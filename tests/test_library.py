"""Tests for the library provider: what Mopidy gets from browse/lookup/search.

The whole chain is exercised, from the api client over the recorded responses in
`tests/fixtures/` (YouTube Music through a mocked `YTMusic`, jAPI through
`FakeYouTube`), through the entities, to the Mopidy models the library returns.
Only the public methods of `YouTubeLibraryProvider` are driven; the entities are
never touched. Calls on the provider run in a thread with a timeout, so that an
entity future that is never set fails a test instead of hanging the run.
"""

from __future__ import annotations

import json
import threading
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from unittest import mock

import pytest
import requests
from mopidy.models import Album, Artist, Image, Ref, SearchResult, Track
from mopidy.types import Uri

from mopidy_youtube.apis import UnconfiguredApi
from mopidy_youtube.apis.youtube_japi import jAPI
from mopidy_youtube.apis.youtube_music import Music
from mopidy_youtube.cache import cache_metadata
from mopidy_youtube.context import context
from mopidy_youtube.library import YouTubeLibraryProvider
from mopidy_youtube.youtube import Entry, Playlist, Video

from tests.support import FakeYouTube, load_fixture, yt_initial_data_page

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

TIMEOUT = 10  # seconds

BASE = "https://www.youtube.com/"
SEARCH_URL = BASE + "youtubei/v1/search"
ANONYMOUS = {"Cookie": "PREF=hl=en; CONSENT=YES+20210329;"}

# ids in the YouTube Music fixtures
SONG_ID = "fJ9rUzIMcZQ"
ALBUM_ID = "MPREb_eEpQf8QskKl"
OTHER_ALBUM_ID = "MPREb_ppvh6pdaiCc"
OLAK_ID = "OLAK5uy_mQGa-V4qspfisNHu1kXthY1w93yJNT0rw"
PLAYLIST_ID = "PL4fGSI1pDJn6jXS_Tv_N9B8Z0HTRVJE0m"
USER_ID = "UCSHZKyawb77ixDdsGog4iWA"
ARTIST_ID = "UCEPMVbUzImPl4p8k4LkGevA"
ALBUM_TITLE = "A Night At The Opera"
PLAYLIST_TITLE = "Top 100 Songs South Korea"
QUEEN_URI = "yt:channel:UCEPMVbUzImPl4p8k4LkGevA"

# ids in the jAPI fixtures
VIDEO_ID = "dQw4w9WgXcQ"
ZOO_ID = "jNQXAC9IVRw"
MISSING_ID = "zzzzzzzzzzz"
JAPI_PLAYLIST_ID = "PLFgquLnL59alCl_2TQvOiD5Vgm1hCaGSI"
CHANNEL_ID = "UCuAXFkgsw1L7xaCfnd5JJOw"
CHANNEL_PLAYLIST_IDS = [
    "PLlaN88a7y2_qHDbY9eQbuNTAuEJUSEeuu",
    "PLlaN88a7y2_oK0nKMjZSwdU_njxUYWykm",
    "PLlaN88a7y2_pVVkl4fGdTny21_LRyT85E",
]
PLAYLIST_PAGE_VIDEO_IDS = ["fOT0BUpITw8", "NFvDHYMzj9U", "8c7KOGxeY3w"]


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


class Library:
    """A library provider as the backend builds it, with calls that time out."""

    def __init__(self) -> None:
        self.config: dict[str, Any] = {"http": {"enabled": False}}
        backend = SimpleNamespace(config=self.config)
        self.provider = YouTubeLibraryProvider(backend=backend)  # type: ignore[arg-type]

    def browse(self, uri: str) -> list[Ref]:
        return timed(self.provider.browse, Uri(uri))

    def lookup(self, uri: str) -> list[Track]:
        return timed(self.provider.lookup, Uri(uri))

    def search(self, query: Any = None, **kwargs: Any) -> SearchResult | None:
        return timed(self.provider.search, query, **kwargs)

    def get_images(self, uris: Any) -> dict[Uri, list[Image]]:
        return timed(self.provider.get_images, uris)


def finish_background_loads() -> None:
    """Wait for the playlists that were loading in the background."""
    executor = getattr(Playlist, "get_playlist_videos_executor", None)
    if executor is not None:
        # one worker: when this empty job is done, the earlier ones are too
        timed(executor().submit(lambda: None).result)


@pytest.fixture(autouse=True)
def fresh_browse_cache() -> Iterator[None]:
    # it is shared by all providers, and keyed by their identity
    YouTubeLibraryProvider.youtube_library_cache.clear()
    yield
    YouTubeLibraryProvider.youtube_library_cache.clear()


@pytest.fixture
def library() -> Library:
    return Library()


# -- YouTube Music ------------------------------------------------------------


def music_fixture(name: str) -> Any:
    return load_fixture(f"music/{name}.json")


@pytest.fixture
def ytm_class() -> Iterator[mock.MagicMock]:
    with mock.patch("mopidy_youtube.apis.youtube_music.YTMusic") as ytm_class:
        ytm_class.get_album_browse_id.return_value = ALBUM_ID
        yield ytm_class


@pytest.fixture
def music(ytm_class: mock.MagicMock) -> Iterator[Music]:
    """The Music client as the api of the extension, over the recorded responses."""
    client = Music(None, ANONYMOUS, mock.Mock())
    ytmusic: Any = client.ytmusic
    ytmusic.get_album.side_effect = lambda _: music_fixture("album")
    ytmusic.get_playlist.side_effect = lambda _: music_fixture("playlist")
    ytmusic.get_song.side_effect = lambda video_id: music_fixture("songs")[video_id]
    ytmusic.search.side_effect = lambda **kwargs: music_fixture(
        "search_albums" if kwargs["filter"] == "albums" else "search_songs"
    )
    context.api = client
    yield client
    finish_background_loads()
    client.close()


@pytest.fixture
def ytmusic(music: Music) -> Any:
    return music.ytmusic


def set_up_artist_channel(ytmusic: Any) -> None:
    """The own channel is an artist: the playlists are its albums."""
    context.channel = ARTIST_ID
    ytmusic.get_artist.return_value = music_fixture("artist")
    ytmusic.get_artist_albums.return_value = music_fixture("artist_albums")


def set_up_user_channel(ytmusic: Any) -> None:
    """The own channel is a user without login: the playlists are the public ones."""
    context.channel = USER_ID
    ytmusic.get_artist.side_effect = KeyError("not an artist")
    ytmusic.get_library_playlists.side_effect = RuntimeError("login required")
    ytmusic.get_user.return_value = music_fixture("user")


# -- jAPI ---------------------------------------------------------------------


