from unittest import mock

import pytest
import youtube_dl
from mopidy import httpclient

from mopidy_youtube import Extension, youtube

from tests import playlist_uris as playlist_uris_list
from tests import video_uris as video_uris_list

user_agent = "{}/{}".format(Extension.dist_name, Extension.version)


@pytest.fixture
def headers():
    return {
        "user-agent": httpclient.format_user_agent(user_agent),
        "Cookie": "PREF=hl=en;",
        "Accept-Language": "en;q=0.8",
    }


@pytest.fixture
def config(tmp_path):
    return {
        "core": {
            "cache_dir": str(tmp_path / "cache"),
            "data_dir": str(tmp_path / "data"),
        },
        "http": {"enabled": True, "hostname": "::", "port": 6680,},
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
            "youtube_dl_package": "youtube_dl",
        },
        "proxy": {},
    }


@pytest.fixture
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
    video_mock.extract_info.return_value.url = "http://example.com/"
    video_mock.length = 2000
    video_mock.title = "a title"
    video_mock.videoid = "a video id"
    return youtube_dl_mock


@pytest.fixture
def video_uris():
    return video_uris_list


@pytest.fixture
def playlist_uris():
    return playlist_uris_list
