from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest import mock

import pytest

from mopidy_youtube import youtube
from mopidy_youtube.resolver import resolve_audio_url

if TYPE_CHECKING:
    from pathlib import Path

EXTRACT = {"url": "https://www.youtube.com/watch?v=abc123defgh", "process": True}


@pytest.fixture
def ydl():
    """A fake yt-dlp: `YoutubeDL(...)` is the context manager that is returned."""
    with mock.patch("mopidy_youtube.resolver.yt_dlp.YoutubeDL") as factory:
        instance = factory.return_value.__enter__.return_value
        instance.extract_info.return_value = {"id": "abc123defgh", "tbr": 129.5}
        instance.process_ie_result.side_effect = lambda info, download: {
            **info,
            "downloaded": download,
        }
        instance.factory = factory
        yield instance


@pytest.fixture
def cached():
    with (
        mock.patch("mopidy_youtube.resolver.cache_image") as cache_image,
        mock.patch("mopidy_youtube.resolver.cache_metadata") as cache_metadata,
    ):
        yield SimpleCaches(cache_image, cache_metadata)


class SimpleCaches:
    def __init__(self, image: mock.Mock, metadata: mock.Mock) -> None:
        self.image = image
        self.metadata = metadata


def video() -> youtube.Video:
    video = youtube.Video()
    video.id = "abc123defgh"
    return video


def resolve(cache_location: Path | None, options: dict[str, Any] | None = None):
    return resolve_audio_url(
        video(),
        ytdl_options=options or {"format": "bestaudio"},
        ytdl_extract_info_options=dict(EXTRACT),
        cache_location=cache_location,
    )


def test_a_track_is_extracted_once_and_what_was_extracted_is_downloaded(
    tmp_path: Path, ydl: mock.Mock, cached: SimpleCaches
):
    assert resolve(tmp_path) is None

    ydl.factory.assert_called_once()  # one yt-dlp: one extraction
    ydl.extract_info.assert_called_once_with(**EXTRACT, download=False)
    ydl.process_ie_result.assert_called_once()
    extracted, download = (
        ydl.process_ie_result.call_args.args[0],
        (ydl.process_ie_result.call_args.kwargs["download"]),
    )
    assert extracted == {"id": "abc123defgh", "tbr": 129.5}
    assert download is True


def test_the_download_goes_to_the_cache_location(
    tmp_path: Path, ydl: mock.Mock, cached: SimpleCaches
):
    resolve(tmp_path, {"format": "bestaudio", "proxy": "http://p"})

    options = ydl.factory.call_args.args[0]
    assert options["outtmpl"] == str(tmp_path / "%(id)s.%(ext)s")
    assert options["format"] == "bestaudio"
    assert options["proxy"] == "http://p"


def test_the_options_of_the_caller_are_left_alone(
    tmp_path: Path, ydl: mock.Mock, cached: SimpleCaches
):
    options = {"format": "bestaudio"}

    resolve(tmp_path, options)

    assert options == {"format": "bestaudio"}


def test_the_image_and_metadata_are_cached_after_the_download(
    tmp_path: Path, ydl: mock.Mock, cached: SimpleCaches
):
    resolve(tmp_path)

    cached.image.assert_called_once()
    assert cached.image.call_args.args[1] == tmp_path
    (_, location, metadata) = cached.metadata.call_args.args
    assert location == tmp_path
    assert metadata["tbr"] == 129.5  # what the download found out


def test_a_live_stream_is_not_downloaded(
    tmp_path: Path, ydl: mock.Mock, cached: SimpleCaches
):
    ydl.extract_info.return_value = {"id": "abc123defgh", "is_live": True}

    assert resolve(tmp_path) is None

    ydl.process_ie_result.assert_not_called()
    cached.image.assert_not_called()
    cached.metadata.assert_not_called()


def test_a_track_that_is_cached_is_not_extracted_at_all(
    tmp_path: Path, ydl: mock.Mock, cached: SimpleCaches
):
    (tmp_path / "abc123defgh.webm").write_bytes(b"audio")

    assert resolve(tmp_path) == f"file://{tmp_path}/abc123defgh.webm"

    ydl.factory.assert_not_called()


def test_without_a_cache_the_url_is_the_one_that_was_extracted(ydl: mock.Mock):
    ydl.extract_info.return_value = {"url": "https://example.com/audio.webm"}

    assert resolve(None) == "https://example.com/audio.webm"

    ydl.extract_info.assert_called_once_with(**EXTRACT, download=False)
    ydl.process_ie_result.assert_not_called()


def test_without_a_cache_and_without_a_url_there_is_nothing_to_play(ydl: mock.Mock):
    ydl.extract_info.return_value = {"id": "abc123defgh"}

    assert resolve(None) is None


def test_a_failed_download_is_an_error_for_the_caller(
    tmp_path: Path, ydl: mock.Mock, cached: SimpleCaches
):
    ydl.process_ie_result.side_effect = RuntimeError("HTTP Error 403")

    with pytest.raises(RuntimeError, match="403"):
        resolve(tmp_path)

    cached.image.assert_not_called()