def page(name: str) -> str:
    return yt_initial_data_page(load_fixture(f"japi/{name}"))


class YouTubeSite(FakeYouTube):
    """youtube.com: the search is answered by kind, the rest by `add`."""

    def send(  # noqa: PLR0917 - signature of requests' BaseAdapter
        self,
        request: requests.PreparedRequest,
        stream: bool = False,
        timeout: Any = None,
        verify: Any = True,
        cert: Any = None,
        proxies: Any = None,
    ) -> requests.Response:
        url = request.url or ""
        if not url.startswith(SEARCH_URL):
            return super().send(request, stream, timeout, verify, cert, proxies)
        self.requests.append(request)
        is_video_search = "EgIQAQ" in url
        fixture = (
            "search_videos.json" if is_video_search else "search_playlists_lockups.json"
        )
        response = requests.Response()
        response.status_code = 200
        response._content = json.dumps(load_fixture(f"japi/{fixture}")).encode()
        response.url = url
        response.request = request
        return response


@pytest.fixture
def site() -> YouTubeSite:
    """youtube.com with a playlist page and video pages; channels are added by tests."""
    site = YouTubeSite()
    site.add("GET", BASE + "results", body=page("search_videos.json"))
    site.add("GET", BASE + f"watch?v={ZOO_ID}", body=page("watch_zoo.json"))
    site.add("GET", BASE + "watch", body="not found", status=404)
    site.add("GET", BASE + "playlist", body=page("playlist_page.json"))
    return site


@pytest.fixture
def japi(site: YouTubeSite) -> Iterator[jAPI]:
    client = jAPI(None, {})
    site.attach(client)
    context.api = client
    yield client
    finish_background_loads()
    client.close()


# -- describing what comes back -----------------------------------------------


def describe(track: Track) -> tuple[Any, ...]:
    """What a client shows of a track (artists in a fixed order)."""
    album = track.album
    return (
        track.uri,
        track.name,
        track.length,
        track.track_no,
        (album.name, album.uri) if album else None,
        sorted((artist.name, artist.uri) for artist in track.artists),
    )


def opera_track(
    video_id: str, name: str, seconds: int, number: int, album_id: str = ALBUM_ID
) -> tuple[Any, ...]:
    return (
        f"youtube:video:{video_id}",
        name,
        seconds * 1000,
        number,
        (ALBUM_TITLE, f"yt:playlist:{album_id}"),
        [("Queen", QUEEN_URI)],
    )


def opera_tracks(album_id: str = ALBUM_ID) -> list[tuple[Any, ...]]:
    return [
        opera_track(
            "kqVpk0qxmfA", "Death On Two Legs (Dedicated To...)", 224, 1, album_id
        ),
        opera_track("OU6EyXcFBxA", "Lazing On A Sunday Afternoon", 68, 2, album_id),
        opera_track("oaEM4JYFPfw", "I'm In Love With My Car", 185, 3, album_id),
        opera_track("HaZpZQG2z10", "You're My Best Friend", 171, 4, album_id),
    ]


def korean_playlist_tracks() -> list[tuple[Any, ...]]:
    album = (PLAYLIST_TITLE, f"yt:playlist:{PLAYLIST_ID}")
    return [
        (
            "youtube:video:D968qfUZMUE",
            "NEON",
            223000,
            None,
            album,
            [
                ("A2O", "yt:channel:UCcy9NwrIzmzITEqiVstaN1A"),
                ("A2O LITE", "yt:channel:UCCa_4FfbVdc6zhWmRndKwfQ"),
            ],
        ),
        (
            "youtube:video:GxChUrrY4bc",
            "꿈꾸던 어른이 되었나요?",
            205000,
            None,
            album,
            [("MEOMURU", "yt:channel:UCumxj48bP-H_YusbCXi7vkQ")],
        ),
        (
            "youtube:video:7mDDM0eBWR0",
            "소연 (SOYEON) '퇴사할게여 (Narr. 기안84)' Official Music Video",
            212000,
            None,
            album,
            [("i-dle (아이들)", "yt:channel:UCritGVo7pLJLUS8wEu32vow")],
        ),
        (
            "youtube:video:F_EGihOgXsg",
            "Mise en scène",
            179000,
            None,
            album,
            [
                ("DAVICHI", "yt:channel:UCACsUruxumQoyZq08UB9RVw"),
                ("EPIK HIGH", "yt:channel:UCoNq-kohNtB6l7ChNheqW0g"),
            ],
        ),
    ]


def page_track(video_id: str, name: str, seconds: int, channel: str, channel_id: str):
    return (
        f"youtube:video:{video_id}",
        name,
        seconds * 1000,
        None,
        ("Popular Music Videos", f"yt:playlist:{JAPI_PLAYLIST_ID}"),
        [(f"{channel} (Channel)", f"yt:channel:{channel_id}")],
    )


def japi_playlist_tracks() -> list[tuple[Any, ...]]:
    return [
        page_track(
            "fOT0BUpITw8",
            "BELLAKEO (Video Oficial) - Peso Pluma, Anitta",
            235,
            "Peso Pluma",
            "UCzrM_068Odho89mTRrrxqbA",
        ),
        page_track(
            "NFvDHYMzj9U",
            "Arcángel - FN8 ( Video Lyric )",
            650,
            "Arcangel",
            "UCu4bj03KW4CwAsYtHSwMEsQ",
        ),
        page_track(
            "8c7KOGxeY3w",
            "Becky G - POR EL CONTRARIO (Performance Video) ft. Ángela Aguilar, "
            "Leonardo Aguilar",
            235,
            "Becky G",
            "UCgtNC51EUSgcZ6kKyVoPxKA",
        ),
    ]


RICK_NAME = "Rick Astley - Never Gonna Give You Up (Official Video) (4K Remaster)"
RICK_TRACK = (
    f"youtube:video:{VIDEO_ID}",
    RICK_NAME,
    214000,
    None,
    ("YouTube Playlist", None),
    [("Rick Astley (Channel)", f"yt:channel:{CHANNEL_ID}")],
)


# ===========================================================================
# lookup


def test_a_video_of_youtube_music_is_one_track(library: Library, ytmusic: Any):
    tracks = library.lookup(f"youtube:video:{SONG_ID}")

    assert [describe(track) for track in tracks] == [
        (
            f"youtube:video:{SONG_ID}",
            "Bohemian Rhapsody (Live At Milton Keynes Bowl / June 1982)",
            359000,
            None,
            ("YouTube Playlist", None),
            [("Queen", "yt:channel:UCiMhD4jzUqG-IgPzUmmytRQ")],
        )
    ]
    assert tracks[0].comment == SONG_ID


