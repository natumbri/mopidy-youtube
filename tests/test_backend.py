import pytest
from mopidy import backend as backend_api
from mopidy.core import CoreListener as CoreListener_api
from mopidy.models import Album, Image, Ref, SearchResult, Track

from mopidy_youtube import backend, youtube  # , data, youtube
from mopidy_youtube.backend import (
    YouTubeCoreListener,
    YouTubeLibraryProvider,
    YouTubePlaybackProvider,
)

from tests import apis, channel_uris, get_backend, my_vcr, playlist_uris, video_uris
from tests.test_api import setup_entry_api


def get_corelistener(config):
    obj = backend.YouTubeCoreListener(config=config, core=None)
    return obj


def test_uri_schemes(config):
    backend = get_backend(config, {})

    assert "youtube" in backend.uri_schemes
    assert "yt" in backend.uri_schemes


def test_init_sets_up_the_providers(config):
    backend = get_backend(config, {})

    assert isinstance(backend.library, YouTubeLibraryProvider)
    assert isinstance(backend.library, backend_api.LibraryProvider)

    assert isinstance(backend.playback, YouTubePlaybackProvider)
    assert isinstance(backend.playback, backend_api.PlaybackProvider)

    core = get_corelistener(config)

    assert isinstance(core, YouTubeCoreListener)
    assert isinstance(core, CoreListener_api)


@pytest.mark.parametrize("api", apis)
def test_on_start_configures_the_api(api, config, headers):
    with my_vcr.use_cassette(f"tests/fixtures/{api['name']}/backend_on_start.yaml"):
        backend_inst = get_backend(config=config, api_config=api["config"])
        backend_inst.on_start()
        assert isinstance(youtube.Entry.api, api["class"])


@pytest.mark.parametrize("api", apis)
@pytest.mark.parametrize("playlist_uri", playlist_uris)
def test_backend_browse_playlist(api, config, headers, playlist_uri):

    with my_vcr.use_cassette(
        f"tests/fixtures/{api['name']}/backend_browse_playlist.yaml"
    ):

        setup_entry_api(api, config, headers)

        backend_inst = get_backend(config=config, api_config=api["config"])

        playlist = backend_inst.library.browse(playlist_uri)
        assert isinstance(playlist, list)
        assert isinstance(playlist[0], Ref)


@pytest.mark.parametrize("api", apis)
@pytest.mark.parametrize("channel_uri", channel_uris)
def test_backend_browse_channel(api, config, headers, channel_uri):

    with my_vcr.use_cassette(
        f"tests/fixtures/{api['name']}/backend_browse_channel.yaml"
    ):

        setup_entry_api(api, config, headers)

        backend_inst = get_backend(config=config, api_config=api["config"])

        channel = backend_inst.library.browse(channel_uri)
        assert isinstance(channel, list)
        assert isinstance(channel[0], Ref)


@pytest.mark.parametrize("api", apis)
def test_backend_search(api, config, headers):

    with my_vcr.use_cassette(f"tests/fixtures/{api['name']}/backend_search.yaml"):

        setup_entry_api(api, config, headers)

        backend_inst = get_backend(config=config, api_config=api["config"])

        search_result = backend_inst.library.search(query={"omit-any": ["chvrches"]})
        assert search_result is None

        search_result = backend_inst.library.search(query={"any": ["chvrches"]})

        # assert len(videos.tracks) == 18

        assert isinstance(search_result, SearchResult)
        # assert isinstance(search_result.tracks, list)
        assert isinstance(search_result.tracks[0], Track)
        # assert isinstance(search_result.albums, list)

        # does the youtube API return albums??
        if search_result.albums:
            assert isinstance(search_result.albums[0], Album)
        # assert isinstance(search_result.artists, list)


@pytest.mark.parametrize("api", apis)
@pytest.mark.parametrize("video_uri", video_uris)
def test_backend_lookup_video(api, config, headers, video_uri):

    with my_vcr.use_cassette(f"tests/fixtures/{api['name']}/backend_lookup_video.yaml"):

        setup_entry_api(api, config, headers)

        backend_inst = get_backend(config=config, api_config=api["config"])

        video = backend_inst.library.lookup(video_uri)
        assert len(video) == 1


@pytest.mark.parametrize("api", apis)
@pytest.mark.parametrize("pl_uri", playlist_uris)
def test_backend_lookup_playlist(api, config, headers, pl_uri):

    with my_vcr.use_cassette(
        f"tests/fixtures/{api['name']}/backend_lookup_playlist.yaml"
    ):

        setup_entry_api(api, config, headers)

        backend_inst = get_backend(config=config, api_config=api["config"])

        pl = backend_inst.library.lookup(pl_uri)
        assert pl  # len(pl) == 16


@pytest.mark.parametrize("api", apis)
@pytest.mark.parametrize("video_uri", video_uris)
def test_backend_get_video_image(api, config, headers, video_uri):

    with my_vcr.use_cassette(
        f"tests/fixtures/{api['name']}/backend_get_video_image.yaml"
    ):

        setup_entry_api(api, config, headers)
        backend_inst = get_backend(config=config, api_config=api["config"])
        images = backend_inst.library.get_images(video_uri)
        assert isinstance(images, dict)
        assert isinstance(images[video_uri], list)
        assert isinstance(images[video_uri][0], Image)


@pytest.mark.parametrize("api", apis)
def test_backend_get_video_images(api, config, headers, video_uris):

    with my_vcr.use_cassette(
        f"tests/fixtures/{api['name']}/backend_get_video_images.yaml"
    ):

        setup_entry_api(api, config, headers)

        backend_inst = get_backend(config=config, api_config=api["config"])
        setup_entry_api(api, config, headers)
        images = backend_inst.library.get_images(video_uris)
        assert isinstance(images, dict)
        assert isinstance(images[video_uris[0]], list)
        assert isinstance(images[video_uris[0]][0], Image)
        for video_uri in video_uris:
            for video_Image in images[video_uri]:
                assert isinstance(video_Image, Image)

        assert len(images) == 9


@pytest.mark.parametrize("api", apis)
@pytest.mark.parametrize("playlist_uri", playlist_uris)
def test_backend_get_playlist_image(api, config, headers, playlist_uri):

    with my_vcr.use_cassette(
        f"tests/fixtures/{api['name']}/backend_get_playlist_image.yaml"
    ):

        setup_entry_api(api, config, headers)
        backend_inst = get_backend(config=config, api_config=api["config"])
        images = backend_inst.library.get_images(playlist_uri)
        assert isinstance(images, dict)
        assert isinstance(images[playlist_uri], list)
        for playlist_Image in images[playlist_uri]:
            assert isinstance(playlist_Image, Image)


@pytest.mark.parametrize("api", apis)
@pytest.mark.parametrize("video_uri", video_uris)
def test_backend_playback_translate_uri(
    api, config, headers, video_uri, youtube_dl_mock_with_video
):

    with my_vcr.use_cassette(
        f"tests/fixtures/{api['name']}/backend_playback_translate_uri.yaml"
    ):

        setup_entry_api(api, config, headers)
        backend_inst = get_backend(config=config, api_config=api["config"])
        youtube.Video.proxy = None
        audio_url = backend_inst.playback.translate_uri(video_uri)
        # How to test this?
        assert audio_url
