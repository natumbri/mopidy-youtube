"""Tests for the YouTube Music client.

`ytmusicapi.YTMusic` is replaced by a mock that answers with real responses,
recorded anonymously from YouTube Music and trimmed to what the client reads
(`tests/fixtures/music/`). The exceptions are `get_library_playlists` and
`get_library_albums`, which need a login: the library albums reuse the shape of
the album search results, which is the same, and the library playlists are
written by hand after the ytmusicapi documentation.

To refresh a fixture, call the same ytmusicapi method with the same arguments
(see the comments above each fixture helper) and trim long lists.
"""

from __future__ import annotations

import logging
from concurrent.futures import Future
from typing import TYPE_CHECKING, Any
from unittest import mock

import pytest

from mopidy_youtube.apis.youtube_music import Music
from mopidy_youtube.context import context
from mopidy_youtube.youtube import Entry, Playlist, Video

from tests.support import load_fixture

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator


class LoginRequiredError(Exception):
    """Stands in for the error ytmusicapi raises for calls that need a login.

    Its class has moved between ytmusicapi releases; the code only catches
    `Exception`.
    """


ANONYMOUS = {"Cookie": "PREF=hl=en; CONSENT=YES+20210329;"}

# ids in the fixtures
SONG_ID = "fJ9rUzIMcZQ"  # get_song, get_watch_playlist
RELATED_ID = "MPTRt_wUbiMNbaE6O"  # the "related" browse id of the watch playlist
ALBUM_ID = "MPREb_eEpQf8QskKl"  # search(filter="albums"), get_album
OTHER_ALBUM_ID = "MPREb_ppvh6pdaiCc"
OLAK_ID = "OLAK5uy_mQGa-V4qspfisNHu1kXthY1w93yJNT0rw"  # audio playlist of the album
PLAYLIST_ID = "PL4fGSI1pDJn6jXS_Tv_N9B8Z0HTRVJE0m"  # get_playlist
ARTIST_ID = "UCEPMVbUzImPl4p8k4LkGevA"  # get_artist (Queen)
USER_ID = "UCSHZKyawb77ixDdsGog4iWA"  # get_user (Lex Fridman), not an artist
OWN_CHANNEL = "UCownChannelOfTheUser0"

ALBUM_TITLE = "A Night At The Opera"
UNAVAILABLE_ID = "aaaaaaaaaaa"
RELATED_VIDEO_IDS = ["U-Ooxpz0Eqk", "-SaUrDhp034", "oMfMUfgjiLg", "ulRXvH8VOl8"]
RELATED_ALBUM_IDS = {
    "MPREb_4EH1Eo0cgGr",
    "MPREb_8lrA5KA4Gfv",
    "MPREb_fN7uwe7VDV6",
    "MPREb_jnYA50rlu4H",
}
WATCH_VIDEO_IDS = [SONG_ID, "04854XqcfCY", "kR4zpS-ky9o"]
ALBUM_TRACK_IDS = ["kqVpk0qxmfA", "OU6EyXcFBxA", "oaEM4JYFPfw", "HaZpZQG2z10"]
PLAYLIST_TRACK_IDS = ["D968qfUZMUE", "GxChUrrY4bc", "7mDDM0eBWR0", "F_EGihOgXsg"]
ARTIST_ALBUM_IDS = [
    "OLAK5uy_kol_swyj7Jpirgq7d5UnCAghTEX4wLdUg",
    "OLAK5uy_mo3flQUFtMFqJlzckSzj63duhUMS6gv5Q",
    "OLAK5uy_n-Fn_Y9_8eezE8hAAvdPJHUuuKRvzVjfw",
]


def fixture(name: str) -> Any:
    """A fresh copy of the recorded response `name`."""
    return load_fixture(f"music/{name}.json")


def get_song(video_id: str) -> dict[str, Any]:
    """`YTMusic.get_song(video_id)`"""
    if video_id == UNAVAILABLE_ID:
        return fixture("song_unavailable")
    return fixture("songs")[video_id]


def get_album(browse_id: str) -> dict[str, Any]:
    """`YTMusic.get_album(browse_id)`: one album, whatever the id."""
    return fixture("album")


def library_playlists() -> list[dict[str, Any]]:
    """`YTMusic.get_library_playlists()`, which needs a login (see the docstring)."""
    thumbnail = {"url": "https://example.com/p.jpg", "width": 226, "height": 226}
    return [
        {
            "playlistId": "PLlibrary0000000000001",
            "title": "My favourites",
            "thumbnails": [thumbnail],
            "count": "1,234",
        },
        {
            "playlistId": "LM",
            "title": "Your Likes",
            "thumbnails": [thumbnail],
            "count": "99",
        },
    ]


class InlineExecutor:
    """Runs jobs when they are submitted, so that background work is awaited."""

    def __init__(self) -> None:
        self.submitted: list[Any] = []

    def submit(self, fn: Callable[..., Any], *args: Any) -> Future[Any]:
        self.submitted.append(fn)
        future: Future[Any] = Future()
        try:
            future.set_result(fn(*args))
        except Exception as e:
            future.set_exception(e)
        return future

    def shutdown(self, *, wait: bool = True, cancel_futures: bool = False) -> None:
        pass


@pytest.fixture(autouse=True)
def clean_entry_cache() -> Iterator[None]:
    Entry.cache.clear()
    yield
    Entry.cache.clear()


@pytest.fixture
def ytm_class() -> Iterator[mock.MagicMock]:
    """The patched `YTMusic` class; `ytm_class.return_value` is the client."""
    with mock.patch("mopidy_youtube.apis.youtube_music.YTMusic") as ytm_class:
        yield ytm_class


@pytest.fixture
def fallback() -> mock.Mock:
    api = mock.Mock()
    api.list_related_videos.return_value = {"items": []}
    return api


@pytest.fixture
def music(ytm_class: mock.MagicMock, fallback: mock.Mock) -> Iterator[Music]:
    client = Music(None, ANONYMOUS, fallback)
    client._lookup_executor.shutdown()
    client._lookup_executor = InlineExecutor()  # type: ignore[assignment]
    yield client
    client.close()


