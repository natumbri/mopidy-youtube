import pytest
from mopidy import backend as backend_api
from mopidy.core import CoreListener as CoreListener_api

from mopidy_youtube import backend
from mopidy_youtube.backend import (
    YouTubeCoreListener,
    YouTubeLibraryProvider,
    YouTubePlaybackProvider,
)

from tests import apis, get_backend, my_vcr, playlist_uris, video_uris
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
@pytest.mark.parametrize("video_uri", video_uris)
def test_backend_lookup_video(api, config, headers, video_uri):

    with my_vcr.use_cassette(
        f"tests/fixtures/{api['name']}/backend_lookup_video.yaml",
        filter_query_parameters=["key"],
    ):

        setup_entry_api(api, config, headers)

        backend_inst = get_backend(config=config, api_config=api["config"])

        video = backend_inst.library.lookup(video_uri)
        assert len(video) == 1


@pytest.mark.parametrize("api", apis)
@pytest.mark.parametrize("pl_uri", playlist_uris)
def test_backend_lookup_playlist(api, config, headers, pl_uri):

    with my_vcr.use_cassette(
        f"tests/fixtures/{api['name']}/backend_lookup_playlist.yaml",
        filter_query_parameters=["key"],
    ):

        setup_entry_api(api, config, headers)

        backend_inst = get_backend(config=config, api_config=api["config"])

        pl = backend_inst.library.lookup(pl_uri)
        assert pl  # len(pl) == 16