def test_a_video_is_not_loaded_again_by_the_next_lookup(library: Library, ytmusic: Any):
    first = library.lookup(f"youtube:video:{SONG_ID}")
    second = library.lookup(f"yt:video:{SONG_ID}")

    assert second == first
    assert ytmusic.get_song.call_count == 1


@pytest.mark.parametrize(
    "uri",
    [
        f"youtube:video:{VIDEO_ID}",
        f"yt:video:{VIDEO_ID}",
        f"https://www.youtube.com/watch?v={VIDEO_ID}",
        f"youtube:https://www.youtube.com/watch?v={VIDEO_ID}",
        f"yt:https://www.youtube.com/watch?v={VIDEO_ID}",
        f"https://youtu.be/{VIDEO_ID}",
        f"youtu.be/{VIDEO_ID}",
    ],
)
def test_a_video_is_found_by_every_form_of_its_uri(
    library: Library, japi: jAPI, uri: str
):
    tracks = library.lookup(uri)

    assert [describe(track) for track in tracks] == [RICK_TRACK]


def test_a_video_without_a_duration_has_length_zero(library: Library, japi: jAPI):
    tracks = library.lookup(f"youtube:video:{ZOO_ID}")

    assert [describe(track) for track in tracks] == [
        (
            f"youtube:video:{ZOO_ID}",
            "Me at the zoo",
            0,
            None,
            ("YouTube Playlist", None),
            [("jawed", None)],
        )
    ]


def test_a_video_that_cannot_be_found_is_a_track_without_length(
    library: Library, japi: jAPI
):
    (track,) = library.lookup(f"youtube:video:{MISSING_ID}")

    assert track.uri == f"youtube:video:{MISSING_ID}"
    assert track.length == 0


def test_the_playlist_of_a_watch_url_is_looked_up_rather_than_the_video(
    library: Library, japi: jAPI
):
    uri = f"https://www.youtube.com/watch?v={VIDEO_ID}&list={JAPI_PLAYLIST_ID}"

    tracks = library.lookup(uri)

    assert [describe(track) for track in tracks] == japi_playlist_tracks()


@pytest.mark.parametrize(
    "uri",
    [
        f"youtube:playlist:{JAPI_PLAYLIST_ID}",
        f"yt:playlist:{JAPI_PLAYLIST_ID}",
        f"https://www.youtube.com/playlist?list={JAPI_PLAYLIST_ID}",
    ],
)
def test_a_playlist_is_its_videos_in_order_on_the_album_of_the_playlist(
    library: Library, japi: jAPI, uri: str
):
    tracks = library.lookup(uri)

    assert [describe(track) for track in tracks] == japi_playlist_tracks()


def test_a_playlist_is_not_loaded_again_by_the_next_lookup(
    library: Library, japi: jAPI, site: YouTubeSite
):
    first = library.lookup(f"youtube:playlist:{JAPI_PLAYLIST_ID}")
    requests_made = len(site.requests)

    second = library.lookup(f"youtube:playlist:{JAPI_PLAYLIST_ID}")

    assert second == first
    assert len(site.requests) == requests_made


def test_a_playlist_of_youtube_music_has_its_tracks_and_artists(
    library: Library, ytmusic: Any
):
    tracks = library.lookup(f"youtube:playlist:{PLAYLIST_ID}")

    assert [describe(track) for track in tracks] == korean_playlist_tracks()
    assert [track.comment for track in tracks] == [
        "D968qfUZMUE",
        "GxChUrrY4bc",
        "7mDDM0eBWR0",
        "F_EGihOgXsg",
    ]
    assert {call.args[0] for call in ytmusic.get_playlist.call_args_list} == {
        PLAYLIST_ID
    }


def test_an_album_of_youtube_music_has_its_numbered_tracks_in_order(
    library: Library, ytmusic: Any
):
    tracks = library.lookup(f"youtube:playlist:{ALBUM_ID}")

    assert [describe(track) for track in tracks] == opera_tracks()
    assert {call.args[0] for call in ytmusic.get_album.call_args_list} == {ALBUM_ID}


def test_an_album_is_found_by_the_id_of_its_audio_playlist(
    library: Library, ytmusic: Any
):
    tracks = library.lookup(f"yt:playlist:{OLAK_ID}")

    assert [describe(track) for track in tracks] == opera_tracks(OLAK_ID)


def test_an_album_gives_its_tracks_after_a_search_found_it(
    library: Library, ytmusic: Any
):
    result = library.search({"any": ["night at the opera"]})
    assert result is not None
    album_uris = sorted(album.uri for album in result.albums)
    assert album_uris == [
        f"youtube:playlist:{ALBUM_ID}",
        f"youtube:playlist:{OTHER_ALBUM_ID}",
    ]

    first = library.lookup(album_uris[0])
    second = library.lookup(album_uris[1])

    assert [describe(track) for track in first] == opera_tracks(ALBUM_ID)
    assert [describe(track) for track in second] == opera_tracks(OTHER_ALBUM_ID)


def test_a_playlist_gives_its_tracks_after_a_channel_listed_it(
    library: Library, ytmusic: Any
):
    set_up_user_channel(ytmusic)
    (playlist,) = library.browse("youtube:channel:root")

    tracks = library.lookup(playlist.uri)

    assert playlist.name == "Guitar & Piano"
    assert [track.uri for track in tracks] == [
        f"youtube:video:{video_id}"
        for video_id in ["D968qfUZMUE", "GxChUrrY4bc", "7mDDM0eBWR0", "F_EGihOgXsg"]
    ]


@pytest.mark.parametrize("max_videos", [1, 2, 3])
def test_a_playlist_gives_no_more_tracks_than_the_configured_maximum(
    library: Library, ytmusic: Any, max_videos: int
):
    context.playlist_max_videos = max_videos

    tracks = library.lookup(f"youtube:playlist:{PLAYLIST_ID}")

    assert [track.name for track in tracks] == [
        item[1] for item in korean_playlist_tracks()[:max_videos]
    ]


def test_a_playlist_that_cannot_be_loaded_is_an_unknown_track(
    library: Library, ytmusic: Any
):
    ytmusic.get_playlist.side_effect = RuntimeError("playlist does not exist")

    tracks = library.lookup("youtube:playlist:PLgone")

    assert tracks == [Track(uri=Uri("youtube:video:unknown"), name="Unknown")]