@pytest.fixture
def ytmusic(music: Music) -> mock.MagicMock:
    return music.ytmusic  # type: ignore[return-value]


def search_results(filter: str, **_: Any) -> list[dict[str, Any]]:
    return fixture("search_albums" if filter == "albums" else "search_songs")


def answer_related_calls(ytmusic: mock.MagicMock) -> None:
    ytmusic.get_watch_playlist.side_effect = lambda _: fixture("watch_playlist")
    ytmusic.get_song_related.side_effect = lambda _: fixture("song_related")
    ytmusic.get_song.side_effect = get_song
    ytmusic.get_album.side_effect = get_album


def video_ids(items: list[dict[str, Any]]) -> list[str]:
    return [item["id"]["videoId"] for item in items]


def future_value(entity: Video | Playlist, field: str) -> Any:
    """The loaded value of an entity field; fails instead of starting a load."""
    return entity.__dict__["_" + field].get(timeout=0)


def playlist_value(playlist_id: str, field: str) -> Any:
    return future_value(Playlist.get(playlist_id), field)


def video_value(video_id: str, field: str) -> Any:
    return future_value(Video.get(video_id), field)


def playlist_video_ids(playlist_id: str) -> list[str]:
    return [video.id for video in playlist_value(playlist_id, "videos")]


# ---------------------------------------------------------------------------
# construction


def test_it_is_anonymous_without_a_login_cookie(
    ytm_class: mock.MagicMock, fallback: mock.Mock
):
    music = Music(None, ANONYMOUS, fallback)

    assert ytm_class.call_args.kwargs["auth"] is None
    assert music.ytmusic is ytm_class.return_value
    music.close()


def test_it_falls_back_to_an_anonymous_client_when_the_login_is_rejected(
    ytm_class: mock.MagicMock, fallback: mock.Mock, caplog: pytest.LogCaptureFixture
):
    anonymous = mock.MagicMock()
    ytm_class.side_effect = [ValueError("bad headers"), anonymous]

    with caplog.at_level(logging.ERROR, logger="mopidy_youtube"):
        music = Music(None, {"Cookie": "broken"}, fallback)

    assert music.ytmusic is anonymous
    assert "YTMusic init error: bad headers" in caplog.text
    music.close()


# ---------------------------------------------------------------------------
# search


def test_search_returns_the_albums_and_then_the_songs(
    music: Music, ytmusic: mock.MagicMock
):
    ytmusic.search.side_effect = search_results
    ytmusic.get_album.side_effect = get_album

    items = music.search("a night at the opera")["items"]

    albums, songs = items[:2], items[2:]
    assert {item["id"]["playlistId"] for item in albums} == {
        ALBUM_ID,
        OTHER_ALBUM_ID,
    }
    assert all(item["id"]["kind"] == "youtube#playlist" for item in albums)
    assert video_ids(songs) == ["BSTsnWoslP4", "_Xsu44ppnFQ", "soHI4sKPQ3E"]
    assert all(item["id"]["kind"] == "youtube#video" for item in songs)


def test_search_asks_for_albums_and_songs_with_the_result_limit(
    music: Music, ytmusic: mock.MagicMock
):
    context.search_results = 7
    ytmusic.search.side_effect = search_results
    ytmusic.get_album.side_effect = get_album

    music.search("queen")

    searches = {
        call.kwargs["filter"]: call.kwargs for call in ytmusic.search.call_args_list
    }
    assert searches == {
        "albums": {"query": "queen", "filter": "albums", "limit": 7},
        "songs": {"query": "queen", "filter": "songs", "limit": 7},
    }


def test_search_keeps_no_more_songs_than_the_result_limit(
    music: Music, ytmusic: mock.MagicMock
):
    context.search_results = 2
    ytmusic.search.side_effect = lambda **kwargs: (
        [] if kwargs["filter"] == "albums" else fixture("search_songs")
    )

    items = music.search("queen")["items"]

    assert video_ids(items) == ["BSTsnWoslP4", "_Xsu44ppnFQ"]


def test_search_without_results_is_empty(music: Music, ytmusic: mock.MagicMock):
    ytmusic.search.return_value = []

    assert music.search("nothing") == {"items": []}


def test_search_songs_converts_songs_and_skips_those_without_an_id(
    music: Music, ytmusic: mock.MagicMock
):
    results = fixture("search_songs")
    results[1]["videoId"] = None
    ytmusic.search.return_value = results

    songs = music.search_songs("queen")

    assert video_ids(songs) == ["BSTsnWoslP4", "soHI4sKPQ3E"]
    assert songs[0]["snippet"]["title"] == "Bohemian Rhapsody"
    assert songs[0]["snippet"]["channelTitle"] == "Queen"
    assert songs[0]["contentDetails"]["duration"] == "PT5M55S"


def test_search_albums_returns_playlists_named_by_their_browse_id(
    music: Music, ytmusic: mock.MagicMock
):
    ytmusic.search.return_value = fixture("search_albums")
    ytmusic.get_album.side_effect = get_album

    albums = music.search_albums("a night at the opera")

    assert sorted(a["id"]["playlistId"] for a in albums) == [ALBUM_ID, OTHER_ALBUM_ID]
    assert {call.args[0] for call in ytmusic.get_album.call_args_list} == {
        ALBUM_ID,
        OTHER_ALBUM_ID,
    }
    album = albums[0]
    assert album["snippet"]["title"] == ALBUM_TITLE
    assert album["snippet"]["channelTitle"] == "Queen"
    assert album["contentDetails"]["itemCount"] == 12


# ---------------------------------------------------------------------------
# process_albums


def test_process_albums_creates_the_playlist_and_video_entities(
    music: Music, ytmusic: mock.MagicMock
):
    ytmusic.get_album.side_effect = get_album

    music.process_albums(fixture("search_albums")[:1])

    assert playlist_value(ALBUM_ID, "title") == ALBUM_TITLE
    assert playlist_video_ids(ALBUM_ID) == ALBUM_TRACK_IDS
    assert video_value("kqVpk0qxmfA", "title") == "Death On Two Legs (Dedicated To...)"
    assert video_value("kqVpk0qxmfA", "track_no") == 1


