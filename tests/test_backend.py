import youtube_dl
from mopidy import httpclient

# import os
import mock
import pytest
import vcr
from mopidy_youtube import Extension, backend, youtube
from mopidy_youtube.apis import youtube_api, youtube_bs4api, youtube_scrapi

proxy = None  # httpclient.format_proxy(config['proxy'])
youtube.Video.proxy = proxy

user_agent = "{}/{}".format(Extension.dist_name, Extension.version)

headers = {
    "user-agent": httpclient.format_user_agent(user_agent),
    "Cookie": "PREF=hl=en;",
    "Accept-Language": "en;q=0.8",
}

# youtube_api.youtube_api_key = os.environ.get("YOUTUBE_API_KEY", "FAKE_API_KEY")

yak = "fakeyoutubekey"
youtube_api.youtube_api_key = yak


@pytest.yield_fixture
def youtube_dl_mock():
    patcher = mock.patch.object(youtube, "youtube_dl", spec=youtube_dl)
    yield patcher.start()
    patcher.stop()


@pytest.fixture
def youtube_dl_mock_with_video(youtube_dl_mock):
    video_mock = youtube_dl_mock.YoutubeDL.return_value
    video_mock.bigthumb = "big thumb"
    video_mock.bigthumbhd = "big thumb in hd"
    video_mock.getbestaudio.return_value.url = "http://example.com/"
    video_mock.length = 2000
    video_mock.title = "a title"
    video_mock.videoid = "a video id"

    return youtube_dl_mock


@pytest.fixture
def config():
    return {
        "core": {"cache_dir": "."},
        "http": {"hostname": "127.0.0.1", "port": "6680"},
        "youtube": {
            "enabled": "true",
            "youtube_api_key": yak,
            "threads_max": 16,
            "search_results": 30,
            "playlist_max_videos": 20,
            "api_enabled": False,
        },
    }


def get_backend(config):
    return backend.YouTubeBackend(config=config, audio=mock.Mock())


def test_uri_schemes(config):
    backend_inst = get_backend(config)

    assert "youtube" in backend_inst.uri_schemes
    assert "yt" in backend_inst.uri_schemes


def test_init_sets_up_the_providers(config):
    backend_inst = get_backend(config)

    assert isinstance(backend_inst.library, backend.YouTubeLibraryProvider)
    assert isinstance(backend_inst.playback, backend.YouTubePlaybackProvider)


# need to work out how to add youtube_api.API to this list
apis = [youtube_scrapi.scrAPI, youtube_bs4api.bs4API]


@vcr.use_cassette(
    "tests/fixtures/youtube_playlist.yaml", filter_query_parameters=["key"]
)
def test_get_playlist(config):

    for api in apis:
        youtube.Entry.api = api(proxy, headers)

        pl = youtube.Playlist.get("PLvdVG7oER2eFutjd4xl3TGNDui9ELvY4D")

        assert len(pl.videos.get()) == 20
        assert pl.videos.get()[0].title.get()

        # Playlist.videos starts loading video info in the background
        video = pl.videos.get()[0]
        assert video._length  # should be ready
        assert video.length.get() == 392

        pl2 = youtube.Playlist.get("PLvdVG7oER2eFutjd4xl3TGNDui9ELvY4D")

        assert pl2 is pl  # fetch from cache
        assert pl._videos  # should be ready


@vcr.use_cassette(
    "tests/fixtures/youtube_list_playlists.yaml",
    filter_query_parameters=["key"],
)
def test_list_playlists(config):

    for api in apis:
        youtube.Entry.api = api(proxy, headers)

        playlists = api.list_playlists(
            [
                "PLfGibfZATlGq6zF72No5BZaScBiWWb6U1",
                "PLRHAVCbqFwJBkRupIhuGW3_XEIWc-ZYER",
            ]
        )

        assert len(playlists["items"]) == 2


