from mopidy_youtube import Extension
from mopidy_youtube import frontend as frontend_lib


def test_get_default_config():
        ext = Extension()
        config = ext.get_default_config()
        assert '[youtube]' in config
        assert 'enabled = true' in config
        assert 'youtube_api_key = ' in config
        assert 'threads_max = 16' in config
        assert 'search_results = 15' in config
        assert 'playlist_max_videos = 20' in config

def test_get_config_schema():
        ext = Extension()
        schema = ext.get_config_schema()

        # TODO Test the content of your config schema
        # assert "username" in schema
        # assert "password" in schema
        
        # TODO Write more tests

