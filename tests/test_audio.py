from concurrent.futures import Future
from pathlib import Path
from typing import Any
from unittest import mock

import pykka
import pytest

from mopidy_youtube import youtube
from mopidy_youtube.async_utils import is_future_set
from mopidy_youtube.audio import AudioResolver
from mopidy_youtube.context import context


def new_video(video_id: str, *, with_future: bool = True) -> youtube.Video:
    video = youtube.Video()
    video.id = video_id
    if with_future:
        # reading `audio_url` would start a real download
        video.__dict__["_audio_url"] = pykka.ThreadingFuture()
    return video


def downloading(path: Path, *, done: int, total: int | None) -> dict[str, Any]:
    return {
        "status": "downloading",
        "filename": str(path),
        "downloaded_bytes": done,
        "total_bytes": total,
        "info_dict": {},
    }


def test_publishes_an_http_url_once_two_percent_of_a_webm_is_cached(
    tmp_path: Path,
):
    context.http_port = 6680
    video = new_video("vid1")
    resolver = AudioResolver(video)
    path = tmp_path / "vid1.webm"

    resolver.on_progress(downloading(path, done=100, total=10_000))  # 1%
    assert not is_future_set(video._audio_url)  # still unset

    resolver.on_progress(downloading(path, done=300, total=10_000))  # 3%

    assert video._audio_url.get(timeout=0) == "http://localhost:6680/youtube/vid1.webm"
    assert video.total_bytes == 10_000


def test_does_not_stream_containers_that_need_the_end_of_the_file(tmp_path: Path):
    video = new_video("vid2")
    resolver = AudioResolver(video)

    resolver.on_progress(downloading(tmp_path / "vid2.m4a", done=9_000, total=10_000))

    assert not is_future_set(video._audio_url)


def test_does_not_stream_without_an_exact_size(tmp_path: Path):
    video = new_video("vid3")
    resolver = AudioResolver(video)

    resolver.on_progress(downloading(tmp_path / "vid3.webm", done=9_000, total=None))

    assert not is_future_set(video._audio_url)


def test_a_finished_download_publishes_the_file_and_remembers_it(tmp_path: Path):
    video = new_video("vid4")
    path = tmp_path / "vid4.m4a"
    path.write_bytes(b"x" * 123)

    AudioResolver(video).on_progress({"status": "finished", "filename": str(path)})

    assert video._audio_url.get(timeout=0) == f"file://{path}"
    assert video.cached_file_uri == f"file://{path}"
    assert video.total_bytes == 123


def test_a_finished_download_does_not_replace_the_early_http_url(tmp_path: Path):
    video = new_video("vid5")
    resolver = AudioResolver(video)
    path = tmp_path / "vid5.webm"
    path.write_bytes(b"x" * 10_000)

    resolver.on_progress(downloading(path, done=5_000, total=10_000))
    resolver.on_progress({"status": "finished", "filename": str(path)})

    assert video._audio_url.get(timeout=0).startswith("http://localhost")
    assert video.cached_file_uri == f"file://{path}"


def test_a_prefetch_moves_to_the_interactive_pool_when_the_track_is_played():
    video = new_video("vid6", with_future=False)
    prefetch_pool = mock.Mock()
    interactive_pool = mock.Mock()
    queued: Future[None] = Future()
    prefetch_pool.submit.return_value = queued

    with mock.patch.object(
        youtube.Video,
        "_audio_pool",
        side_effect=lambda *, prefetch: prefetch_pool if prefetch else interactive_pool,
    ):
        video.prefetch_audio_url()
        video.promote_audio_url()

    prefetch_pool.submit.assert_called_once_with(video._load_audio_url)
    interactive_pool.submit.assert_called_once_with(video._load_audio_url)
    assert queued.cancelled()


def test_a_prefetch_that_has_already_started_is_left_alone():
    video = new_video("vid7", with_future=False)
    prefetch_pool = mock.Mock()
    interactive_pool = mock.Mock()
    running: Future[None] = Future()
    running.set_running_or_notify_cancel()
    prefetch_pool.submit.return_value = running

    with mock.patch.object(
        youtube.Video,
        "_audio_pool",
        side_effect=lambda *, prefetch: prefetch_pool if prefetch else interactive_pool,
    ):
        video.prefetch_audio_url()
        video.promote_audio_url()

    interactive_pool.submit.assert_not_called()


def test_a_failed_load_is_not_remembered_so_the_next_request_retries():
    video = new_video("vid8", with_future=False)
    pool = mock.Mock()

    with (
        mock.patch.object(youtube.Video, "_audio_pool", return_value=pool),
        mock.patch("mopidy_youtube.youtube.AudioResolver") as resolver,
    ):
        resolver.return_value.run.side_effect = RuntimeError("boom")
        first = video.audio_url
        video._load_audio_url()

        assert first.get(timeout=0) is None
        second = video.audio_url

    assert second is not first
    assert pool.submit.call_count == 2


def test_a_failed_prefetch_is_not_retried_straight_away():
    video = new_video("vid9", with_future=False)
    pool = mock.Mock()

    with (
        mock.patch.object(youtube.Video, "_audio_pool", return_value=pool),
        mock.patch("mopidy_youtube.youtube.AudioResolver") as resolver,
    ):
        resolver.return_value.run.side_effect = RuntimeError("boom")
        video.prefetch_audio_url()
        video._load_audio_url()
        video.prefetch_audio_url()

    assert pool.submit.call_count == 1


def test_a_failure_after_the_early_http_url_discards_it():
    video = new_video("vid10", with_future=False)
    pool = mock.Mock()

    def publish_then_fail() -> None:
        video._audio_url.set("http://localhost:6680/youtube/vid10.webm")
        msg = "download died"
        raise RuntimeError(msg)

    with (
        mock.patch.object(youtube.Video, "_audio_pool", return_value=pool),
        mock.patch("mopidy_youtube.youtube.AudioResolver") as resolver,
    ):
        resolver.return_value.run.side_effect = publish_then_fail
        first = video.audio_url
        video._load_audio_url()
        second = video.audio_url

    assert second is not first
    assert video.total_bytes == 0


@pytest.mark.parametrize("cached", [True, False])
def test_resolver_hands_the_cache_location_to_the_resolver(
    tmp_path: Path, cached: bool
):
    context.cache_location = tmp_path if cached else None
    video = new_video("vid11")

    with (
        mock.patch.object(context, "youtube_dl") as ytdl,
        mock.patch("mopidy_youtube.audio.resolve_audio_url") as resolve,
    ):
        resolve.return_value = "https://example.com/a.webm"
        AudioResolver(video).run()

    kwargs = resolve.call_args.kwargs
    assert kwargs["cache_location"] == (tmp_path if cached else None)
    assert kwargs["youtube_dl"] is ytdl.return_value
    assert kwargs["ytdl_extract_info_options"]["url"].endswith("watch?v=vid11")
    assert "nopart" not in kwargs["ytdl_options"]
    assert video._audio_url.get(timeout=0) == "https://example.com/a.webm"
