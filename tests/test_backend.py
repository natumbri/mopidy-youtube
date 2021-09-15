# import threading
from unittest import mock
import vcr

from mopidy import httpclient
from mopidy import backend as backend_api
from mopidy.core import CoreListener as CoreListener_api

from mopidy_youtube import Extension, backend, youtube
from mopidy_youtube.backend import (
    YouTubeCoreListener,
    YouTubeLibraryProvider,
    YouTubePlaybackProvider,
)
from mopidy_youtube.apis import youtube_japi

user_agent = "{}/{}".format(Extension.dist_name, Extension.version)

headers = {
    "user-agent": httpclient.format_user_agent(user_agent),
    "Cookie": "PREF=hl=en;",
    "Accept-Language": "en;q=0.8",
}


def get_backend(config, session_mock=None):
    obj = backend.YouTubeBackend(config=config, audio=None)
    if session_mock:
        obj._session = session_mock
    else:
        obj._session = mock.Mock()
        obj._web_client = mock.Mock()
    obj._event_loop = mock.Mock()
    return obj


def get_corelistener(config):
    obj = backend.YouTubeCoreListener(config=config, core=None)
    return obj


def test_uri_schemes(config):
    backend = get_backend(config)

    assert "youtube" in backend.uri_schemes
    assert "yt" in backend.uri_schemes


def test_init_sets_up_the_providers(config):
    backend = get_backend(config)

    assert isinstance(backend.library, YouTubeLibraryProvider)
    assert isinstance(backend.library, backend_api.LibraryProvider)

    assert isinstance(backend.playback, YouTubePlaybackProvider)
    assert isinstance(backend.playback, backend_api.PlaybackProvider)

    core = get_corelistener(config)

    assert isinstance(core, YouTubeCoreListener)
    assert isinstance(core, CoreListener_api)


@vcr.use_cassette("tests/fixtures/youtube_playlist.yaml")
def test_get_playlist(config):

    youtube.Entry.api = youtube_japi.jAPI(proxy=config["proxy"], headers=headers)

    pl = youtube.Playlist.get("PLJD13y84Bd032qVrq7CHBLEfKZZtp-u1j")

    assert len(pl.videos.get()) == 20
    assert pl.videos.get()[0].title.get()

    # Playlist.videos starts loading video info in the background
    video = pl.videos.get()[0]  # don't know what video[0] will be
    assert video._length  # should be ready
    # assert video.length.get() == 277  # don't know what the length will be

    pl2 = youtube.Playlist.get("PLJD13y84Bd032qVrq7CHBLEfKZZtp-u1j")

    assert pl2 is pl  # fetch from cache
    assert pl._videos  # should be ready


@vcr.use_cassette("tests/fixtures/youtube_list_playlists.yaml")
def test_list_playlists(config):

    youtube.Entry.api = youtube_japi.jAPI(proxy=config["proxy"], headers=headers)

    playlists = youtube.Entry.api.list_playlists(
        [
            "PLJD13y84Bd032qVrq7CHBLEfKZZtp-u1j",
            "PLJD13y84Bd01Q8b8ONfwNMLD3pVBcqwMq",
        ]
    )

    assert len(playlists["items"]) == 2


@vcr.use_cassette("tests/fixtures/youtube_search.yaml")
def test_search(config):

    youtube.Entry.api = youtube_japi.jAPI(proxy=config["proxy"], headers=headers)
    backend_inst = get_backend(config)

    videos = backend_inst.library.search(query={"omit-any": ["chvrches"]})
    assert videos is None

    videos = backend_inst.library.search(query={"any": ["chvrches"]})
    assert len(videos.tracks) == 18

    videos = youtube.Entry.search("chvrches")
    assert len(videos) == 18
    assert videos[0]._title  # should be ready
    assert videos[0]._channel  # should be ready
    assert videos[0]._length  # should be ready (scrAPI)

    video = youtube.Video.get("mDqJIBvcuUw")

    assert video in videos  # cached


@vcr.use_cassette("tests/fixtures/youtube_lookup.yaml", filter_query_parameters=["key"])
def test_lookup(config):

    youtube.Entry.api = youtube_japi.jAPI(proxy=config["proxy"], headers=headers)
    backend_inst = get_backend(config)

    video_uris = [
        "youtube:https://www.youtube.com/watch?v=nvlTJrNJ5lA",
        "yt:https://www.youtube.com/watch?v=nvlTJrNJ5lA",
        "youtube:https://youtu.be/nvlTJrNJ5lA",
        "yt:https://youtu.be/nvlTJrNJ5lA",
        # "youtube:https://www.youtube.com/watch?v=1lWJXDG2i0A",
        "youtube:video/Tom Petty And The Heartbreakers - I Won't Back Down (Official Music Video).nvlTJrNJ5lA",
        "yt:video/Tom Petty And The Heartbreakers - I Won't Back Down (Official Music Video).nvlTJrNJ5lA",
        "youtube:video:nvlTJrNJ5lA",
        "yt:video:nvlTJrNJ5lA",
    ]
    for video_uri in video_uris:
        video = backend_inst.library.lookup(video_uri)
        assert len(video) == 1

    playlist_uris = [
        "youtube:https://www.youtube.com/watch?v=SIhb-kNvL6M&list=PLo4c-riVwz2miWOT3Y2VWzg2bmV4FmC8J",
        "yt:https://www.youtube.com/watch?v=SIhb-kNvL6M&list=PLo4c-riVwz2miWOT3Y2VWzg2bmV4FmC8J",
        # "youtube:https://www.youtube.com/watch?v=lis8WGZQ9tw&list=PLW3M-yio9tLtQLihn1wrJYzuV7AUPMq63",
        # "yt:https://www.youtube.com/watch?v=lis8WGZQ9tw&list=PLW3M-yio9tLtQLihn1wrJYzuV7AUPMq63",
        "youtube:playlist/Tom Petty's greatest hits album.PLo4c-riVwz2miWOT3Y2VWzg2bmV4FmC8J",
        "yt:playlist/Tom Petty's greatest hits album.PLo4c-riVwz2miWOT3Y2VWzg2bmV4FmC8J",
        "youtube:playlist:PLo4c-riVwz2miWOT3Y2VWzg2bmV4FmC8J",
        "yt:playlist:PLo4c-riVwz2miWOT3Y2VWzg2bmV4FmC8J",
    ]
    for playlist_uri in playlist_uris:
        playlist = backend_inst.library.lookup(playlist_uri)
        assert len(playlist) == 16