def test_process_albums_skips_an_album_that_cannot_be_fetched(
    music: Music, ytmusic: mock.MagicMock, caplog: pytest.LogCaptureFixture
):
    def get_album_or_fail(browse_id: str) -> dict[str, Any]:
        if browse_id == OTHER_ALBUM_ID:
            msg = "no such album"
            raise RuntimeError(msg)
        return get_album(browse_id)

    ytmusic.get_album.side_effect = get_album_or_fail

    with caplog.at_level(logging.ERROR, logger="mopidy_youtube"):
        albums = music.process_albums(fixture("search_albums"))

    assert [a["id"]["playlistId"] for a in albums] == [ALBUM_ID]
    assert "process_albums get_album error no such album" in caplog.text
    assert OTHER_ALBUM_ID in caplog.text


def test_process_albums_without_results_is_empty(music: Music):
    assert music.process_albums([]) == []


# ---------------------------------------------------------------------------
# list_related_videos


def test_related_videos_are_the_related_songs_then_the_watch_playlist_then_the_jAPI(
    music: Music, ytmusic: mock.MagicMock, fallback: mock.Mock
):
    answer_related_calls(ytmusic)
    fallback.list_related_videos.return_value = {
        "items": [{"id": {"videoId": "fromFallback"}}]
    }

    items = music.list_related_videos(SONG_ID)["items"]

    assert video_ids(items) == [
        *RELATED_VIDEO_IDS,
        *WATCH_VIDEO_IDS,
        "fromFallback",
    ]
    ytmusic.get_watch_playlist.assert_called_once_with(SONG_ID)
    ytmusic.get_song_related.assert_called_once_with(RELATED_ID)
    fallback.list_related_videos.assert_called_once_with(SONG_ID)


def test_related_videos_take_album_and_artists_from_the_related_track(
    music: Music, ytmusic: mock.MagicMock
):
    answer_related_calls(ytmusic)

    items = music.list_related_videos(SONG_ID)["items"]

    by_id = {item["id"]["videoId"]: item for item in items}
    rainbow = by_id["U-Ooxpz0Eqk"]
    assert (
        rainbow["snippet"]["title"]
        == "Somewhere Over The Rainbow/What A Wonderful World"
    )
    assert rainbow["snippet"]["channelTitle"] == "Israel Kamakawiwo'ole"
    assert rainbow["contentDetails"]["duration"] == "PT0H05M08S"
    assert rainbow["album"] == {
        "name": "Facing Future",
        "uri": "yt:playlist:MPREb_4EH1Eo0cgGr",
    }
    assert rainbow["artists"] == [
        {
            "name": "Israel Kamakawiwo'ole",
            "uri": "yt:channel:UCDrbjok3kk04f-SByjhpLYg",
        }
    ]
    # a song of the watch playlist is not a related track: only the uploader is known
    live = by_id[SONG_ID]
    assert "album" not in live
    assert live["artists"] == [
        {"name": "Queen", "uri": "yt:channel:UCiMhD4jzUqG-IgPzUmmytRQ"}
    ]


def test_related_videos_look_up_the_albums_of_the_related_tracks(
    music: Music, ytmusic: mock.MagicMock
):
    answer_related_calls(ytmusic)

    music.list_related_videos(SONG_ID)

    assert {call.args[0] for call in ytmusic.get_album.call_args_list} == (
        RELATED_ALBUM_IDS
    )
    # ... which creates the playlists, so that opening one needs no request
    assert music._lookup_executor.submitted == [music.list_playlists]  # type: ignore[attr-defined]
    for album_id in RELATED_ALBUM_IDS:
        assert playlist_value(album_id, "title") == ALBUM_TITLE
        assert len(playlist_value(album_id, "videos")) == 4


def test_a_related_album_without_an_id_is_not_looked_up(
    music: Music, ytmusic: mock.MagicMock
):
    answer_related_calls(ytmusic)
    related = fixture("song_related")
    related[0]["contents"][0]["album"] = {"name": "A Single", "id": None}
    ytmusic.get_song_related.side_effect = lambda _: related

    items = music.list_related_videos(SONG_ID)["items"]

    assert len(items) == 7
    assert {call.args[0] for call in ytmusic.get_album.call_args_list} == (
        RELATED_ALBUM_IDS - {"MPREb_4EH1Eo0cgGr"}
    )


def test_a_related_track_without_an_album_is_still_returned(
    music: Music, ytmusic: mock.MagicMock
):
    answer_related_calls(ytmusic)
    related = fixture("song_related")
    related[0]["contents"][0]["album"] = None
    ytmusic.get_song_related.side_effect = lambda _: related

    items = music.list_related_videos(SONG_ID)["items"]

    assert video_ids(items)[:4] == RELATED_VIDEO_IDS
    assert "album" not in items[0]


def test_enough_related_songs_need_neither_the_watch_playlist_nor_the_jAPI(
    music: Music, ytmusic: mock.MagicMock, fallback: mock.Mock
):
    answer_related_calls(ytmusic)
    template = fixture("song_related")
    ids = [f"related{i:04}" for i in range(10)]
    template[0]["contents"] = [
        {**template[0]["contents"][0], "videoId": video_id} for video_id in ids
    ]
    ytmusic.get_song_related.side_effect = lambda _: template

    def song(video_id: str) -> dict[str, Any]:
        response = get_song("U-Ooxpz0Eqk")
        response["videoDetails"]["videoId"] = video_id
        return response

    ytmusic.get_song.side_effect = song

    items = music.list_related_videos(SONG_ID)["items"]

    assert video_ids(items) == ids
    assert ytmusic.get_song.call_count == 10
    fallback.list_related_videos.assert_not_called()


def test_a_failing_related_song_lookup_falls_back_to_the_watch_playlist(
    music: Music,
    ytmusic: mock.MagicMock,
    fallback: mock.Mock,
    caplog: pytest.LogCaptureFixture,
):
    answer_related_calls(ytmusic)
    ytmusic.get_song_related.side_effect = RuntimeError("related is gone")

    with caplog.at_level(logging.ERROR, logger="mopidy_youtube"):
        items = music.list_related_videos(SONG_ID)["items"]

    assert video_ids(items) == WATCH_VIDEO_IDS
    assert "list_related_videos error:related is gone" in caplog.text
    fallback.list_related_videos.assert_called_once_with(SONG_ID)