def test_the_videos_of_a_channel_are_the_videos_of_its_playlists(
    library: Library, japi: jAPI, site: YouTubeSite
):
    site.add(
        "GET",
        BASE + f"channel/{CHANNEL_ID}/playlists",
        body=page("channel_playlists_lockups.json"),
    )

    tracks = library.lookup(f"youtube:channel:{CHANNEL_ID}")

    # the playlist page of the site is the same for every playlist
    assert [track.uri for track in tracks] == [
        f"youtube:video:{video_id}" for video_id in PLAYLIST_PAGE_VIDEO_IDS * 3
    ]


def test_a_channel_without_playlists_is_an_unknown_track(
    library: Library, japi: jAPI, site: YouTubeSite
):
    site.add(
        "GET",
        BASE + f"channel/{CHANNEL_ID}/playlists",
        body=page("channel_unavailable.json"),
    )

    tracks = library.lookup(f"yt:channel:{CHANNEL_ID}")

    assert tracks == [Track(uri=Uri("youtube:video:unknown"), name="Unknown")]


@pytest.mark.parametrize(
    "uri",
    [
        "youtube:nothing",
        "youtube:video:short",
        "yt:video:",
        "https://example.com/video",
        "mp3:video:dQw4w9WgXcQ",
        "",
    ],
)
def test_a_uri_that_is_none_of_the_kinds_is_an_unknown_track(
    library: Library, uri: str
):
    tracks = library.lookup(uri)

    assert tracks == [Track(uri=Uri("youtube:video:unknown"), name="Unknown")]


def test_a_preloaded_video_is_a_track_without_asking_the_api(library: Library):
    songs = music_fixture("search_songs")
    preload = json.dumps([*songs[:2], {"title": "no video id"}]).encode().hex()
    context.api = UnconfiguredApi()

    tracks = library.lookup(f"youtube:video:{songs[0]['videoId']}:preload:{preload}")

    assert [describe(track) for track in tracks] == [
        (
            "youtube:video:BSTsnWoslP4",
            "Bohemian Rhapsody",
            355000,
            None,
            (ALBUM_TITLE, f"yt:playlist:{ALBUM_ID}"),
            [("Queen", QUEEN_URI)],
        )
    ]


def test_the_other_preloaded_videos_are_tracks_without_asking_the_api(
    library: Library,
):
    songs = music_fixture("search_songs")
    preload = json.dumps(songs[:2]).encode().hex()
    context.api = UnconfiguredApi()
    library.lookup(f"youtube:video:{songs[0]['videoId']}:preload:{preload}")

    tracks = library.lookup(f"youtube:video:{songs[1]['videoId']}")

    assert [describe(track) for track in tracks] == [
        (
            "youtube:video:_Xsu44ppnFQ",
            "Bohemian Rhapsody x Walk It Talk It",
            114000,
            None,
            ("Bohemian Rhapsody x Walk It Talk It", "yt:playlist:MPREb_fEnzBsOYhvt"),
            [
                ("klyron", "yt:channel:UCxk14i4tCeR23oEyEGrI3bw"),
                ("nimphia", "yt:channel:UCmbwsoH423PykuFJk9z5jqw"),
            ],
        )
    ]


# -- the cache directory ------------------------------------------------------


def cached_track_json(video_id: str) -> dict[str, Any]:
    """What a cached track looks like when it is read back as a Track."""
    return {
        "uri": f"youtube:video:{video_id}",
        "name": "What was cached",
        "artists": [{"name": "Cached artist", "uri": "yt:channel:UCcached"}],
        "album": {"name": "Cached album", "uri": "yt:playlist:PLcached"},
        "length": 123000,
        "track_no": 5,
        "comment": video_id,
        "bitrate": 128,
    }


def test_the_metadata_of_a_cached_video_is_read_from_the_cache_dir(
    library: Library, tmp_path: Path
):
    context.cache_location = tmp_path
    context.api = UnconfiguredApi()
    (tmp_path / f"{VIDEO_ID}.json").write_text(
        json.dumps(cached_track_json(VIDEO_ID)), encoding="utf-8"
    )

    tracks = library.lookup(f"youtube:video:{VIDEO_ID}")

    assert tracks == [Track.model_validate(cached_track_json(VIDEO_ID))]
    assert tracks[0].bitrate == 128
    assert tracks[0].name == "What was cached"


def test_a_video_that_is_not_in_the_cache_dir_is_loaded(
    library: Library, japi: jAPI, site: YouTubeSite, tmp_path: Path
):
    context.cache_location = tmp_path
    (tmp_path / "otherVideo11.json").write_text(
        json.dumps(cached_track_json("otherVideo11")), encoding="utf-8"
    )

    tracks = library.lookup(f"youtube:video:{VIDEO_ID}")

    assert [describe(track) for track in tracks] == [RICK_TRACK]
    assert site.calls("GET", BASE + "results")


@pytest.mark.parametrize(
    "malformed", ["", "{not json", '{"name": "a string", "uri": 5}']
)
def test_malformed_metadata_in_the_cache_dir_is_ignored(
    library: Library, japi: jAPI, tmp_path: Path, malformed: str
):
    context.cache_location = tmp_path
    (tmp_path / f"{VIDEO_ID}.json").write_text(malformed, encoding="utf-8")

    tracks = library.lookup(f"youtube:video:{VIDEO_ID}")

    assert [describe(track) for track in tracks] == [RICK_TRACK]


def test_the_cache_dir_is_not_used_without_a_cache_location(
    library: Library, japi: jAPI, tmp_path: Path
):
    (tmp_path / f"{VIDEO_ID}.json").write_text(
        json.dumps(cached_track_json(VIDEO_ID)), encoding="utf-8"
    )

    tracks = library.lookup(f"youtube:video:{VIDEO_ID}")

    assert [describe(track) for track in tracks] == [RICK_TRACK]


def test_the_metadata_that_was_cached_is_what_a_later_lookup_returns(
    library: Library, japi: jAPI, tmp_path: Path
):
    context.cache_location = tmp_path
    (loaded,) = library.lookup(f"youtube:video:{VIDEO_ID}")
    timed(cache_metadata, Video.get(VIDEO_ID), tmp_path, {"tbr": 128})
    Entry.cache.clear()
    context.api = UnconfiguredApi()

    (again,) = library.lookup(f"youtube:video:{VIDEO_ID}")

    assert again == loaded.model_copy(update={"bitrate": 128})


# ===========================================================================
# search


