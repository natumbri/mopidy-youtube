from unittest import mock

from mopidy_youtube import Extension
from mopidy_youtube import backend as backend_lib
from mopidy_youtube import frontend as frontend_lib


def test_get_default_config():
    ext = Extension()

    config = ext.get_default_config()

    assert "[youtube]" in config
    assert "enabled = true" in config


def test_get_config_schema():
    ext = Extension()

    schema = ext.get_config_schema()

    assert "allow_cache" in schema
    assert "youtube_api_key" in schema
    assert "search_results" in schema
    assert "playlist_max_videos" in schema
    assert "api_enabled" in schema
    assert "channel_id" in schema
    assert "musicapi_enabled" in schema
    assert "musicapi_cookie" in schema
    assert "autoplay_enabled" in schema
    assert "strict_autoplay" in schema
    assert "max_autoplay_length" in schema
    assert "max_degrees_of_separation" in schema


def test_setup():
    registry = mock.Mock()

    ext = Extension()
    ext.setup(registry)

    registry.add.assert_any_call("backend", backend_lib.YouTubeBackend)
    registry.add.assert_any_call("frontend", frontend_lib.YouTubeAutoplayer)
    registry.add.assert_any_call("frontend", backend_lib.YouTubeCoreListener)
    registry.add.assert_any_call(
        "http:app", {"name": ext.ext_name, "factory": ext.webapp}
    )
