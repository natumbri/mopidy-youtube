from mopidy_youtube import Extension


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

    # TODO Test the content of your config schema
    # assert "username" in schema
    # assert "password" in schema

    # TODO Write more tests