def test_a_failing_song_lookup_loses_the_related_songs_but_not_the_result(
    music: Music, ytmusic: mock.MagicMock, caplog: pytest.LogCaptureFixture
):
    answer_related_calls(ytmusic)

    def get_song_or_fail(video_id: str) -> dict[str, Any]:
        if video_id == RELATED_VIDEO_IDS[1]:
            msg = "private video"
            raise RuntimeError(msg)
        return get_song(video_id)

    ytmusic.get_song.side_effect = get_song_or_fail

    with caplog.at_level(logging.ERROR, logger="mopidy_youtube"):
        items = music.list_related_videos(SONG_ID)["items"]

    assert video_ids(items) == WATCH_VIDEO_IDS
    assert "private video" in caplog.text


def test_a_failing_watch_playlist_leaves_the_related_songs(
    music: Music,
    ytmusic: mock.MagicMock,
    fallback: mock.Mock,
    caplog: pytest.LogCaptureFixture,
):
    answer_related_calls(ytmusic)
    ytmusic.get_watch_playlist.side_effect = RuntimeError("no watch playlist")

    def get_song_related(browse_id: str) -> list[dict[str, Any]]:
        if browse_id == "none":  # what the client asks for without a browse id
            msg = "invalid browse id"
            raise RuntimeError(msg)
        return fixture("song_related")

    ytmusic.get_song_related.side_effect = get_song_related
    fallback.list_related_videos.return_value = {"items": [{"id": {"videoId": "jAPI"}}]}

    with caplog.at_level(logging.ERROR, logger="mopidy_youtube"):
        items = music.list_related_videos(SONG_ID)["items"]

    assert video_ids(items) == ["jAPI"]
    assert "get_watch_playlist error:no watch playlist" in caplog.text


# ---------------------------------------------------------------------------
# list_videos


def test_list_videos_returns_a_video_per_id_in_order(
    music: Music, ytmusic: mock.MagicMock
):
    ytmusic.get_song.side_effect = get_song

    result = music.list_videos([RELATED_VIDEO_IDS[0], SONG_ID])

    live = result["items"][1]
    assert [item["id"] for item in result["items"]] == [RELATED_VIDEO_IDS[0], SONG_ID]
    assert live["snippet"]["title"] == (
        "Bohemian Rhapsody (Live At Milton Keynes Bowl / June 1982)"
    )
    assert live["snippet"]["channelTitle"] == "Queen"
    assert live["contentDetails"]["duration"] == "PT0H05M59S"
    assert live["snippet"]["thumbnails"]["default"]["url"].startswith(
        "https://i.ytimg.com/vi/fJ9rUzIMcZQ/"
    )
    assert [call.args[0] for call in ytmusic.get_song.call_args_list] == [
        RELATED_VIDEO_IDS[0],
        SONG_ID,
    ]


def test_list_videos_skips_ids_without_a_response(
    music: Music, ytmusic: mock.MagicMock
):
    ytmusic.get_song.side_effect = lambda video_id: (
        None if video_id == "gone" else get_song(video_id)
    )

    result = music.list_videos(["gone", SONG_ID])

    assert [item["id"] for item in result["items"]] == [SONG_ID]


def test_list_videos_without_ids_is_empty(music: Music):
    assert music.list_videos([]) == {"items": []}


def test_an_unavailable_video_is_described_by_the_reason(
    music: Music, ytmusic: mock.MagicMock
):
    ytmusic.get_song.side_effect = get_song

    (item,) = music.list_videos([UNAVAILABLE_ID])["items"]

    assert item["snippet"]["title"] == "Video unavailable"
    assert item["contentDetails"]["duration"] == "PT0H00M00S"
    assert item["snippet"]["thumbnails"]["default"] == {
        "url": "https://s.ytimg.com/yts/img/meh7-vflGevej7.png",
        "width": 140,
        "height": 100,
    }


def test_an_unavailable_video_keeps_its_requested_id(
    music: Music, ytmusic: mock.MagicMock
):
    ytmusic.get_song.side_effect = get_song

    (item,) = music.list_videos([UNAVAILABLE_ID])["items"]

    assert item["id"] == UNAVAILABLE_ID


def test_list_videos_returns_nothing_when_a_response_cannot_be_converted(
    music: Music, ytmusic: mock.MagicMock, caplog: pytest.LogCaptureFixture
):
    ytmusic.get_song.return_value = {
        "playabilityStatus": {"status": "OK"},
        "videoDetails": {"videoId": SONG_ID},  # no title
    }

    with caplog.at_level(logging.ERROR, logger="mopidy_youtube"):
        assert music.list_videos([SONG_ID]) == {"items": []}

    assert "list_videos ytm_item_to_video error" in caplog.text


# ---------------------------------------------------------------------------
# list_playlists


def test_list_playlists_describes_a_playlist(music: Music, ytmusic: mock.MagicMock):
    ytmusic.get_playlist.side_effect = lambda _: fixture("playlist")

    (item,) = music.list_playlists([PLAYLIST_ID])["items"]

    ytmusic.get_playlist.assert_called_once_with(PLAYLIST_ID)
    assert item["id"] == {"kind": "youtube#playlist", "playlistId": PLAYLIST_ID}
    assert item["snippet"]["title"] == "Top 100 Songs South Korea"
    assert item["snippet"]["channelTitle"] == "YouTube Charts"
    assert item["snippet"]["resourceId"] == {"playlistId": PLAYLIST_ID}
    assert item["snippet"]["thumbnails"]["default"]["width"] == 1200
    assert item["contentDetails"]["itemCount"] == 100
    assert [t["id"]["videoId"] for t in item["tracks"]] == PLAYLIST_TRACK_IDS
    assert item["tracks"][0]["snippet"]["title"] == "NEON"
    assert item["tracks"][0]["snippet"]["channelTitle"] == "A2O LITE"
    assert item["tracks"][0]["album"] == {
        "name": "Top 100 Songs South Korea",
        "uri": f"yt:playlist:{PLAYLIST_ID}",
    }


