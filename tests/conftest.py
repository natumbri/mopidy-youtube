import pytest


@pytest.fixture
def config(tmp_path):
    return {
        "core": {
            "cache_dir": str(tmp_path / "cache"),
            "data_dir": str(tmp_path / "data"),
        },
        "youtube": {
            "enabled": True,
            "allow_cache": None,
            "youtube_api_key": None,
            "channel_id": None,
            "search_results": 15,
            "playlist_max_videos": 20,
            "api_enabled": False,
            "musicapi_enabled": False,
            "musicapi_cookie": None,
            "autoplay_enabled": False,
            "strict_autoplay": False,
            "max_autoplay_length": 600,
            "max_degrees_of_separation": 3,
        },
        "proxy": {},
    }
