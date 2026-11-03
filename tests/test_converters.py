"""Tests for the conversion of videos and playlists to Mopidy models.

The entities are real: a stub api answers `list_videos` / `list_playlists` the way
every api client does (payloads shaped like Data API v3 responses, see
`mopidy_youtube.apis.YouTubeApi`), so what is pinned is the Track / Album a user
of the library gets for the data an api returned, not how the entities store it.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

import pytest
from mopidy.models import Album, Artist, Track

from mopidy_youtube.context import context
from mopidy_youtube.converters import (
    convert_playlist_to_album,
    convert_video_to_track,
)
from mopidy_youtube.youtube import Playlist, Video

if TYPE_CHECKING:
    from collections.abc import Callable

TIMEOUT = 10  # seconds; futures that are never set must fail a test, not hang it

VIDEO_ID = "dQw4w9WgXcQ"
PLAYLIST_ID = "PLFgquLnL59alCl_2TQvOiD5Vgm1hCaGSI"


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


class StubApi:
    """The part of the api that loading videos and playlists needs."""

    def __init__(
        self,
        videos: list[dict[str, Any]] | None = None,
        playlists: list[dict[str, Any]] | None = None,
    ) -> None:
        self.videos = videos or []
        self.playlists = playlists or []

    def list_videos(self, ids: list[str]) -> dict[str, Any]:
        return {"items": [item for item in self.videos if item["id"] in ids]}

    def list_playlists(self, ids: list[str]) -> dict[str, Any]:
        return {"items": [item for item in self.playlists if item["id"] in ids]}

    def list_playlistitems(
        self, playlist_id: str, page: str | None, max_results: int
    ) -> dict[str, Any]:
        # asked for the track number of a video that is on an album
        return {"items": []}


def video_item(
    video_id: str = VIDEO_ID,
    *,
    title: str = "A title",
    channel: str = "A channel",
    channel_id: str | None = "UCchannel",
    duration: str = "PT3M4S",
    **extra: Any,
) -> dict[str, Any]:
    """A video as an api returns it; `channel_id=None` leaves out the channel id."""
    snippet = {"title": title, "channelTitle": channel, "channelId": channel_id}
    return {
        "id": video_id,
        "snippet": {k: v for k, v in snippet.items() if v is not None},
        "contentDetails": {"duration": duration},
        **extra,
    }


def playlist_item(
    playlist_id: str = PLAYLIST_ID,
    *,
    title: str = "A playlist",
    channel: str | None = "An owner",
    count: int | str = 12,
) -> dict[str, Any]:
    thumbnail = {"url": "https://i.ytimg.com/p.jpg", "width": 120, "height": 90}
    snippet = {
        "title": title,
        "channelTitle": channel,
        "thumbnails": {"default": thumbnail},
    }
    return {
        "id": playlist_id,
        "snippet": {k: v for k, v in snippet.items() if v is not None},
        "contentDetails": {"itemCount": count},
    }


def video_track(item: dict[str, Any], **kwargs: Any) -> Track:
    context.api = StubApi(videos=[item])
    return timed(convert_video_to_track, Video.get(item["id"]), **kwargs)


def playlist_album(item: dict[str, Any]) -> Album:
    context.api = StubApi(playlists=[item])
    return timed(convert_playlist_to_album, Playlist.get(item["id"]))


# ---------------------------------------------------------------------------
# convert_video_to_track


def test_a_video_becomes_a_track_of_that_video():
    track = video_track(video_item())

    assert isinstance(track, Track)
    assert track.uri == f"youtube:video:{VIDEO_ID}"
    assert track.name == "A title"
    assert track.comment == VIDEO_ID
    assert track.length == 184000


def test_the_artist_of_a_video_is_its_channel():
    track = video_track(video_item())

    assert track.artists == frozenset(
        {Artist(name="A channel (Channel)", uri="yt:channel:UCchannel")}
    )


def test_the_artist_of_a_video_without_a_channel_id_has_no_uri():
    track = video_track(video_item(channel_id=None))

    assert track.artists == frozenset({Artist(name="A channel", uri=None)})


def test_a_video_without_an_album_is_on_the_youtube_playlist_album():
    track = video_track(video_item())

    assert track.album == Album(name="YouTube Playlist", uri=None)
    assert track.track_no is None


def test_a_video_keeps_the_artists_album_and_track_number_the_api_gave_it():
    item = video_item(
        artists=[
            {"name": "Queen", "uri": "yt:channel:UCqueen"},
            {"name": "Freddie", "uri": None},
        ],
        album={"name": "Opera", "uri": "yt:playlist:MPREb_opera"},
        track_no=3,
    )

    track = video_track(item)

    assert track.artists == frozenset(
        {Artist(name="Queen", uri="yt:channel:UCqueen"), Artist(name="Freddie")}
    )
    assert track.album == Album(name="Opera", uri="yt:playlist:MPREb_opera")
    assert track.track_no == 3


def test_an_artist_that_is_listed_twice_is_one_artist():
    artist = {"name": "Queen", "uri": "yt:channel:UCqueen"}

    track = video_track(video_item(artists=[artist, dict(artist)]))

    assert len(track.artists) == 1


def test_the_album_name_and_id_given_replace_the_album_of_the_video():
    item = video_item(album={"name": "Opera", "uri": "yt:playlist:MPREb_opera"})

    track = video_track(item, album_name="A list", album_id="PL123")

    assert track.album == Album(name="A list", uri="yt:playlist:PL123")


def test_an_empty_album_name_leaves_the_album_of_the_video():
    item = video_item(album={"name": "Opera", "uri": "yt:playlist:MPREb_opera"})

    track = video_track(item, album_name="", album_id="PL123")

    assert track.album == Album(name="Opera", uri="yt:playlist:MPREb_opera")


def test_other_track_fields_are_passed_on():
    track = video_track(video_item(), bitrate=128)

    assert track.bitrate == 128
    assert track.name == "A title"


@pytest.mark.parametrize(
    ("duration", "length"),
    [
        ("PT0S", 0),
        ("PT45S", 45000),
        ("PT10M", 600000),
        ("PT3M4S", 184000),
        ("PT1H2M10S", 3730000),
    ],
)
def test_the_length_is_the_duration_in_milliseconds(duration: str, length: int):
    assert video_track(video_item(duration=duration)).length == length


def test_a_video_the_api_does_not_know_has_length_zero():
    context.api = StubApi()

    track = timed(convert_video_to_track, Video.get(VIDEO_ID))

    assert track.uri == f"youtube:video:{VIDEO_ID}"
    assert track.length == 0


def test_a_failing_api_leaves_a_track_of_length_zero():
    class FailingApi:
        def list_videos(self, ids: list[str]) -> dict[str, Any]:
            msg = "no connection"
            raise RuntimeError(msg)

    context.api = FailingApi()  # type: ignore[assignment]

    track = timed(convert_video_to_track, Video.get(VIDEO_ID))

    assert track.uri == f"youtube:video:{VIDEO_ID}"
    assert track.length == 0


# ---------------------------------------------------------------------------
# convert_playlist_to_album


def test_a_playlist_becomes_an_album_of_that_playlist():
    album = playlist_album(playlist_item())

    assert isinstance(album, Album)
    assert album.uri == f"youtube:playlist:{PLAYLIST_ID}"
    assert album.name == "A playlist"
    assert album.num_tracks == 12


def test_the_artist_of_a_playlist_is_its_owner_without_a_uri():
    album = playlist_album(playlist_item())

    assert album.artists == frozenset({Artist(name="An owner")})


def test_the_owner_of_a_playlist_without_one_is_unknown():
    album = playlist_album(playlist_item(channel=None))

    assert album.artists == frozenset({Artist(name="unknown")})


def test_the_number_of_tracks_may_be_given_as_text():
    assert playlist_album(playlist_item(count="7")).num_tracks == 7


def test_the_number_of_tracks_is_capped_at_the_playlist_maximum():
    context.playlist_max_videos = 5

    assert playlist_album(playlist_item(count=100)).num_tracks == 5