def test_list_playlists_creates_the_entities_of_the_playlist_and_its_videos(
    music: Music, ytmusic: mock.MagicMock
):
    ytmusic.get_playlist.side_effect = lambda _: fixture("playlist")

    (item,) = music.list_playlists([PLAYLIST_ID])["items"]

    track_ids = [t["id"]["videoId"] for t in item["tracks"]]
    assert playlist_value(PLAYLIST_ID, "title") == "Top 100 Songs South Korea"
    assert playlist_value(PLAYLIST_ID, "video_count") == 50  # the 100 are capped
    assert playlist_value(PLAYLIST_ID, "channel") == "YouTube Charts"
    assert playlist_video_ids(PLAYLIST_ID) == track_ids
    assert video_value("D968qfUZMUE", "title") == "NEON"
    assert video_value("D968qfUZMUE", "length") == 223
    assert video_value("D968qfUZMUE", "channel") == "A2O LITE"


def test_list_playlists_looks_albums_up_by_the_browse_id_of_their_audio_playlist(
    music: Music, ytmusic: mock.MagicMock, ytm_class: mock.MagicMock
):
    ytm_class.get_album_browse_id.return_value = ALBUM_ID
    ytmusic.get_album.side_effect = get_album

    (item,) = music.list_playlists([OLAK_ID])["items"]

    assert ytm_class.get_album_browse_id.call_args.args[1] == OLAK_ID
    ytmusic.get_album.assert_called_once_with(ALBUM_ID)
    ytmusic.get_playlist.assert_not_called()
    assert item["snippet"]["title"] == ALBUM_TITLE
    assert item["snippet"]["channelTitle"] == "Queen"
    assert item["contentDetails"]["itemCount"] == 12
    assert [t["track_no"] for t in item["tracks"]] == [1, 2, 3, 4]
    assert item["tracks"][0]["album"]["name"] == ALBUM_TITLE


def test_list_playlists_returns_an_album_under_the_requested_id(
    music: Music, ytmusic: mock.MagicMock, ytm_class: mock.MagicMock
):
    ytm_class.get_album_browse_id.return_value = ALBUM_ID
    ytmusic.get_album.side_effect = get_album

    items = music.list_playlists([OLAK_ID])["items"]

    assert [item["id"]["playlistId"] for item in items] == [OLAK_ID]


def test_list_playlists_returns_what_it_found_of_a_mixed_request(
    music: Music,
    ytmusic: mock.MagicMock,
    ytm_class: mock.MagicMock,
    caplog: pytest.LogCaptureFixture,
):
    def get_playlist_or_fail(playlist_id: str) -> dict[str, Any]:
        if playlist_id == "PLgone":
            msg = "playlist does not exist"
            raise RuntimeError(msg)
        return fixture("playlist")

    ytm_class.get_album_browse_id.return_value = ALBUM_ID
    ytmusic.get_playlist.side_effect = get_playlist_or_fail
    ytmusic.get_album.side_effect = get_album

    with caplog.at_level(logging.ERROR, logger="mopidy_youtube"):
        items = music.list_playlists([PLAYLIST_ID, OLAK_ID, "PLgone"])["items"]

    titles = {item["id"]["playlistId"]: item["snippet"]["title"] for item in items}
    assert titles == {
        PLAYLIST_ID: "Top 100 Songs South Korea",
        OLAK_ID: ALBUM_TITLE,
    }
    assert "playlist does not exist, PLgone" in caplog.text


@pytest.mark.parametrize("ids", [[], ["PLgone"]])
def test_list_playlists_without_a_result_is_empty(
    music: Music, ytmusic: mock.MagicMock, ids: list[str]
):
    ytmusic.get_playlist.side_effect = RuntimeError("playlist does not exist")

    assert music.list_playlists(ids) == {"items": []}


# ---------------------------------------------------------------------------
# list_playlistitems


def test_list_playlistitems_returns_the_videos_of_a_playlist(
    music: Music, ytmusic: mock.MagicMock
):
    ytmusic.get_playlist.side_effect = lambda _: fixture("playlist")

    result = music.list_playlistitems(PLAYLIST_ID, None, 50)

    assert result["nextPageToken"] is None
    assert [item["id"] for item in result["items"]] == PLAYLIST_TRACK_IDS
    first = result["items"][0]
    assert first["snippet"]["resourceId"]["videoId"] == "D968qfUZMUE"
    assert first["snippet"]["title"] == "NEON"
    assert first["snippet"]["channelTitle"] == "A2O LITE"
    assert first["contentDetails"]["duration"] == "PT3M43S"


def test_list_playlistitems_fills_in_the_playlist_entity(
    music: Music, ytmusic: mock.MagicMock
):
    ytmusic.get_playlist.side_effect = lambda _: fixture("playlist")

    music.list_playlistitems(PLAYLIST_ID, None, 50)

    assert playlist_value(PLAYLIST_ID, "title") == "Top 100 Songs South Korea"
    assert playlist_value(PLAYLIST_ID, "video_count") == 50
    assert playlist_value(PLAYLIST_ID, "channel") == "YouTube Charts"
    assert [image.width for image in playlist_value(PLAYLIST_ID, "thumbnails")] == [
        1200
    ]


@pytest.mark.parametrize("max_results", [1, 3, 4, 10])
def test_list_playlistitems_returns_at_most_max_results(
    music: Music, ytmusic: mock.MagicMock, max_results: int
):
    ytmusic.get_playlist.side_effect = lambda _: fixture("playlist")

    items = music.list_playlistitems(PLAYLIST_ID, None, max_results)["items"]

    assert len(items) == min(max_results, 4)


def test_list_playlistitems_skips_videos_that_are_not_available(
    music: Music, ytmusic: mock.MagicMock
):
    playlist = fixture("playlist")
    playlist["tracks"][1]["videoId"] = None
    ytmusic.get_playlist.side_effect = lambda _: playlist

    items = music.list_playlistitems(PLAYLIST_ID, None, 50)["items"]

    assert len(items) == 3
    assert playlist["tracks"][1]["title"] not in [
        item["snippet"]["title"] for item in items
    ]