def test_a_search_finds_the_songs_and_albums_of_youtube_music(
    library: Library, ytmusic: Any
):
    result = library.search({"any": ["bohemian rhapsody"]})

    assert result is not None
    assert result.uri == "youtube:search"
    assert result.artists == ()
    assert [describe(track) for track in result.tracks] == [
        (
            "youtube:video:BSTsnWoslP4",
            "Bohemian Rhapsody",
            355000,
            None,
            (ALBUM_TITLE, f"yt:playlist:{ALBUM_ID}"),
            [("Queen", QUEEN_URI)],
        ),
        (
            "youtube:video:_Xsu44ppnFQ",
            "Bohemian Rhapsody x Walk It Talk It",
            114000,
            None,
            ("Bohemian Rhapsody x Walk It Talk It", "yt:playlist:MPREb_fEnzBsOYhvt"),
            [
                ("klyron", "yt:channel:UCxk14i4tCeR23oEyEGrI3bw"),
                ("nimphia", "yt:channel:UCmbwsoH423PykuFJk9z5jqw"),
            ],
        ),
        (
            "youtube:video:soHI4sKPQ3E",
            "Bohemian Rhapsody",
            342000,
            None,
            ("From Limpopo To The World", "yt:playlist:MPREb_s3vrIxzWWPx"),
            [("Ndlovu Youth Choir", "yt:channel:UC4O-I7SBNRC6q2jYkc5sIKw")],
        ),
    ]


def test_an_album_found_by_a_search_has_its_name_artist_and_number_of_tracks(
    library: Library, ytmusic: Any
):
    result = library.search({"any": ["bohemian rhapsody"]})

    assert result is not None
    albums = sorted(result.albums, key=lambda album: album.uri or "")
    assert albums == [
        Album(
            uri=Uri(f"youtube:playlist:{ALBUM_ID}"),
            name=ALBUM_TITLE,
            artists=frozenset({Artist(name="Queen")}),
            num_tracks=12,
        ),
        Album(
            uri=Uri(f"youtube:playlist:{OTHER_ALBUM_ID}"),
            name=ALBUM_TITLE,
            artists=frozenset({Artist(name="Queen")}),
            num_tracks=12,
        ),
    ]


def test_the_values_of_the_any_field_are_searched_for_together(
    library: Library, ytmusic: Any
):
    library.search({"any": ["queen", "night", "opera"]})

    queries = {call.kwargs["query"] for call in ytmusic.search.call_args_list}
    assert queries == {"queen night opera"}


def test_only_the_any_field_of_a_query_is_searched_for(library: Library, ytmusic: Any):
    result = library.search(
        {"any": ["bohemian"], "artist": ["somebody else"], "track_name": ["x"]}
    )

    assert result is not None
    assert len(result.tracks) == 3
    queries = {call.kwargs["query"] for call in ytmusic.search.call_args_list}
    assert queries == {"bohemian"}


def test_the_uris_and_exactness_of_a_search_do_not_narrow_it(
    library: Library, ytmusic: Any
):
    plain = library.search({"any": ["bohemian"]})

    narrowed = library.search(
        {"any": ["bohemian"]}, uris=[Uri("youtube:playlist:other")], exact=True
    )

    assert plain is not None
    assert narrowed is not None
    assert narrowed.tracks == plain.tracks


@pytest.mark.parametrize(
    "query",
    [
        None,
        {},
        {"artist": ["queen"]},
        {"track_name": ["bohemian rhapsody"]},
        {"album": ["a night at the opera"]},
        {"albumartist": ["queen"], "date": ["1975"]},
    ],
)
def test_a_search_needs_an_any_or_uri_field_or_finds_nothing(
    library: Library, ytmusic: Any, query: Any
):
    assert library.search(query) is None

    ytmusic.search.assert_not_called()


@pytest.mark.parametrize("values", [[], [""], ["  "]])
def test_a_search_for_nothing_is_an_empty_result_and_asks_nobody(
    library: Library, ytmusic: Any, values: list[str]
):
    result = library.search({"any": values})

    assert result == SearchResult(
        uri=Uri("youtube:search"), tracks=(), artists=(), albums=()
    )
    ytmusic.search.assert_not_called()


def test_a_failing_search_is_an_empty_result(library: Library, ytmusic: Any):
    ytmusic.search.side_effect = RuntimeError("no connection")

    result = library.search({"any": ["bohemian"]})

    assert result == SearchResult(
        uri=Uri("youtube:search"), tracks=(), artists=(), albums=()
    )


def test_a_search_gives_no_more_results_than_the_configured_limit(
    library: Library, ytmusic: Any
):
    context.search_results = 1

    result = library.search({"any": ["bohemian"]})

    assert result is not None
    assert [track.uri for track in result.tracks] == ["youtube:video:BSTsnWoslP4"]
    assert len(result.albums) == 1


def test_a_search_finds_the_videos_and_playlists_of_youtube(
    library: Library, japi: jAPI, site: YouTubeSite
):
    context.search_results = 3

    result = library.search({"any": ["never gonna give you up"]})

    assert result is not None
    assert result.uri == "youtube:search"
    assert [describe(track) for track in result.tracks] == [
        RICK_TRACK,
        (
            "youtube:video:7FwDP17XPlk",
            "Rick Astley - Never Gonna Give You Up",
            214000,
            None,
            ("YouTube Playlist", None),
            [("Amazing Lyrics (Channel)", "yt:channel:UCZtoHl1p6R6_iLm2yjA9gew")],
        ),
        (
            "youtube:video:5SZYz7lZRRI",
            "Rick Astley - Never Gonna Give You Up (Official Music Video) (1987)",
            213000,
            None,
            ("YouTube Playlist", None),
            [("Super Top Songs (Channel)", "yt:channel:UCuRJJMKpFIdyAsBVaWfK7BQ")],
        ),
    ]
    assert result.artists == ()
    assert list(result.albums) == [
        Album(
            uri=Uri("youtube:playlist:PLl8RNOyzcwBjjIajUplE6oV8Vi5Od65H2"),
            name="Rick Astley - Never Gonna Give You Up",
            artists=frozenset({Artist(name="Seh")}),
            num_tracks=50,
        ),
        Album(
            uri=Uri("youtube:playlist:PLd5Vfgy_sILZXNGHKlAHnwPOEhboVQNBG"),
            name="Never Gonna Give You Up",
            artists=frozenset({Artist(name="ゆうきtvメイン")}),
            num_tracks=50,
        ),
        Album(
            uri=Uri("youtube:playlist:PLL8jFEKG82Z7vNDMUamdAcNL4JwGZ8CMG"),
            name="Never Gonna Give You Up version 1 - 16 Variant",
            artists=frozenset({Artist(name="Iris Trismegistus")}),
            num_tracks=18,
        ),
    ]


def test_the_number_of_tracks_of_an_album_is_capped_at_the_playlist_maximum(
    library: Library, japi: jAPI
):
    context.search_results = 3
    context.playlist_max_videos = 20

    result = library.search({"any": ["never gonna give you up"]})

    assert result is not None
    assert [album.num_tracks for album in result.albums] == [20, 20, 18]


