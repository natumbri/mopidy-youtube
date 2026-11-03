"""Tests for the file cache (audio, thumbnails and track metadata).

Everything happens in `tmp_path`. Thumbnails are downloaded through the session
of the api, which here is a client whose transport is `FakeYouTube`; videos are
real entities, loaded through a stub api.
"""

from __future__ import annotations

import io
import json
import threading
from typing import TYPE_CHECKING, Any

import pytest
from mopidy.models import Track

from mopidy_youtube.apis.client import Client
from mopidy_youtube.cache import (
    InvalidImageFormatError,
    cache_image,
    cache_metadata,
    find_cached_audio_path,
    read_cached_track,
)
from mopidy_youtube.context import context
from mopidy_youtube.converters import convert_video_to_track
from mopidy_youtube.youtube import Video

from tests.support import FakeYouTube

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

    import requests

TIMEOUT = 10  # seconds; futures that are never set must fail a test, not hang it

VIDEO_ID = "dQw4w9WgXcQ"
OTHER_ID = "3BFTio5296w"
THUMBNAIL_URL = f"https://i.ytimg.com/vi_webp/{VIDEO_ID}/maxresdefault.webp"

JPEG = b"\xff\xd8\xff\xe0" + b"\x00\x10JFIF" + bytes(range(200))
WEBP = b"RIFF" + b"\x24\x00\x00\x00WEBPVP8 " + bytes(range(200))


