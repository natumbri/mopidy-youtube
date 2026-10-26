from unittest import mock

from mopidy_youtube import Extension
from mopidy_youtube import backend as backend_lib
from mopidy_youtube import frontend as frontend_lib

REQUIRED_CONFIG_KEYS = [
    "allow_cache",
    "youtube_api_key",
    "channel_id",
    "search_results",
    "playlist_max_videos",
    "api_enabled",
    "musicapi_enabled",
    "musicapi_cookie",
    "musicapi_browser_authentication_file",
    "musicapi_cookiefile",
    "history_enabled",
    "autoplay_enabled",
    "strict_autoplay",
    "max_autoplay_length",
    "max_degrees_of_separation",
    "youtube_dl_package",
]


def test_get_default_config_contains_extension_header_and_defaults():
    config = Extension().get_default_config()

    assert "[youtube]" in config
    assert "enabled = true" in config
    assert "search_results = 15" in config
    assert "playlist_max_videos = 20" in config


def test_get_config_schema_registers_expected_keys():
    schema = Extension().get_config_schema()

    for key in REQUIRED_CONFIG_KEYS:
        assert key in schema


def test_setup_registers_backend_and_frontend_services():
    registry = mock.Mock()
    ext = Extension()

    ext.setup(registry)

    registry.add.assert_any_call("backend", backend_lib.YouTubeBackend)
    registry.add.assert_any_call("frontend", frontend_lib.YouTubeAutoplayer)
    registry.add.assert_any_call("frontend", backend_lib.YouTubeCoreListener)
    registry.add.assert_any_call(
        "http:app", {"name": ext.ext_name, "factory": ext.webapp}
    )