def test_a_search_by_uri_is_a_lookup_of_that_uri(library: Library, ytmusic: Any):
    result = library.search({"uri": [f"youtube:video:{SONG_ID}"]})

    assert result is not None
    assert result.uri == "youtube:search"
    assert result.albums == ()
    assert result.artists == ()
    assert [track.uri for track in result.tracks] == [f"youtube:video:{SONG_ID}"]
    ytmusic.search.assert_not_called()


def test_a_search_by_playlist_uri_finds_the_tracks_of_the_playlist(
    library: Library, ytmusic: Any
):
    result = library.search({"uri": [f"youtube:playlist:{PLAYLIST_ID}"]})

    assert result is not None
    assert [describe(track) for track in result.tracks] == korean_playlist_tracks()


def test_a_search_by_uri_only_looks_up_the_first_uri(library: Library, ytmusic: Any):
    result = library.search(
        {"uri": [f"youtube:playlist:{ALBUM_ID}", f"youtube:video:{SONG_ID}"]}
    )

    assert result is not None
    assert [describe(track) for track in result.tracks] == opera_tracks()


def test_a_search_by_a_uri_that_is_unknown_finds_the_unknown_track(library: Library):
    result = library.search({"uri": ["youtube:nothing"]})

    assert result == SearchResult(
        uri=Uri("youtube:search"),
        tracks=(Track(uri=Uri("youtube:video:unknown"), name="Unknown"),),
    )


def test_a_uri_search_wins_over_a_text_search(library: Library, ytmusic: Any):
    result = library.search({"uri": [f"youtube:video:{SONG_ID}"], "any": ["queen"]})

    assert result is not None
    assert [track.uri for track in result.tracks] == [f"youtube:video:{SONG_ID}"]
    ytmusic.search.assert_not_called()


# ===========================================================================
# browse


def test_the_root_directory_is_youtube():
    assert YouTubeLibraryProvider.root_directory == Ref.directory(
        uri=Uri("youtube:browse"), name="YouTube"
    )


def test_the_root_has_the_playlists_and_artists_of_the_channel(library: Library):
    assert library.browse("youtube:browse") == [
        Ref.directory(uri=Uri("youtube:channel:root"), name="My Youtube playlists"),
        Ref.directory(uri=Uri("youtube:channel:artists"), name="My Youtube artists"),
    ]


@pytest.mark.parametrize(
    "uri",
    ["youtube:video:dQw4w9WgXcQ", "youtube:search", "yt:browse", "mp3:folder", ""],
)
def test_other_uris_have_nothing_to_browse(library: Library, uri: str):
    assert library.browse(uri) == []


def test_without_a_channel_there_are_no_playlists_and_no_artists(
    library: Library, ytmusic: Any
):
    assert library.browse("youtube:channel:root") == []
    assert library.browse("youtube:channel:artists") == []


def test_the_playlists_of_the_channel_are_listed_by_name(
    library: Library, japi: jAPI, site: YouTubeSite
):
    context.channel = CHANNEL_ID
    site.add(
        "GET",
        BASE + f"channel/{CHANNEL_ID}/playlists",
        body=page("channel_playlists_lockups.json"),
    )

    refs = library.browse("youtube:channel:root")

    # not in the order of the page, but sorted by name, ignoring case
    assert refs == [
        Ref.playlist(
            uri=Uri(f"youtube:playlist:{CHANNEL_PLAYLIST_IDS[2]}"),
            name="Forever and More",
        ),
        Ref.playlist(
            uri=Uri(f"youtube:playlist:{CHANNEL_PLAYLIST_IDS[1]}"),
            name=(
                "Rick Astley (リック・アストリー) \uff0d "
                "名曲ミュージックビデオ\uff08日本語字幕\uff09"
            ),
        ),
        Ref.playlist(
            uri=Uri(f"youtube:playlist:{CHANNEL_PLAYLIST_IDS[0]}"),
            name="Rick Astley Live at The O2",
        ),
    ]


@pytest.mark.parametrize("scheme", ["youtube", "yt"])
def test_the_playlists_of_another_channel_are_listed_by_its_uri(
    library: Library, japi: jAPI, site: YouTubeSite, scheme: str
):
    site.add(
        "GET",
        BASE + f"channel/{CHANNEL_ID}/playlists",
        body=page("channel_playlists_lockups.json"),
    )

    refs = library.browse(f"{scheme}:channel:{CHANNEL_ID}")

    assert {ref.uri for ref in refs} == {
        f"youtube:playlist:{playlist_id}" for playlist_id in CHANNEL_PLAYLIST_IDS
    }
    assert {ref.type for ref in refs} == {Ref.PLAYLIST}
    (request,) = site.calls("GET", BASE + "channel/")
    assert request.url == BASE + f"channel/{CHANNEL_ID}/playlists"


def test_the_albums_of_an_artist_are_the_playlists_of_its_channel(
    library: Library, ytmusic: Any
):
    set_up_artist_channel(ytmusic)

    refs = library.browse("youtube:channel:root")

    # sorted by name, not in the order of the albums of the artist
    assert refs == [
        Ref.playlist(
            uri=Uri("youtube:playlist:OLAK5uy_n-Fn_Y9_8eezE8hAAvdPJHUuuKRvzVjfw"),
            name="Acoustic",
        ),
        Ref.playlist(
            uri=Uri("youtube:playlist:OLAK5uy_kol_swyj7Jpirgq7d5UnCAghTEX4wLdUg"),
            name="Queen Budapest",
        ),
        Ref.playlist(
            uri=Uri("youtube:playlist:OLAK5uy_mo3flQUFtMFqJlzckSzj63duhUMS6gv5Q"),
            name="Queen II (2026 Mix)",
        ),
    ]


def test_a_channel_that_cannot_be_loaded_has_no_playlists(
    library: Library, japi: jAPI, site: YouTubeSite
):
    context.channel = CHANNEL_ID
    site.add(
        "GET",
        BASE + f"channel/{CHANNEL_ID}/playlists",
        body=page("channel_unavailable.json"),
    )

    assert library.browse("youtube:channel:root") == []
    assert library.browse(f"youtube:channel:{CHANNEL_ID}") == []


def test_a_playlist_is_browsed_as_its_tracks(library: Library, japi: jAPI):
    refs = library.browse(f"youtube:playlist:{JAPI_PLAYLIST_ID}")

    assert refs == [
        Ref.track(uri=Uri(f"youtube:video:{track[0].split(':')[-1]}"), name=track[1])
        for track in japi_playlist_tracks()
    ]


