from __future__ import annotations

from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urlparse

import pytest

from mopidy_youtube.apis.youtube_api import API
from mopidy_youtube.context import context

if TYPE_CHECKING:
    from mopidy_youtube.apis import YouTubeApi

    from tests.support import FakeYouTube

BASE = "https://www.googleapis.com/youtube/v3/"


@pytest.fixture
def api(youtube_site: FakeYouTube) -> API:
    api = API(None, {"user-agent": "test"}, "SECRET")
    youtube_site.attach(api)
    return api


def query_of(youtube_site: FakeYouTube, endpoint: str) -> dict[str, str]:
    (request,) = youtube_site.calls("GET", BASE + endpoint)
    return {k: v[0] for k, v in parse_qs(urlparse(request.url).query).items()}


def test_it_satisfies_the_api_protocol(api: API):
    client: YouTubeApi = api

    assert client.session is api.session


def test_search_asks_for_videos_and_playlists_with_the_key_and_limit(
    api: API, youtube_site: FakeYouTube
):
    context.search_results = 7
    youtube_site.add("GET", BASE + "search", json_data={"items": [{"id": {}}]})

    result = api.search("never gonna give you up")

    assert result == {"items": [{"id": {}}]}
    query = query_of(youtube_site, "search")
    assert query["q"] == "never gonna give you up"
    assert query["key"] == "SECRET"
    assert query["type"] == "video,playlist"
    assert query["maxResults"] == "7"


def test_list_related_videos_searches_by_related_video(
    api: API, youtube_site: FakeYouTube
):
    youtube_site.add("GET", BASE + "search", json_data={"items": []})

    api.list_related_videos("abc123defgh")

    query = query_of(youtube_site, "search")
    assert query["relatedToVideoId"] == "abc123defgh"
    assert query["type"] == "video"
    assert query["key"] == "SECRET"


def test_list_videos_joins_the_ids(api: API, youtube_site: FakeYouTube):
    youtube_site.add("GET", BASE + "videos", json_data={"items": []})

    api.list_videos(["aaaaaaaaaaa", "bbbbbbbbbbb"])

    query = query_of(youtube_site, "videos")
    assert query["id"] == "aaaaaaaaaaa,bbbbbbbbbbb"
    assert "contentDetails" in query["part"]


def test_list_playlists_joins_the_ids(api: API, youtube_site: FakeYouTube):
    youtube_site.add("GET", BASE + "playlists", json_data={"items": []})

    api.list_playlists(["PL1", "PL2"])

    assert query_of(youtube_site, "playlists")["id"] == "PL1,PL2"


def test_list_playlistitems_passes_the_page_and_page_size(
    api: API, youtube_site: FakeYouTube
):
    youtube_site.add(
        "GET", BASE + "playlistItems", json_data={"items": [], "nextPageToken": "T"}
    )

    result = api.list_playlistitems("PL1", "PAGE2", 25)

    assert result["nextPageToken"] == "T"
    query = query_of(youtube_site, "playlistItems")
    assert query["playlistId"] == "PL1"
    assert query["pageToken"] == "PAGE2"
    assert query["maxResults"] == "25"


def test_list_playlistitems_omits_an_empty_page_token(
    api: API, youtube_site: FakeYouTube
):
    youtube_site.add("GET", BASE + "playlistItems", json_data={"items": []})

    api.list_playlistitems("PL1", None, 50)

    assert "pageToken" not in query_of(youtube_site, "playlistItems")


def test_list_channelplaylists_filters_by_channel(api: API, youtube_site: FakeYouTube):
    youtube_site.add("GET", BASE + "playlists", json_data={"items": []})

    api.list_channelplaylists("UC123")

    query = query_of(youtube_site, "playlists")
    assert query["channelId"] == "UC123"
    assert query["maxResults"] == "50"


def test_errors_are_returned_for_the_caller_to_handle(
    api: API, youtube_site: FakeYouTube
):
    error: dict[str, Any] = {"error": {"code": 400, "message": "API key not valid"}}
    youtube_site.add("GET", BASE + "search", json_data=error, status=400)

    assert api.search("anything") == error


def test_close_shuts_down_the_executor(api: API):
    api.close()

    with pytest.raises(RuntimeError, match="shutdown"):
        api.executor.submit(print)