def test_list_playlistitems_numbers_the_tracks_of_an_album(
    music: Music, ytmusic: mock.MagicMock
):
    ytmusic.get_album.side_effect = get_album

    items = music.list_playlistitems(ALBUM_ID, None, 50)["items"]

    ytmusic.get_album.assert_called_once_with(ALBUM_ID)
    assert [item["id"] for item in items] == ALBUM_TRACK_IDS
    assert [item["track_no"] for item in items] == [1, 2, 3, 4]
    assert items[0]["album"] == {"name": ALBUM_TITLE, "uri": f"yt:playlist:{ALBUM_ID}"}
    assert items[0]["snippet"]["channelTitle"] == "Queen"
    # the tracks have no thumbnails of their own: they show the album's
    assert items[0]["snippet"]["thumbnails"]["default"]["width"] == 544
    assert playlist_value(ALBUM_ID, "title") == ALBUM_TITLE


def test_list_playlistitems_of_an_album_audio_playlist_keeps_the_requested_id(
    music: Music, ytmusic: mock.MagicMock, ytm_class: mock.MagicMock
):
    ytm_class.get_album_browse_id.return_value = ALBUM_ID
    ytmusic.get_album.side_effect = get_album

    items = music.list_playlistitems(OLAK_ID, None, 50)["items"]

    assert len(items) == 4
    assert playlist_value(OLAK_ID, "title") == ALBUM_TITLE
    assert items[0]["album"]["uri"] == f"yt:playlist:{OLAK_ID}"


# ---------------------------------------------------------------------------
# list_channelplaylists


def test_the_playlists_of_an_artist_are_its_albums(
    music: Music, ytmusic: mock.MagicMock
):
    artist = fixture("artist")
    ytmusic.get_artist.return_value = artist
    ytmusic.get_artist_albums.return_value = fixture("artist_albums")

    items = music.list_channelplaylists(ARTIST_ID)["items"]

    ytmusic.get_artist.assert_called_once_with(ARTIST_ID)
    ytmusic.get_artist_albums.assert_called_once_with(
        artist["albums"]["browseId"], artist["albums"]["params"]
    )
    assert [item["id"] for item in items] == ARTIST_ALBUM_IDS
    assert items[0]["snippet"]["title"] == "Queen Budapest"
    assert {item["snippet"]["channelTitle"] for item in items} == {"Queen"}
    assert items[0]["id"] == items[0]["snippet"]["resourceId"]["playlistId"]


def test_the_channel_defaults_to_the_own_channel(music: Music, ytmusic: mock.MagicMock):
    context.channel = ARTIST_ID
    ytmusic.get_artist.return_value = fixture("artist")
    ytmusic.get_artist_albums.return_value = fixture("artist_albums")

    music.list_channelplaylists(None)

    ytmusic.get_artist.assert_called_once_with(ARTIST_ID)


def test_the_playlists_of_a_user_are_its_public_playlists(
    music: Music, ytmusic: mock.MagicMock
):
    ytmusic.get_artist.side_effect = KeyError("not an artist")
    ytmusic.get_user.return_value = fixture("user")

    items = music.list_channelplaylists(USER_ID)["items"]

    ytmusic.get_user.assert_called_once_with(USER_ID)
    ytmusic.get_library_playlists.assert_not_called()
    assert [item["id"] for item in items] == ["PLrAXtmErZgOfvk4SvtkAMXNw6iF9qfMen"]
    assert items[0]["snippet"]["title"] == "Guitar & Piano"
    assert items[0]["snippet"]["channelTitle"] == "Lex Fridman"


def test_an_artist_without_an_albums_page_is_listed_by_its_albums_on_the_profile(
    music: Music, ytmusic: mock.MagicMock
):
    ytmusic.get_artist.side_effect = lambda _: fixture("artist_without_album_params")
    ytmusic.get_user.side_effect = KeyError("not a user")

    items = music.list_channelplaylists(ARTIST_ID)["items"]

    assert ytmusic.get_artist.call_count == 2
    assert [item["id"] for item in items] == ["MPREb_WOqUMNyA4PV", "MPREb_i3rlVrZLqb7"]
    assert (
        items[0]["snippet"]["title"]
        == "Reflections (From The Vault Of Smoke + Mirrors)"
    )
    assert {item["snippet"]["channelTitle"] for item in items} == {"Imagine Dragons"}


def test_a_channel_that_is_neither_user_nor_artist_is_an_error(
    music: Music, ytmusic: mock.MagicMock
):
    ytmusic.get_artist.side_effect = KeyError("not an artist")
    ytmusic.get_user.side_effect = KeyError("not a user")

    with pytest.raises(KeyError, match="not an artist"):
        music.list_channelplaylists(USER_ID)


def test_the_library_is_the_playlists_of_the_own_channel(
    music: Music, ytmusic: mock.MagicMock
):
    context.channel = OWN_CHANNEL
    ytmusic.get_artist.side_effect = KeyError("not an artist")
    ytmusic.get_library_playlists.return_value = library_playlists()
    ytmusic.get_library_albums.return_value = fixture("search_albums")
    ytmusic.get_album.side_effect = get_album
    ytmusic.get_user.return_value = {"name": "Me"}

    items = music.list_channelplaylists(OWN_CHANNEL)["items"]

    ytmusic.get_user.assert_called_once_with(OWN_CHANNEL)
    assert [item["id"] for item in items] == [
        "PLlibrary0000000000001",  # "LM", the liked music, is left out
        OLAK_ID,
        "OLAK5uy_nkyz8Kw10VZOtXbh5Owus0BOUOYQyS1AQ",
    ]
    favourites, album = items[0], items[1]
    assert favourites["snippet"]["title"] == "My favourites"
    assert favourites["contentDetails"]["itemCount"] == 1234
    assert favourites["snippet"]["channelTitle"] == "Me"
    assert album["snippet"]["title"] == ALBUM_TITLE
    assert album["snippet"]["channelTitle"] == "Queen"
    # the albums of the library were fetched, which creates their playlists
    assert {call.args[0] for call in ytmusic.get_album.call_args_list} == {
        ALBUM_ID,
        OTHER_ALBUM_ID,
    }
    assert playlist_value(ALBUM_ID, "title") == ALBUM_TITLE