def test_an_album_is_browsed_as_its_tracks_in_order(library: Library, ytmusic: Any):
    refs = library.browse(f"yt:playlist:{ALBUM_ID}")

    assert refs == [
        Ref.track(uri=Uri(track[0]), name=track[1]) for track in opera_tracks()
    ]


def test_a_playlist_that_cannot_be_loaded_is_browsed_as_the_unknown_track(
    library: Library, ytmusic: Any
):
    ytmusic.get_playlist.side_effect = RuntimeError("playlist does not exist")

    refs = library.browse("youtube:playlist:PLgone")

    assert refs == [Ref.track(uri=Uri("youtube:video:unknown"), name="Unknown")]


def test_the_artists_of_the_channel_are_listed_by_name_without_doubles(
    library: Library, ytmusic: Any
):
    set_up_user_channel(ytmusic)

    refs = library.browse("youtube:channel:artists")

    # sorted ignoring case: "i-dle" is between "EPIK HIGH" and "MEOMURU"
    assert refs == [
        Ref.artist(uri=Uri("yt:channel:UCcy9NwrIzmzITEqiVstaN1A"), name="A2O"),
        Ref.artist(uri=Uri("yt:channel:UCCa_4FfbVdc6zhWmRndKwfQ"), name="A2O LITE"),
        Ref.artist(uri=Uri("yt:channel:UCACsUruxumQoyZq08UB9RVw"), name="DAVICHI"),
        Ref.artist(uri=Uri("yt:channel:UCoNq-kohNtB6l7ChNheqW0g"), name="EPIK HIGH"),
        Ref.artist(
            uri=Uri("yt:channel:UCritGVo7pLJLUS8wEu32vow"), name="i-dle (아이들)"
        ),
        Ref.artist(uri=Uri("yt:channel:UCumxj48bP-H_YusbCXi7vkQ"), name="MEOMURU"),
    ]


def test_an_artist_on_several_playlists_is_listed_once(library: Library, ytmusic: Any):
    set_up_artist_channel(ytmusic)

    refs = library.browse("youtube:channel:artists")

    assert refs == [Ref.artist(uri=Uri(QUEEN_URI), name="Queen")]


def test_the_artists_of_the_channel_are_the_channels_of_the_videos(
    library: Library, japi: jAPI, site: YouTubeSite
):
    context.channel = CHANNEL_ID
    site.add(
        "GET",
        BASE + f"channel/{CHANNEL_ID}/playlists",
        body=page("channel_playlists_lockups.json"),
    )

    refs = library.browse("youtube:channel:artists")

    assert refs == [
        Ref.artist(
            uri=Uri("yt:channel:UCu4bj03KW4CwAsYtHSwMEsQ"), name="Arcangel (Channel)"
        ),
        Ref.artist(
            uri=Uri("yt:channel:UCgtNC51EUSgcZ6kKyVoPxKA"), name="Becky G (Channel)"
        ),
        Ref.artist(
            uri=Uri("yt:channel:UCzrM_068Odho89mTRrrxqbA"), name="Peso Pluma (Channel)"
        ),
    ]


def test_the_playlists_of_a_channel_are_only_asked_for_once(
    library: Library, japi: jAPI, site: YouTubeSite
):
    context.channel = CHANNEL_ID
    site.add(
        "GET",
        BASE + f"channel/{CHANNEL_ID}/playlists",
        body=page("channel_playlists_lockups.json"),
    )

    first = library.browse("youtube:channel:root")
    second = library.browse("youtube:channel:root")

    assert second == first
    assert len(site.calls("GET", BASE + "channel/")) == 1


def test_every_channel_uri_is_browsed_and_cached_by_itself(
    library: Library, japi: jAPI, site: YouTubeSite
):
    context.channel = CHANNEL_ID
    site.add(
        "GET",
        BASE + f"channel/{CHANNEL_ID}/playlists",
        body=page("channel_playlists_lockups.json"),
    )

    library.browse("youtube:channel:root")
    library.browse(f"youtube:channel:{CHANNEL_ID}")
    library.browse(f"yt:channel:{CHANNEL_ID}")
    library.browse(f"youtube:channel:{CHANNEL_ID}")

    assert len(site.calls("GET", BASE + "channel/")) == 3


def test_the_albums_of_an_artist_are_only_asked_for_once(
    library: Library, ytmusic: Any
):
    set_up_artist_channel(ytmusic)

    first = library.browse("youtube:channel:root")
    second = library.browse("youtube:channel:root")

    assert second == first
    assert ytmusic.get_artist.call_count == 1
    assert ytmusic.get_artist_albums.call_count == 1


def test_the_artists_of_the_channel_are_only_worked_out_once(
    library: Library, ytmusic: Any
):
    set_up_user_channel(ytmusic)

    first = library.browse("youtube:channel:artists")
    playlists_loaded = ytmusic.get_playlist.call_count
    second = library.browse("youtube:channel:artists")

    assert second == first
    assert ytmusic.get_user.call_count == 1
    assert ytmusic.get_playlist.call_count == playlists_loaded


def test_a_playlist_is_only_loaded_once_by_browsing_it_again(
    library: Library, ytmusic: Any
):
    first = library.browse(f"youtube:playlist:{PLAYLIST_ID}")
    playlists_loaded = ytmusic.get_playlist.call_count
    second = library.browse(f"youtube:playlist:{PLAYLIST_ID}")

    assert second == first
    assert playlists_loaded >= 1
    assert ytmusic.get_playlist.call_count == playlists_loaded


def test_browsing_a_playlist_again_does_not_notice_that_it_has_changed(
    library: Library, ytmusic: Any
):
    first = library.browse(f"youtube:playlist:{PLAYLIST_ID}")
    changed = music_fixture("playlist")
    changed["tracks"] = changed["tracks"][:1]
    ytmusic.get_playlist.side_effect = lambda _: changed

    second = library.browse(f"youtube:playlist:{PLAYLIST_ID}")

    assert len(first) == 4
    assert second == first


# ===========================================================================
# get_images


def test_the_image_of_a_video_is_its_thumbnail_on_youtube(library: Library):
    images = library.get_images([Uri(f"youtube:video:{VIDEO_ID}")])

    assert images == {
        f"youtube:video:{VIDEO_ID}": [
            Image(uri=Uri(f"https://i.ytimg.com/vi_webp/{VIDEO_ID}/maxresdefault.webp"))
        ]
    }