@vcr.use_cassette(
    "tests/fixtures/youtube_search.yaml", filter_query_parameters=["key"]
)
def test_search(config):

    for api in apis:
        youtube.Entry.api = api(proxy, headers)
        backend_inst = get_backend(config)

        videos = backend_inst.library.search(query={"omit-any": ["chvrches"]})
        assert videos is None

        videos = backend_inst.library.search(query={"any": ["chvrches"]})
        assert len(videos.tracks) == 30

        videos = youtube.Entry.search("chvrches")
        assert len(videos) == 30
        assert videos[0]._title  # should be ready
        assert videos[0]._channel  # should be ready
        # assert videos[0]._length  # should be ready (scrAPI)

        video = youtube.Video.get("BZyzX4c1vIs")

        assert video in videos  # cached


@vcr.use_cassette(
    "tests/fixtures/youtube_lookup.yaml", filter_query_parameters=["key"]
)
def test_lookup(config):

    for api in apis:
        youtube.Entry.api = api(proxy, headers)
        backend_inst = get_backend(config)

        video_uris = [
            "yt:https://www.youtube.com/watch?v=s5BJXwNeKsQ",
            "youtube:https://www.youtube.com/watch?v=1lWJXDG2i0A",
            "youtube:video/Tom Petty And The Heartbreakers - "
            "I Won't Back Down (Official Music Video).nvlTJrNJ5lA",
        ]
        for video_uri in video_uris:
            video = backend_inst.library.lookup(video_uri)
            assert len(video) == 1

        playlist_uris = [
            "yt:https://www.youtube.com/watch?v=SIhb-kNvL6M"
            "&list=PLo4c-riVwz2miWOT3Y2VWzg2bmV4FmC8J",
            "youtube:https://www.youtube.com/watch?v=lis8WGZQ9tw"
            "&list=PLW3M-yio9tLtQLihn1wrJYzuV7AUPMq63",
            "youtube:playlist/Tom Petty and The Heartbreakers GREATEST HITS "
            "(Complete Album).PLrpyDacBCh7Bs3cNzKtMbuafcK_nw9znk",
        ]
        for playlist_uri in playlist_uris:
            playlist = backend_inst.library.lookup(playlist_uri)
            assert len(playlist) == 18


@vcr.use_cassette(
    "tests/fixtures/youtube_get_video.yaml", filter_query_parameters=["key"]
)
def test_get_video(config):

    for api in apis:
        youtube.Entry.api = api(proxy, headers)

        video = youtube.Video.get("e1YqueG2gtQ")

        assert video.length.get()

        # get again, should fetch from cache, _length should be ready
        video2 = youtube.Video.get("e1YqueG2gtQ")

        assert video2 is video
        assert video2._length


@vcr.use_cassette(
    "tests/fixtures/youtube_list_videos.yaml", filter_query_parameters=["key"]
)
def test_list_videos(config):

    for api in apis:
        youtube.Entry.api = api(proxy, headers)

        videos = api.list_videos(["_mTRvJ9fugM", "h_uyq8oGDvU"])

        assert len(videos["items"]) == 2


@vcr.use_cassette(
    "tests/fixtures/youtube_list_playlistitems.yaml",
    filter_query_parameters=["key"],
)
def test_list_playlistitems(config):

    for api in apis:
        youtube.Entry.api = api(proxy, headers)

        playlistitems = api.list_playlistitems(
            "PLvdVG7oER2eFutjd4xl3TGNDui9ELvY4D", None, 20
        )

        assert len(playlistitems["items"]) == 20


def test_audio_url(youtube_dl_mock_with_video):

    for api in apis:
        youtube.Entry.api = api(proxy, headers)

        video = youtube.Video.get("e1YqueG2gtQ")

        assert video.audio_url.get()


def test_audio_url_fail(youtube_dl_mock):

    for api in apis:
        youtube.Entry.api = api(proxy, headers)

        youtube_dl_mock.YoutubeDL.side_effect = Exception("Removed")

        video = youtube.Video.get("unknown")

        assert not video.audio_url.get()