def timed[T](fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Call `fn` in a daemon thread and fail after `TIMEOUT` seconds."""
    outcome: dict[str, Any] = {}

    def run() -> None:
        try:
            outcome["value"] = fn(*args, **kwargs)
        except BaseException as e:
            outcome["error"] = e

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(TIMEOUT)
    if thread.is_alive():
        pytest.fail(f"{fn.__name__} did not finish within {TIMEOUT} seconds")
    if "error" in outcome:
        raise outcome["error"]
    return outcome["value"]


class StreamingYouTube(FakeYouTube):
    """A `FakeYouTube` whose responses can be read as a stream, like a download."""

    def send(  # noqa: PLR0917 - signature of requests' BaseAdapter
        self,
        request: requests.PreparedRequest,
        stream: bool = False,
        timeout: Any = None,
        verify: Any = True,
        cert: Any = None,
        proxies: Any = None,
    ) -> requests.Response:
        response = super().send(request, stream, timeout, verify, cert, proxies)
        response.raw = io.BytesIO(response._content)  # type: ignore[arg-type]
        response._content = False
        return response


class StubApi:
    """What loading a video needs from the api."""

    def list_videos(self, ids: list[str]) -> dict[str, Any]:
        return {
            "items": [
                {
                    "id": video_id,
                    "snippet": {
                        "title": f"Title of {video_id}",
                        "channelTitle": "A channel",
                        "channelId": "UCchannel",
                    },
                    "contentDetails": {"duration": "PT3M4S"},
                }
                for video_id in ids
            ]
        }


@pytest.fixture
def site() -> StreamingYouTube:
    return StreamingYouTube()


@pytest.fixture
def downloads(site: StreamingYouTube) -> Iterator[Client]:
    """The api whose session downloads the thumbnails."""
    client = Client(None, {})
    site.attach(client)
    context.api = client  # type: ignore[assignment]
    yield client
    client.close()


@pytest.fixture
def video() -> Video:
    context.api = StubApi()  # type: ignore[assignment]
    return Video.get(VIDEO_ID)


def files(directory: Path) -> set[str]:
    return {path.name for path in directory.iterdir()}


# ---------------------------------------------------------------------------
# find_cached_audio_path


@pytest.mark.parametrize("extension", ["webm", "m4a", "mp3", "ogg"])
def test_a_cached_audio_file_is_found_as_a_file_uri(tmp_path: Path, extension: str):
    (tmp_path / f"{VIDEO_ID}.{extension}").write_bytes(b"audio")

    path = find_cached_audio_path(tmp_path, VIDEO_ID)

    assert path == f"file://{tmp_path}/{VIDEO_ID}.{extension}"


def test_the_cache_location_may_be_a_string(tmp_path: Path):
    (tmp_path / f"{VIDEO_ID}.m4a").write_bytes(b"audio")

    assert find_cached_audio_path(str(tmp_path), VIDEO_ID) == (
        f"file://{tmp_path}/{VIDEO_ID}.m4a"
    )


def test_a_video_that_is_not_cached_has_no_audio_path(tmp_path: Path):
    (tmp_path / f"{OTHER_ID}.webm").write_bytes(b"audio of another video")

    assert find_cached_audio_path(tmp_path, VIDEO_ID) is None


@pytest.mark.parametrize("name", [f"{VIDEO_ID}.json", f"{VIDEO_ID}.jpg", VIDEO_ID])
def test_only_audio_files_are_audio(tmp_path: Path, name: str):
    (tmp_path / name).write_bytes(b"not audio")

    assert find_cached_audio_path(tmp_path, VIDEO_ID) is None


def test_the_audio_of_a_video_is_not_found_by_a_prefix_of_its_id(tmp_path: Path):
    (tmp_path / f"{VIDEO_ID}x.webm").write_bytes(b"audio")
    (tmp_path / f"x{VIDEO_ID}.webm").write_bytes(b"audio")

    assert find_cached_audio_path(tmp_path, VIDEO_ID) is None


def test_one_of_the_formats_is_chosen_when_there_are_several(tmp_path: Path):
    (tmp_path / f"{VIDEO_ID}.webm").write_bytes(b"audio")
    (tmp_path / f"{VIDEO_ID}.mp3").write_bytes(b"audio")

    assert find_cached_audio_path(tmp_path, VIDEO_ID) in {
        f"file://{tmp_path}/{VIDEO_ID}.webm",
        f"file://{tmp_path}/{VIDEO_ID}.mp3",
    }


@pytest.mark.parametrize("location", [None, ""])
def test_nothing_is_found_without_a_cache_location(location: str | None):
    assert find_cached_audio_path(location, VIDEO_ID) is None


# ---------------------------------------------------------------------------
# cache_image


def test_a_jpeg_thumbnail_is_cached_as_jpg(
    tmp_path: Path, video: Video, site: StreamingYouTube, downloads: Client
):
    site.add("GET", THUMBNAIL_URL, body=JPEG)

    timed(cache_image, video, tmp_path)

    assert files(tmp_path) == {f"{VIDEO_ID}.jpg"}
    assert (tmp_path / f"{VIDEO_ID}.jpg").read_bytes() == JPEG


def test_a_webp_thumbnail_is_cached_as_webp(
    tmp_path: Path, video: Video, site: StreamingYouTube, downloads: Client
):
    site.add("GET", THUMBNAIL_URL, body=WEBP)

    timed(cache_image, video, tmp_path)

    assert files(tmp_path) == {f"{VIDEO_ID}.webp"}
    assert (tmp_path / f"{VIDEO_ID}.webp").read_bytes() == WEBP


def test_the_thumbnail_of_the_video_is_what_is_downloaded(
    tmp_path: Path, video: Video, site: StreamingYouTube, downloads: Client
):
    site.add("GET", THUMBNAIL_URL, body=WEBP)

    timed(cache_image, video, str(tmp_path))

    (request,) = site.calls("GET", "https://")
    assert request.url == THUMBNAIL_URL
    assert (tmp_path / f"{VIDEO_ID}.webp").exists()


def test_the_host_and_content_length_of_the_session_are_not_sent(
    tmp_path: Path, video: Video, site: StreamingYouTube
):
    client = Client(None, {"Host": "api.example.com", "Content-Length": "0"})
    site.attach(client)
    context.api = client  # type: ignore[assignment]
    site.add("GET", THUMBNAIL_URL, body=WEBP)

    try:
        timed(cache_image, video, tmp_path)
    finally:
        client.close()

    (request,) = site.calls("GET", THUMBNAIL_URL)
    assert "host" not in request.headers
    assert "content-length" not in request.headers


@pytest.mark.parametrize("cached", [f"{VIDEO_ID}.webp", f"{VIDEO_ID}.jpg"])
def test_a_thumbnail_that_is_cached_is_not_downloaded_again(
    tmp_path: Path,
    video: Video,
    site: StreamingYouTube,
    downloads: Client,
    cached: str,
):
    (tmp_path / cached).write_bytes(b"what was cached")

    timed(cache_image, video, tmp_path)

    assert not site.requests
    assert files(tmp_path) == {cached}
    assert (tmp_path / cached).read_bytes() == b"what was cached"


def test_the_thumbnail_of_another_video_does_not_count_as_cached(
    tmp_path: Path, video: Video, site: StreamingYouTube, downloads: Client
):
    (tmp_path / f"{OTHER_ID}.jpg").write_bytes(b"another video")
    site.add("GET", THUMBNAIL_URL, body=JPEG)

    timed(cache_image, video, tmp_path)

    assert files(tmp_path) == {f"{OTHER_ID}.jpg", f"{VIDEO_ID}.jpg"}


def test_a_thumbnail_that_cannot_be_downloaded_is_not_cached(
    tmp_path: Path, video: Video, site: StreamingYouTube, downloads: Client
):
    site.add("GET", THUMBNAIL_URL, body=b"not found", status=404)

    timed(cache_image, video, tmp_path)

    assert len(site.requests) == 1
    assert files(tmp_path) == set()


def test_a_download_that_is_not_an_image_is_an_error_and_is_not_cached(
    tmp_path: Path, video: Video, site: StreamingYouTube, downloads: Client
):
    site.add("GET", THUMBNAIL_URL, body=b"<html>no image here</html>")

    with pytest.raises(InvalidImageFormatError, match=VIDEO_ID):
        timed(cache_image, video, tmp_path)

    assert files(tmp_path) == set()


@pytest.mark.parametrize("location", [None, ""])
def test_nothing_is_downloaded_without_a_cache_location(
    video: Video, site: StreamingYouTube, downloads: Client, location: str | None
):
    timed(cache_image, video, location)

    assert not site.requests


# ---------------------------------------------------------------------------
# cache_metadata


def metadata_of(directory: Path, video_id: str = VIDEO_ID) -> dict[str, Any]:
    return json.loads((directory / f"{video_id}.json").read_text(encoding="utf-8"))


def test_the_metadata_of_a_video_is_cached_as_json(tmp_path: Path, video: Video):
    timed(cache_metadata, video, tmp_path, {"tbr": 129.7})

    assert files(tmp_path) == {f"{VIDEO_ID}.json"}
    metadata = metadata_of(tmp_path)
    assert metadata["uri"] == f"youtube:video:{VIDEO_ID}"
    assert metadata["name"] == f"Title of {VIDEO_ID}"
    assert metadata["length"] == 184000
    assert metadata["comment"] == VIDEO_ID
    assert [artist["name"] for artist in metadata["artists"]] == ["A channel (Channel)"]
    assert metadata["album"]["name"] == "YouTube Playlist"


def test_the_bitrate_is_the_whole_number_of_kbit_per_second(
    tmp_path: Path, video: Video
):
    timed(cache_metadata, video, tmp_path, {"tbr": 129.7})

    assert metadata_of(tmp_path)["bitrate"] == 129


def test_the_bitrate_is_zero_when_it_is_not_known(tmp_path: Path, video: Video):
    timed(cache_metadata, video, str(tmp_path), {})

    assert metadata_of(tmp_path)["bitrate"] == 0


def test_metadata_that_is_cached_is_left_alone(tmp_path: Path, video: Video):
    path = tmp_path / f"{VIDEO_ID}.json"
    path.write_text('{"name": "what was cached"}', encoding="utf-8")

    timed(cache_metadata, video, tmp_path, {"tbr": 128})

    assert path.read_text(encoding="utf-8") == '{"name": "what was cached"}'
    assert files(tmp_path) == {path.name}


@pytest.mark.parametrize("malformed", ["", "{not json", '{"name": "cut off'])
def test_malformed_metadata_is_rebuilt(tmp_path: Path, video: Video, malformed: str):
    (tmp_path / f"{VIDEO_ID}.json").write_text(malformed, encoding="utf-8")

    timed(cache_metadata, video, tmp_path, {"tbr": 128})

    assert files(tmp_path) == {f"{VIDEO_ID}.json"}
    assert metadata_of(tmp_path)["name"] == f"Title of {VIDEO_ID}"
    assert metadata_of(tmp_path)["bitrate"] == 128


def test_metadata_that_is_not_utf8_is_rebuilt(tmp_path: Path, video: Video):
    (tmp_path / f"{VIDEO_ID}.json").write_bytes(b"\xff\xfe\x00 not utf-8")

    timed(cache_metadata, video, tmp_path, {})

    assert metadata_of(tmp_path)["uri"] == f"youtube:video:{VIDEO_ID}"


def test_the_metadata_of_other_videos_is_not_touched(tmp_path: Path, video: Video):
    (tmp_path / f"{OTHER_ID}.json").write_text("{not json", encoding="utf-8")

    timed(cache_metadata, video, tmp_path, {})

    assert files(tmp_path) == {f"{OTHER_ID}.json", f"{VIDEO_ID}.json"}
    assert (tmp_path / f"{OTHER_ID}.json").read_text(encoding="utf-8") == "{not json"


@pytest.mark.parametrize("location", [None, ""])
def test_no_metadata_is_cached_without_a_cache_location(
    tmp_path: Path, video: Video, location: str | None
):
    timed(cache_metadata, video, location, {"tbr": 128})

    assert files(tmp_path) == set()


def test_cached_metadata_can_be_read_back_as_the_track(tmp_path: Path, video: Video):
    timed(cache_metadata, video, tmp_path, {"tbr": 128})

    track = Track.model_validate(metadata_of(tmp_path))

    assert track == timed(convert_video_to_track, video, bitrate=128)


def test_the_cached_track_is_read_back_by_read_cached_track(
    tmp_path: Path, video: Video
):
    timed(cache_metadata, video, tmp_path, {"tbr": 128})

    assert read_cached_track(tmp_path, VIDEO_ID) == timed(
        convert_video_to_track, video, bitrate=128
    )


def test_metadata_cached_by_older_versions_can_still_be_read(
    tmp_path: Path, video: Video
):
    track = timed(convert_video_to_track, video, bitrate=128)
    # what versions before the fix wrote: the discriminator was called `model`
    old_format = track.model_dump(mode="json")
    assert "model" in old_format
    (tmp_path / f"{VIDEO_ID}.json").write_text(json.dumps(old_format), encoding="utf-8")

    assert read_cached_track(tmp_path, VIDEO_ID) == track


def test_reading_metadata_that_was_never_cached_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        read_cached_track(tmp_path, "nothing")