def test_the_images_of_a_video_are_the_thumbnails_the_api_knows(
    library: Library, japi: jAPI
):
    library.lookup(f"youtube:video:{VIDEO_ID}")

    images = library.get_images([Uri(f"youtube:video:{VIDEO_ID}")])

    (image,) = images[Uri(f"youtube:video:{VIDEO_ID}")]
    assert image.uri.startswith("https://i.ytimg.com/vi/dQw4w9WgXcQ/")
    assert (image.width, image.height) == (720, 404)


def test_the_image_of_a_track_of_an_album_is_the_cover_of_the_album(
    library: Library, ytmusic: Any
):
    library.lookup(f"youtube:playlist:{ALBUM_ID}")

    images = library.get_images([Uri("youtube:video:kqVpk0qxmfA")])

    (image,) = images["youtube:video:kqVpk0qxmfA"]
    assert image.uri.startswith("https://yt3.googleusercontent.com/nLn1gx")
    assert (image.width, image.height) == (544, 544)


def test_the_image_of_a_playlist_is_its_thumbnail(library: Library, ytmusic: Any):
    images = library.get_images([Uri(f"youtube:playlist:{PLAYLIST_ID}")])

    (image,) = images[f"youtube:playlist:{PLAYLIST_ID}"]
    assert image.uri.startswith("https://yt3.googleusercontent.com/egwpHc")
    assert (image.width, image.height) == (1200, 1200)


def test_the_image_of_a_playlist_found_by_a_search_is_its_cover(
    library: Library, ytmusic: Any
):
    library.search({"any": ["night at the opera"]})

    images = library.get_images([Uri(f"youtube:playlist:{ALBUM_ID}")])

    (image,) = images[f"youtube:playlist:{ALBUM_ID}"]
    assert image.uri.startswith("https://yt3.googleusercontent.com/nLn1gx")
    assert (image.width, image.height) == (544, 544)


def test_images_are_given_for_each_uri_that_has_one(library: Library, ytmusic: Any):
    uris = [
        Uri(f"youtube:video:{VIDEO_ID}"),
        Uri(f"youtube:playlist:{PLAYLIST_ID}"),
        Uri("youtube:channel:UCsomebody"),
        Uri("youtube:nothing"),
        Uri(f"yt:video:{ZOO_ID}"),
    ]

    images = library.get_images(uris)

    assert set(images) == {uris[0], uris[1], uris[4]}
    assert images[uris[4]][0].uri == (
        f"https://i.ytimg.com/vi_webp/{ZOO_ID}/maxresdefault.webp"
    )


def test_a_single_uri_may_be_given_as_text(library: Library):
    images = library.get_images(f"youtube:video:{VIDEO_ID}")

    assert list(images) == [f"youtube:video:{VIDEO_ID}"]


@pytest.mark.parametrize("uris", [[], ["youtube:nothing"], ["mp3:file.mp3"]])
def test_there_are_no_images_for_uris_that_are_none_of_the_kinds(
    library: Library, uris: list[str]
):
    assert library.get_images([Uri(uri) for uri in uris]) == {}


def test_a_video_that_has_a_cached_image_shows_it_when_the_http_extension_is_on(
    library: Library, tmp_path: Path
):
    context.cache_location = tmp_path
    library.config["http"] = {"enabled": True}
    (tmp_path / f"{VIDEO_ID}.jpg").write_bytes(b"image")
    (tmp_path / f"{ZOO_ID}.webp").write_bytes(b"image")

    images = library.get_images(
        [Uri(f"youtube:video:{VIDEO_ID}"), Uri(f"youtube:video:{ZOO_ID}")]
    )

    assert images == {
        f"youtube:video:{VIDEO_ID}": [Image(uri=Uri(f"/youtube/{VIDEO_ID}.jpg"))],
        f"youtube:video:{ZOO_ID}": [Image(uri=Uri(f"/youtube/{ZOO_ID}.webp"))],
    }


def test_a_cached_webp_is_preferred_to_a_cached_jpg(library: Library, tmp_path: Path):
    context.cache_location = tmp_path
    library.config["http"] = {"enabled": True}
    (tmp_path / f"{VIDEO_ID}.jpg").write_bytes(b"image")
    (tmp_path / f"{VIDEO_ID}.webp").write_bytes(b"image")

    images = library.get_images([Uri(f"youtube:video:{VIDEO_ID}")])

    assert images[Uri(f"youtube:video:{VIDEO_ID}")] == [
        Image(uri=Uri(f"/youtube/{VIDEO_ID}.webp"))
    ]


def test_a_video_without_a_cached_image_shows_its_thumbnail_on_youtube(
    library: Library, tmp_path: Path
):
    context.cache_location = tmp_path
    library.config["http"] = {"enabled": True}
    (tmp_path / f"{ZOO_ID}.jpg").write_bytes(b"image")
    (tmp_path / f"{VIDEO_ID}.json").write_bytes(b"{}")

    images = library.get_images(
        [Uri(f"youtube:video:{VIDEO_ID}"), Uri(f"youtube:video:{ZOO_ID}")]
    )

    assert images[Uri(f"youtube:video:{VIDEO_ID}")][0].uri.startswith("https://")
    assert images[Uri(f"youtube:video:{ZOO_ID}")] == [
        Image(uri=Uri(f"/youtube/{ZOO_ID}.jpg"))
    ]


@pytest.mark.parametrize("http", [{}, {"enabled": False}, None])
def test_cached_images_are_not_shown_unless_the_http_extension_is_on(
    library: Library, tmp_path: Path, http: dict[str, Any] | None
):
    context.cache_location = tmp_path
    library.config["http"] = http
    (tmp_path / f"{VIDEO_ID}.jpg").write_bytes(b"image")

    images = library.get_images([Uri(f"youtube:video:{VIDEO_ID}")])

    assert images[Uri(f"youtube:video:{VIDEO_ID}")][0].uri.startswith("https://")


def test_cached_images_are_not_shown_without_a_cache_location(library: Library):
    library.config["http"] = {"enabled": True}

    images = library.get_images([Uri(f"youtube:video:{VIDEO_ID}")])

    assert images[Uri(f"youtube:video:{VIDEO_ID}")][0].uri.startswith("https://")


def test_a_playlist_always_shows_its_thumbnail(
    library: Library, ytmusic: Any, tmp_path: Path
):
    context.cache_location = tmp_path
    library.config["http"] = {"enabled": True}
    (tmp_path / f"{PLAYLIST_ID}.jpg").write_bytes(b"image")

    images = library.get_images([Uri(f"youtube:playlist:{PLAYLIST_ID}")])

    (image,) = images[f"youtube:playlist:{PLAYLIST_ID}"]
    assert image.uri.startswith("https://")
