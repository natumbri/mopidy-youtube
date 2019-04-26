from __future__ import unicode_literals

from mopidy_youtube import Extension


def test_get_default_config():
    ext = Extension()

    config = ext.get_default_config()

    assert '[youtube]' in config
    assert 'enabled = true' in config
    assert 'youtube_api_key = ' in config
    assert 'threads_max = 16' in config
    assert 'search_results = 15' in config
    assert 'playlist_max_videos = 20' in config