def test_the_library_of_an_unnamed_channel_has_an_unknown_owner(
    music: Music, ytmusic: mock.MagicMock
):
    ytmusic.get_artist.side_effect = AttributeError("a channel id is required")
    ytmusic.get_library_playlists.return_value = library_playlists()
    ytmusic.get_library_albums.return_value = []

    items = music.list_channelplaylists(None)["items"]

    ytmusic.get_user.assert_not_called()
    assert [item["id"] for item in items] == ["PLlibrary0000000000001"]
    assert items[0]["snippet"]["channelTitle"] == "unknown"


def test_without_a_login_the_own_channel_has_no_playlists(
    music: Music, ytmusic: mock.MagicMock
):
    ytmusic.get_artist.side_effect = AttributeError("a channel id is required")
    ytmusic.get_library_playlists.side_effect = LoginRequiredError(
        "Please provide authentication before using this function"
    )

    assert music.list_channelplaylists(None) == {"items": []}


def test_without_a_login_the_own_channel_has_its_public_playlists(
    music: Music, ytmusic: mock.MagicMock
):
    context.channel = OWN_CHANNEL
    ytmusic.get_artist.side_effect = KeyError("not an artist")
    ytmusic.get_library_playlists.side_effect = LoginRequiredError(
        "Please provide authentication before using this function"
    )
    ytmusic.get_user.return_value = fixture("user")

    items = music.list_channelplaylists(OWN_CHANNEL)["items"]

    ytmusic.get_user.assert_called_once_with(OWN_CHANNEL)
    assert [item["snippet"]["channelTitle"] for item in items] == ["Lex Fridman"]


# ---------------------------------------------------------------------------
# yt_listitem_to_playlist


def album_item() -> dict[str, Any]:
    return {**fixture("album"), "playlistId": ALBUM_ID}


def test_an_album_becomes_a_playlist_of_numbered_videos():
    playlist = Music.yt_listitem_to_playlist(album_item())

    assert playlist["id"] == {"kind": "youtube#playlist", "playlistId": ALBUM_ID}
    assert playlist["snippet"]["title"] == ALBUM_TITLE
    assert playlist["snippet"]["channelTitle"] == "Queen"
    assert playlist["snippet"]["thumbnails"]["default"]["width"] == 544
    assert playlist["contentDetails"]["itemCount"] == 12
    assert playlist["artists"] == [{"name": "Queen", "id": ARTIST_ID}]
    tracks = playlist["tracks"]
    assert [t["track_no"] for t in tracks] == [1, 2, 3, 4]
    assert [t["id"]["videoId"] for t in tracks] == ALBUM_TRACK_IDS
    assert {t["album"]["uri"] for t in tracks} == {f"yt:playlist:{ALBUM_ID}"}
    assert {t["snippet"]["channelTitle"] for t in tracks} == {"Queen"}
    # tracks without thumbnails get those of the album
    assert {t["snippet"]["thumbnails"]["default"]["width"] for t in tracks} == {544}


def test_a_playlist_without_tracks_has_no_video_list():
    item = {
        "playlistId": "PL1",
        "title": "Listed only",
        "thumbnails": [{"url": "small"}, {"url": "large"}],
    }

    playlist = Music.yt_listitem_to_playlist(item)

    assert "tracks" not in playlist
    assert playlist["snippet"]["thumbnails"] == {"default": {"url": "large"}}


@pytest.mark.parametrize(
    ("extra", "expected"),
    [
        ({"count": "1,234"}, 1234),
        ({"count": "7"}, 7),
        ({"trackCount": 12}, 12),
        ({"count": "5", "trackCount": 12}, 5),
        ({}, "0"),
    ],
)
def test_the_item_count_comes_from_the_count_or_the_track_count(
    extra: dict[str, Any], expected: int | str
):
    item = {"playlistId": "PL1", "thumbnails": [{}], **extra}

    playlist = Music.yt_listitem_to_playlist(item)

    assert playlist["contentDetails"]["itemCount"] == expected


@pytest.mark.parametrize(
    ("artists", "given", "expected"),
    [
        ([{"name": "Queen"}, {"name": "Other"}], "Given", "Queen"),
        ("Plain Artist", "Given", "Plain Artist"),
        ([], "Given", "Given"),
        (None, "Given", "Given"),
        (None, None, None),
    ],
)
def test_the_channel_title_is_the_artist_or_the_given_title(
    artists: Any, given: str | None, expected: str | None
):
    item = {"playlistId": "PL1", "thumbnails": [{}], "artists": artists}

    playlist = Music.yt_listitem_to_playlist(item, given)

    assert playlist["snippet"]["channelTitle"] == expected


def test_an_item_without_a_playlist_id_is_logged_and_rejected(
    caplog: pytest.LogCaptureFixture,
):
    with (
        caplog.at_level(logging.ERROR, logger="mopidy_youtube"),
        pytest.raises(KeyError, match="playlistId"),
    ):
        Music.yt_listitem_to_playlist({"title": "No id", "thumbnails": [{}]})

    assert "yt_listitem_to_playlist, no playlistId" in caplog.text


def test_a_playlist_without_a_title_is_called_unknown():
    playlist = Music.yt_listitem_to_playlist({"playlistId": "PL1", "thumbnails": [{}]})

    assert playlist["snippet"]["title"] == "Unknown"


def test_tracks_keep_their_own_artists_album_and_thumbnails():
    item = album_item()
    own_album = {"name": "Another Album", "id": "MPREb_other"}
    own_artists = [{"name": "Guest", "id": "UCguest"}]
    own_thumbnails = [{"url": "own", "width": 1, "height": 1}]
    track = item["tracks"][0]
    track.update(album=own_album, artists=own_artists, thumbnails=own_thumbnails)
    item["tracks"][1]["album"] = None
    item["tracks"][2]["videoId"] = None  # unavailable

    tracks = Music.yt_listitem_to_playlist(item)["tracks"]

    assert len(tracks) == 3
    assert tracks[0]["album"] == {
        "name": "Another Album",
        "uri": "yt:playlist:MPREb_other",
    }
    assert tracks[0]["artists"] == [{"name": "Guest", "uri": "yt:channel:UCguest"}]
    assert tracks[0]["snippet"]["thumbnails"]["default"] == own_thumbnails[0]
    assert tracks[1]["album"]["uri"] == f"yt:playlist:{ALBUM_ID}"


def test_only_albums_number_their_tracks():
    item = album_item()
    item["type"] = "Playlist"

    tracks = Music.yt_listitem_to_playlist(item)["tracks"]

    assert [t["track_no"] for t in tracks] == [None] * 4


# ---------------------------------------------------------------------------
# _get_playlist_or_album


def test_a_playlist_is_fetched_with_its_author_as_artist(
    music: Music, ytmusic: mock.MagicMock
):
    ytmusic.get_playlist.side_effect = lambda _: fixture("playlist")

    result = music._get_playlist_or_album(PLAYLIST_ID)

    ytmusic.get_playlist.assert_called_once_with(PLAYLIST_ID)
    assert result["playlistId"] == PLAYLIST_ID
    assert result["artists"] == [{"name": "YouTube Charts", "id": "FEmusic_charts"}]


def test_an_album_is_fetched_with_its_browse_id_as_playlist_id(
    music: Music, ytmusic: mock.MagicMock
):
    ytmusic.get_album.side_effect = get_album

    result = music._get_playlist_or_album(ALBUM_ID)

    ytmusic.get_album.assert_called_once_with(ALBUM_ID)
    ytmusic.get_playlist.assert_not_called()
    assert result["playlistId"] == ALBUM_ID
    assert result["artists"] == [{"name": "Queen", "id": ARTIST_ID}]


def test_an_album_of_an_older_ytmusicapi_has_its_artist_copied_to_artists(
    music: Music, ytmusic: mock.MagicMock
):
    album = fixture("album")
    album["artist"] = album.pop("artists")
    ytmusic.get_album.return_value = album

    result = music._get_playlist_or_album(ALBUM_ID)

    assert result["artists"] == [{"name": "Queen", "id": ARTIST_ID}]


def test_an_album_that_has_a_playlist_id_keeps_it(
    music: Music, ytmusic: mock.MagicMock
):
    ytmusic.get_album.return_value = {**fixture("album"), "playlistId": "PLown"}

    assert music._get_playlist_or_album(ALBUM_ID)["playlistId"] == "PLown"


def test_an_audio_playlist_is_resolved_to_its_album(
    music: Music, ytmusic: mock.MagicMock, ytm_class: mock.MagicMock
):
    ytm_class.get_album_browse_id.return_value = ALBUM_ID
    ytmusic.get_album.side_effect = get_album

    result = music._get_playlist_or_album(OLAK_ID)

    ytm_class.get_album_browse_id.assert_called_once_with(
        ytm_class.return_value, OLAK_ID
    )
    ytmusic.get_album.assert_called_once_with(ALBUM_ID)
    assert result["playlistId"] == ALBUM_ID


# ---------------------------------------------------------------------------
# _create_playlist_objects


def test_the_playlist_and_video_entities_are_filled_from_the_converted_playlist():
    playlist = Music.yt_listitem_to_playlist(album_item())

    Music._create_playlist_objects([playlist])

    assert playlist_value(ALBUM_ID, "title") == ALBUM_TITLE
    assert playlist_value(ALBUM_ID, "video_count") == 12
    assert playlist_value(ALBUM_ID, "channel") == "Queen"
    (image,) = playlist_value(ALBUM_ID, "thumbnails")
    assert (image.width, image.height) == (544, 544)
    assert playlist_video_ids(ALBUM_ID) == ALBUM_TRACK_IDS
    assert len(playlist_value(ALBUM_ID, "videos")) == 4

    track = fixture("album")["tracks"][1]
    assert video_value(track["videoId"], "title") == "Lazing On A Sunday Afternoon"
    assert video_value(track["videoId"], "channel") == "Queen"
    assert video_value(track["videoId"], "length") == 68
    assert video_value(track["videoId"], "track_no") == 2
    assert video_value(track["videoId"], "album") == {
        "name": ALBUM_TITLE,
        "uri": f"yt:playlist:{ALBUM_ID}",
    }
    assert video_value(track["videoId"], "artists") == [
        {"name": "Queen", "uri": f"yt:channel:{ARTIST_ID}"}
    ]
    # the track has none of its own: it shows the thumbnail of the album
    assert [i.width for i in video_value(track["videoId"], "thumbnails")] == [544]


def test_a_playlist_shows_no_more_videos_than_the_configured_maximum():
    context.playlist_max_videos = 3
    playlist = Music.yt_listitem_to_playlist(album_item())

    Music._create_playlist_objects([playlist])

    assert len(playlist_value(ALBUM_ID, "videos")) == 3
    assert playlist_value(ALBUM_ID, "video_count") == 3


def test_a_playlist_without_tracks_has_an_empty_video_list():
    item = {**fixture("playlist"), "playlistId": PLAYLIST_ID, "tracks": []}
    item["artists"] = [item["author"]]

    Music._create_playlist_objects([Music.yt_listitem_to_playlist(item)])

    assert playlist_value(PLAYLIST_ID, "videos") == []


def test_a_track_without_an_album_belongs_to_the_playlist():
    playlist = Music.yt_listitem_to_playlist(album_item())
    for track in playlist["tracks"]:
        del track["album"]

    Music._create_playlist_objects([playlist])

    assert video_value(ALBUM_TRACK_IDS[0], "album") == {
        "name": ALBUM_TITLE,
        "id": ALBUM_ID,
    }


# ---------------------------------------------------------------------------
# close


def test_closing_ends_both_thread_pools(ytm_class: mock.MagicMock, fallback: mock.Mock):
    music = Music(None, ANONYMOUS, fallback)

    music.close()

    for executor in (music.executor, music._lookup_executor):
        with pytest.raises(RuntimeError, match="after shutdown"):
            executor.submit(int)
