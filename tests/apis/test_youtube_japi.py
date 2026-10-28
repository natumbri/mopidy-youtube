"""Tests for the scraping client (jAPI) against recorded YouTube pages.

The fixtures in `tests/fixtures/japi/` are real responses, trimmed to the parts
the client reads. YouTube has since moved most renderers to `lockupViewModel`,
which jAPI reads next to the renderer layout it was written for
(`compactVideoRenderer`, `playlistVideoRenderer`, `gridPlaylistRenderer`, ...).
The older layout is built by the helpers below; the current one comes from the
fixtures.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urlparse

import pytest

from mopidy_youtube.apis.youtube_japi import NoYtDataError, jAPI
from mopidy_youtube.context import context

from tests.apis.conftest import FakeYouTube, load_fixture, yt_initial_data_page

if TYPE_CHECKING:
    from collections.abc import Iterator

    import requests

BASE = "https://www.youtube.com/"
SEARCH_URL = BASE + "youtubei/v1/search"

VIDEO_ID = "dQw4w9WgXcQ"
OTHER_VIDEO_ID = "3BFTio5296w"
ZOO_VIDEO_ID = "jNQXAC9IVRw"
MISSING_VIDEO_ID = "zzzzzzzzzzz"
PLAYLIST_ID = "PLFgquLnL59alCl_2TQvOiD5Vgm1hCaGSI"
CHANNEL_ID = "UCuAXFkgsw1L7xaCfnd5JJOw"

VIDEO_SP = "EgIQAQ%3D%3D"
PLAYLIST_SP = "EgIQAw%3D%3D"

RICK_TITLE = "Rick Astley - Never Gonna Give You Up (Official Video) (4K Remaster)"


# -- helpers ------------------------------------------------------------------


@pytest.fixture
def japi(youtube_site: FakeYouTube) -> Iterator[jAPI]:
    client = jAPI(None, {})
    youtube_site.attach(client)
    yield client
    client.close()


def page(name: str) -> str:
    """A fixture served the way youtube.com embeds its data in html pages."""
    return yt_initial_data_page(load_fixture(f"japi/{name}"))


def query_of(request: requests.PreparedRequest) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlparse(request.url).query).items()}


def only_call(youtube_site: FakeYouTube, method: str, url: str) -> dict[str, str]:
    (request,) = youtube_site.calls(method, url)
    return query_of(request)


def video_renderer(
    video_id: str, *, kind: str = "videoRenderer", **overrides: Any
) -> dict[str, Any]:
    """A video the way pre-lockup YouTube listed it; `field=None` drops a field."""
    renderer: dict[str, Any] = {
        "videoId": video_id,
        "title": {"simpleText": f"Title {video_id}"},
        "thumbnail": {
            "thumbnails": [
                {"url": f"https://i.ytimg.com/{video_id}/s.jpg?sqp=1", "width": 1},
                {"url": f"https://i.ytimg.com/{video_id}/l.jpg?sqp=2&rs=3", "width": 2},
            ]
        },
        "longBylineText": {
            "runs": [
                {
                    "text": f"Channel {video_id}",
                    "navigationEndpoint": {"browseEndpoint": {"browseId": "UC1"}},
                }
            ]
        },
        "lengthText": {"simpleText": "3:34"},
    }
    renderer.update(overrides)
    return {kind: {k: v for k, v in renderer.items() if v is not None}}


def playlist_renderer(playlist_id: str, **overrides: Any) -> dict[str, Any]:
    renderer: dict[str, Any] = {
        "playlistId": playlist_id,
        "videoCount": "3",
        "title": {"simpleText": f"Playlist {playlist_id}"},
        "thumbnails": [
            {"thumbnails": [{"url": f"https://i.ytimg.com/{playlist_id}.jpg?x"}]}
        ],
        "longBylineText": {"runs": [{"text": f"Owner of {playlist_id}"}]},
    }
    renderer.update(overrides)
    return {"playlistRenderer": {k: v for k, v in renderer.items() if v is not None}}


def grid_playlist_renderer(
    playlist_id: str,
    *,
    thumbnail_kind: str | None = "playlistVideoThumbnailRenderer",
    **overrides: Any,
) -> dict[str, Any]:
    renderer: dict[str, Any] = {
        "playlistId": playlist_id,
        "title": {"runs": [{"text": f"Grid {playlist_id}"}]},
        "videoCountShortText": {"simpleText": "1,234"},
    }
    if thumbnail_kind:
        renderer["thumbnailRenderer"] = {
            thumbnail_kind: {
                "thumbnail": {
                    "thumbnails": [
                        {"url": f"https://i.ytimg.com/{playlist_id}/a.jpg?x=1"},
                        {"url": f"https://i.ytimg.com/{playlist_id}/b.jpg?x=2"},
                    ]
                }
            }
        }
    renderer.update(overrides)
    return {
        "gridPlaylistRenderer": {k: v for k, v in renderer.items() if v is not None}
    }


def search_doc(
    items: list[dict[str, Any]], continuation: str | None = None
) -> dict[str, Any]:
    sections: list[dict[str, Any]] = [{"itemSectionRenderer": {"contents": items}}]
    if continuation:
        sections.append(
            {
                "continuationItemRenderer": {
                    "continuationEndpoint": {
                        "continuationCommand": {"token": continuation}
                    }
                }
            }
        )
    return {
        "contents": {
            "twoColumnSearchResultsRenderer": {
                "primaryContents": {"sectionListRenderer": {"contents": sections}}
            }
        }
    }


def continuation_doc(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "onResponseReceivedCommands": [
            {
                "appendContinuationItemsAction": {
                    "continuationItems": [{"itemSectionRenderer": {"contents": items}}]
                }
            }
        ]
    }


def related_doc(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "contents": {
            "twoColumnWatchNextResults": {
                "secondaryResults": {
                    "secondaryResults": {
                        "results": [
                            {"compactAutoplayRenderer": {}},
                            {"itemSectionRenderer": {"contents": items}},
                        ]
                    }
                }
            }
        }
    }


def playlist_doc(items: list[dict[str, Any]]) -> dict[str, Any]:
    list_renderer = {"playlistVideoListRenderer": {"contents": items}}
    section = {"itemSectionRenderer": {"contents": [list_renderer]}}
    tab = {"tabRenderer": {"content": {"sectionListRenderer": {"contents": [section]}}}}
    return {"contents": {"twoColumnBrowseResultsRenderer": {"tabs": [tab]}}}


def channel_doc(items: list[dict[str, Any]]) -> dict[str, Any]:
    grid = {"gridRenderer": {"items": items}}
    section = {"itemSectionRenderer": {"contents": [grid]}}
    tab = {"tabRenderer": {"content": {"sectionListRenderer": {"contents": [section]}}}}
    return {"contents": {"twoColumnBrowseResultsRenderer": {"tabs": [tab]}}}


class SearchSite(FakeYouTube):
    """Serves youtubei search responses by `params` and by continuation.

    A page is `(status, body)`. A request without a page raises a connection
    error, and so does the request that would make it a runaway loop.
    """

    max_requests = 6

    def __init__(self, pages: dict[tuple[str, bool], tuple[int, str]]) -> None:
        super().__init__()
        self.pages = pages

    @staticmethod
    def ok(data: Any) -> tuple[int, str]:
        return 200, json.dumps(data)

    def send(self, request: requests.PreparedRequest, *args: Any, **kwargs: Any):
        if len(self.requests) >= self.max_requests:
            self.requests.append(request)
            msg = "runaway request loop"
            raise RuntimeError(msg)
        sp = query_of(request)["params"]
        is_continuation = "continuation" in json.loads(request.body or b"{}")
        if (sp, is_continuation) in self.pages:
            status, body = self.pages[sp, is_continuation]
            self._routes = [("POST", SEARCH_URL, body.encode(), status)]
        else:
            self._routes = []
        return super().send(request, *args, **kwargs)


@pytest.fixture
def search_site(japi: jAPI) -> SearchSite:
    site = SearchSite({})
    site.attach(japi)
    return site


def ids_of(result: dict[str, Any]) -> list[str]:
    return [item["id"] for item in result["items"]]


def video_ids_of(items: list[dict[str, Any]]) -> list[str]:
    return [item["id"]["videoId"] for item in items]


def titles_of(result: dict[str, Any]) -> list[str]:
    return [item["snippet"]["title"] for item in result["items"]]


# -- _safe_text ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("node", "expected"),
    [
        (None, "unknown"),
        ("plain", "plain"),
        ({"simpleText": "simple"}, "simple"),
        ({"runs": [{"text": "a"}, {"text": "b"}]}, "ab"),
        ({"runs": [{"text": "  padded  "}]}, "padded"),
        ({"runs": [{"text": "x"}, "not a run", {"nothing": 1}]}, "x"),
        ({"runs": []}, "unknown"),
        ({"runs": [{"text": "  "}]}, "unknown"),
        ({"runs": 5}, "unknown"),
        ({"other": "x"}, "unknown"),
        (42, "unknown"),
    ],
)
def test_safe_text(node: Any, expected: str):
    assert jAPI._safe_text(node) == expected


def test_safe_text_uses_the_given_default():
    assert jAPI._safe_text(None, default="n/a") == "n/a"
    assert jAPI._safe_text({"runs": []}, default="n/a") == "n/a"


# -- _extract_duration --------------------------------------------------------


def overlay(text: Any) -> dict[str, Any]:
    return {"thumbnailOverlayTimeStatusRenderer": {"text": text}}


@pytest.mark.parametrize(
    ("video", "expected"),
    [
        ({"lengthText": {"simpleText": "3:34"}}, "PT3M34S"),
        ({"lengthText": {"simpleText": "1:02:03"}}, "PT1H02M03S"),
        ({"lengthText": {"simpleText": " 3:34 "}}, "PT3M34S"),
        ({"lengthText": {"runs": [{"text": "4:15"}]}}, "PT4M15S"),
        ({"thumbnailOverlays": [overlay({"simpleText": "2:00"})]}, "PT2M00S"),
        ({"thumbnailOverlays": [overlay({"runs": [{"text": "5:01"}]})]}, "PT5M01S"),
        (
            {
                "lengthText": {"simpleText": "1:11"},
                "thumbnailOverlays": [overlay({"simpleText": "2:22"})],
            },
            "PT1M11S",
        ),
        (
            {
                "lengthText": {"simpleText": ""},
                "thumbnailOverlays": [overlay({"simpleText": "2:22"})],
            },
            "PT2M22S",
        ),
        (
            {
                "lengthText": {"simpleText": "garbage"},
                "thumbnailOverlays": [{"other": {}}, overlay({"simpleText": "2:22"})],
            },
            "PT2M22S",
        ),
        ({"thumbnailOverlays": [overlay({"simpleText": "LIVE"})]}, "PT0S"),
        ({"lengthText": {"simpleText": "Upcoming"}}, "PT0S"),
        ({"lengthText": {"simpleText": "PREMIERE"}}, "PT0S"),
        ({"thumbnailOverlays": [overlay({"runs": [{"text": "Shorts"}]})]}, "PT0S"),
        ({"lengthText": {"simpleText": "live"}}, "PT0S"),
        ({"lengthText": {"simpleText": "soon"}}, "PT0S"),
        ({"lengthText": {"runs": []}}, "PT0S"),
        ({"lengthText": {"accessibility": {}}}, "PT0S"),
        ({"thumbnailOverlays": [overlay({})]}, "PT0S"),
        ({}, "PT0S"),
    ],
)
def test_extract_duration(video: dict[str, Any], expected: str):
    assert jAPI._extract_duration(video, "abc") == expected


def test_extract_duration_says_why_a_video_has_no_duration(
    caplog: pytest.LogCaptureFixture,
):
    caplog.set_level(logging.INFO, logger="mopidy_youtube")

    jAPI._extract_duration({"lengthText": {"simpleText": "LIVE"}}, "live1")
    jAPI._extract_duration({}, "none1")

    assert "live1 marked as LIVE" in caplog.text
    assert "none1 no video-time" in caplog.text


# -- _find_yt_data ------------------------------------------------------------


DATA = {"contents": {"a": [1, 2, {"b": None}]}}


def test_find_yt_data_reads_a_recorded_page():
    data = jAPI._find_yt_data(page("watch_zoo.json"))

    assert data == load_fixture("japi/watch_zoo.json")


@pytest.mark.parametrize(
    "text",
    [
        f"<script>var ytInitialData = {json.dumps(DATA)};</script>",
        f'<script>window["ytInitialData"] = {json.dumps(DATA)};</script>',
        f"<script>ytInitialData = {json.dumps(DATA)};</script><p>x</p>",
    ],
    ids=["var", "window", "bare"],
)
def test_find_yt_data_understands_both_ways_of_embedding(text: str):
    assert jAPI._find_yt_data(text) == DATA


def test_find_yt_data_prefers_the_window_assignment():
    text = (
        'ytInitialData = {"which": "second"};\n'
        'window["ytInitialData"] = {"which": "first"};'
    )

    assert jAPI._find_yt_data(text) == {"which": "first"}


def test_find_yt_data_ignores_trailing_garbage_after_the_object():
    text = 'var ytInitialData = {"a": 1}, {"b": 2};'

    assert jAPI._find_yt_data(text) == {"a": 1}


def test_find_yt_data_raises_when_the_page_has_no_data(
    caplog: pytest.LogCaptureFixture,
):
    with pytest.raises(NoYtDataError, match="No data found"):
        jAPI._find_yt_data("<html>consent required</html>")

    assert "No data found on page" in caplog.text


def test_find_yt_data_survives_a_semicolon_brace_in_a_string():
    data = {"title": "int main() { return 0; };", "n": 1}

    assert jAPI._find_yt_data(f"var ytInitialData = {json.dumps(data)};") == data


# -- json_to_items: videos ----------------------------------------------------


def search_items() -> list[dict[str, Any]]:
    doc = load_fixture("japi/search_videos.json")
    return doc["contents"]["twoColumnSearchResultsRenderer"]["primaryContents"][
        "sectionListRenderer"
    ]["contents"][0]["itemSectionRenderer"]["contents"]


def test_json_to_items_converts_recorded_search_results():
    items = jAPI.json_to_items(search_items())

    assert video_ids_of(items) == [
        VIDEO_ID,
        "7FwDP17XPlk",
        "5SZYz7lZRRI",
        OTHER_VIDEO_ID,
    ]
    assert items[0] == {
        "id": {"kind": "youtube#video", "videoId": VIDEO_ID},
        "snippet": {
            "title": RICK_TITLE,
            "resourceId": {"videoId": VIDEO_ID},
            "thumbnails": {
                "default": {
                    "url": f"https://i.ytimg.com/vi/{VIDEO_ID}/hq720.jpg",
                    "width": 720,
                    "height": 404,
                }
            },
            "channelTitle": "Rick Astley",
            "channelId": CHANNEL_ID,
        },
        "contentDetails": {"duration": "PT3M34S"},
    }
    assert all(item["contentDetails"]["duration"].startswith("PT") for item in items)


def test_json_to_items_drops_duplicates():
    items = jAPI.json_to_items(search_items() + search_items())

    assert len(items) == 4


@pytest.mark.parametrize(
    "kind", ["videoRenderer", "compactVideoRenderer", "playlistVideoRenderer"]
)
def test_json_to_items_reads_every_kind_of_video_renderer(kind: str):
    (item,) = jAPI.json_to_items([video_renderer("vid", kind=kind)])

    assert item == {
        "id": {"kind": "youtube#video", "videoId": "vid"},
        "snippet": {
            "title": "Title vid",
            "resourceId": {"videoId": "vid"},
            "thumbnails": {
                "default": {"url": "https://i.ytimg.com/vid/l.jpg", "width": 2}
            },
            "channelTitle": "Channel vid",
            "channelId": "UC1",
        },
        "contentDetails": {"duration": "PT3M34S"},
    }


def test_json_to_items_keeps_the_order_of_the_results():
    items = jAPI.json_to_items(
        [video_renderer("b"), video_renderer("a"), video_renderer("c")]
    )

    assert video_ids_of(items) == ["b", "a", "c"]


def test_json_to_items_skips_radio_playlists_and_unknown_renderers():
    items = jAPI.json_to_items(
        [
            {"radioRenderer": {"playlistId": "RDx"}},
            {"shelfRenderer": {}},
            video_renderer("vid"),
        ]
    )

    assert video_ids_of(items) == ["vid"]


def test_json_to_items_skips_a_video_without_an_id(caplog: pytest.LogCaptureFixture):
    items = jAPI.json_to_items(
        [video_renderer("x", videoId=None), video_renderer("ok")]
    )

    assert video_ids_of(items) == ["ok"]
    assert "no videoId detected" in caplog.text


@pytest.mark.parametrize("title", ["[Private video]", "[Deleted video]"])
def test_json_to_items_skips_unavailable_playlist_entries(title: str):
    items = jAPI.json_to_items(
        [
            video_renderer("gone", title={"runs": [{"text": title}]}),
            video_renderer("ok"),
        ]
    )

    assert video_ids_of(items) == ["ok"]


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ({"simpleText": "Simple"}, "Simple"),
        ({"runs": [{"text": "From runs"}]}, "From runs"),
        (None, "unknown"),
        ({"accessibility": {}}, "unknown"),
    ],
)
def test_json_to_items_reads_the_title(title: Any, expected: str):
    (item,) = jAPI.json_to_items([video_renderer("vid", title=title)])

    assert item["snippet"]["title"] == expected


def test_json_to_items_falls_back_to_the_short_byline():
    (item,) = jAPI.json_to_items(
        [
            video_renderer(
                "vid",
                longBylineText=None,
                shortBylineText={"runs": [{"text": "Short name"}]},
            )
        ]
    )

    assert item["snippet"]["channelTitle"] == "Short name"
    assert "channelId" not in item["snippet"]


def test_json_to_items_prefers_the_long_byline():
    (item,) = jAPI.json_to_items(
        [video_renderer("vid", shortBylineText={"runs": [{"text": "Short"}]})]
    )

    assert item["snippet"]["channelTitle"] == "Channel vid"


def test_json_to_items_names_the_channel_unknown_without_a_byline(
    caplog: pytest.LogCaptureFixture,
):
    (item,) = jAPI.json_to_items([video_renderer("vid", longBylineText=None)])

    assert item["snippet"]["channelTitle"] == "unknown"
    assert "channelId" not in item["snippet"]
    assert "no byline detected" in caplog.text


def test_json_to_items_copes_with_an_unreadable_byline():
    (item,) = jAPI.json_to_items([video_renderer("vid", longBylineText={"runs": []})])

    assert item["snippet"]["channelTitle"] == "unknown"


def test_json_to_items_leaves_out_the_channel_id_when_the_byline_has_no_link():
    (item,) = jAPI.json_to_items(
        [video_renderer("vid", longBylineText={"runs": [{"text": "Plain"}]})]
    )

    assert item["snippet"]["channelTitle"] == "Plain"
    assert "channelId" not in item["snippet"]


@pytest.mark.parametrize(
    "thumbnail", [None, {}, {"thumbnails": []}, {"thumbnails": [{}]}]
)
def test_json_to_items_uses_the_default_thumbnail_when_there_is_none(thumbnail: Any):
    (item,) = jAPI.json_to_items([video_renderer("vid", thumbnail=thumbnail)])

    assert item["snippet"]["thumbnails"]["default"] == {
        "url": "https://i.ytimg.com/vi/vid/default.jpg"
    }


def test_json_to_items_picks_the_largest_thumbnail_without_its_query():
    (item,) = jAPI.json_to_items([video_renderer("vid")])

    assert item["snippet"]["thumbnails"]["default"]["url"] == (
        "https://i.ytimg.com/vid/l.jpg"
    )


def test_json_to_items_gives_a_video_without_a_duration_none():
    (item,) = jAPI.json_to_items([video_renderer("vid", lengthText=None)])

    assert item["contentDetails"] == {"duration": "PT0S"}


def test_json_to_items_unwraps_the_item_section_of_related_videos():
    items = jAPI.json_to_items(
        [
            {"compactAutoplayRenderer": {}},
            {
                "itemSectionRenderer": {
                    "contents": [
                        video_renderer("a", kind="compactVideoRenderer"),
                        video_renderer("b", kind="compactVideoRenderer"),
                    ]
                }
            },
        ]
    )

    assert video_ids_of(items) == ["a", "b"]


def test_json_to_items_only_unwraps_the_second_entry():
    assert (
        jAPI.json_to_items(
            [{"itemSectionRenderer": {"contents": [video_renderer("a")]}}]
        )
        == []
    )
    assert jAPI.json_to_items([]) == []


# -- json_to_items: playlists -------------------------------------------------


def test_json_to_items_reads_a_playlist_renderer():
    (item,) = jAPI.json_to_items([playlist_renderer("PL1")])

    assert item == {
        "id": {"kind": "youtube#playlist", "playlistId": "PL1"},
        "contentDetails": {"itemCount": 3},
        "snippet": {
            "title": "Playlist PL1",
            "thumbnails": {"default": {"url": "https://i.ytimg.com/PL1.jpg"}},
            "channelTitle": "Owner of PL1",
        },
    }


@pytest.mark.parametrize(
    "thumbnails", [None, [], [{"thumbnails": []}], [{"nothing": 1}]]
)
def test_json_to_items_skips_a_playlist_without_a_thumbnail(
    thumbnails: Any, caplog: pytest.LogCaptureFixture
):
    items = jAPI.json_to_items(
        [playlist_renderer("PL1", thumbnails=thumbnails), playlist_renderer("PL2")]
    )

    assert [item["id"]["playlistId"] for item in items] == ["PL2"]
    assert "thumbnail exception" in caplog.text


def test_json_to_items_names_the_owner_of_a_playlist_unknown_if_missing():
    (item,) = jAPI.json_to_items([playlist_renderer("PL1", longBylineText=None)])

    assert item["snippet"]["channelTitle"] == "unknown"


def test_json_to_items_reads_a_grid_playlist():
    (item,) = jAPI.json_to_items([grid_playlist_renderer("PL1")])

    assert item == {
        "id": {"kind": "youtube#playlist", "playlistId": "PL1"},
        "contentDetails": {"itemCount": 1234},
        "snippet": {
            "title": "Grid PL1",
            "thumbnails": {"default": {"url": "https://i.ytimg.com/PL1/b.jpg"}},
            "channelTitle": "unknown",
        },
    }


def test_json_to_items_reads_a_grid_playlist_with_a_custom_thumbnail():
    (item,) = jAPI.json_to_items(
        [
            grid_playlist_renderer(
                "PL1", thumbnail_kind="playlistCustomThumbnailRenderer"
            )
        ]
    )

    assert item["snippet"]["thumbnails"]["default"]["url"].endswith("PL1/b.jpg")


def test_json_to_items_keeps_a_grid_playlist_without_a_thumbnail(
    caplog: pytest.LogCaptureFixture,
):
    (item,) = jAPI.json_to_items([grid_playlist_renderer("PL1", thumbnail_kind=None)])

    assert item["snippet"]["thumbnails"] == {"default": None}
    assert "thumbnail exception" in caplog.text


@pytest.mark.parametrize(
    ("count", "expected"),
    [
        ({"simpleText": "7"}, 7),
        ({"simpleText": "12,345"}, 12345),
        ({"simpleText": "50+"}, 0),
        ({"runs": [{"text": "7"}]}, 0),
        (None, 0),
    ],
)
def test_json_to_items_reads_the_size_of_a_grid_playlist(count: Any, expected: int):
    (item,) = jAPI.json_to_items(
        [grid_playlist_renderer("PL1", videoCountShortText=count)]
    )

    assert item["contentDetails"]["itemCount"] == expected


def test_json_to_items_mixes_videos_and_playlists_in_order():
    items = jAPI.json_to_items(
        [video_renderer("v1"), playlist_renderer("PL1"), video_renderer("v2")]
    )

    assert [item["id"]["kind"] for item in items] == [
        "youtube#video",
        "youtube#playlist",
        "youtube#video",
    ]


# -- pl_run_search ------------------------------------------------------------


def test_pl_run_search_asks_the_results_page_and_converts_the_first_section(
    japi: jAPI, youtube_site: FakeYouTube
):
    youtube_site.add("GET", BASE + "results", body=page("search_videos.json"))
    params = {"search_query": "never gonna", "sp": VIDEO_SP, "app": "desktop"}

    items = japi.pl_run_search(params)

    assert video_ids_of(items) == [
        VIDEO_ID,
        "7FwDP17XPlk",
        "5SZYz7lZRRI",
        OTHER_VIDEO_ID,
    ]
    assert only_call(youtube_site, "GET", BASE + "results") == params | {"sp": VIDEO_SP}


def test_pl_run_search_only_reads_the_first_item_section(
    japi: jAPI, youtube_site: FakeYouTube
):
    doc = search_doc([video_renderer("first")])
    doc["contents"]["twoColumnSearchResultsRenderer"]["primaryContents"][
        "sectionListRenderer"
    ]["contents"].append(
        {"itemSectionRenderer": {"contents": [video_renderer("second")]}}
    )
    youtube_site.add("GET", BASE + "results", body=yt_initial_data_page(doc))

    items = japi.pl_run_search({"search_query": "q"})

    assert video_ids_of(items) == ["first"]


def test_pl_run_search_finds_the_item_section_after_other_sections(
    japi: jAPI, youtube_site: FakeYouTube
):
    doc = search_doc([video_renderer("vid")])
    sections = doc["contents"]["twoColumnSearchResultsRenderer"]["primaryContents"][
        "sectionListRenderer"
    ]["contents"]
    sections.insert(0, {"someOtherRenderer": {}})
    youtube_site.add("GET", BASE + "results", body=yt_initial_data_page(doc))

    assert video_ids_of(japi.pl_run_search({"search_query": "q"})) == ["vid"]


def test_pl_run_search_returns_nothing_for_a_failed_request(
    japi: jAPI, youtube_site: FakeYouTube
):
    youtube_site.add("GET", BASE + "results", body="oops", status=429)

    assert japi.pl_run_search({"search_query": "q"}) == []


def test_pl_run_search_returns_nothing_when_the_page_has_no_results(
    japi: jAPI, youtube_site: FakeYouTube, caplog: pytest.LogCaptureFixture
):
    youtube_site.add(
        "GET", BASE + "results", body=yt_initial_data_page({"contents": {}})
    )

    assert japi.pl_run_search({"search_query": "q"}) == []
    assert "pl_run_search parse failed" in caplog.text


def test_pl_run_search_returns_nothing_when_the_page_has_no_sections(
    japi: jAPI, youtube_site: FakeYouTube
):
    youtube_site.add("GET", BASE + "results", body=yt_initial_data_page(search_doc([])))
    doc = search_doc([])
    doc["contents"]["twoColumnSearchResultsRenderer"]["primaryContents"][
        "sectionListRenderer"
    ]["contents"] = [{"continuationItemRenderer": {}}]
    youtube_site.add(
        "GET", BASE + "results?search_query=other", body=yt_initial_data_page(doc)
    )

    assert japi.pl_run_search({"search_query": "q"}) == []
    assert japi.pl_run_search({"search_query": "other"}) == []


# -- run_search ---------------------------------------------------------------


def test_run_search_posts_the_query_to_the_search_endpoint(
    japi: jAPI, search_site: SearchSite
):
    search_site.pages = {
        (VIDEO_SP, False): search_site.ok(load_fixture("japi/search_videos.json"))
    }
    context.search_results = 1

    items = japi.run_search("never gonna give you up", VIDEO_SP)

    assert video_ids_of(items) == [
        VIDEO_ID,
        "7FwDP17XPlk",
        "5SZYz7lZRRI",
        OTHER_VIDEO_ID,
    ]
    (request,) = search_site.calls("POST", SEARCH_URL)
    query = query_of(request)
    assert query["query"] == "never gonna give you up"
    assert query["params"] == VIDEO_SP
    assert query["key"]
    assert query["contentCheckOk"] == "True"
    assert query["racyCheckOk"] == "True"
    assert json.loads(request.body) == {
        "context": {
            "client": {"clientName": "WEB", "clientVersion": "2.20200720.00.02"}
        }
    }
    assert request.headers["Content-Type"] == "application/json"
    assert request.headers["User-Agent"] == "Mozilla/5.0"


def test_run_search_follows_the_continuation_until_it_has_enough_results(
    japi: jAPI, search_site: SearchSite
):
    first = load_fixture("japi/search_videos.json")
    token = first["contents"]["twoColumnSearchResultsRenderer"]["primaryContents"][
        "sectionListRenderer"
    ]["contents"][1]["continuationItemRenderer"]["continuationEndpoint"][
        "continuationCommand"
    ]["token"]
    search_site.pages = {
        (VIDEO_SP, False): search_site.ok(first),
        (VIDEO_SP, True): search_site.ok(load_fixture("japi/search_continuation.json")),
    }
    context.search_results = 6

    items = japi.run_search("never gonna give you up", VIDEO_SP)

    assert video_ids_of(items) == [
        VIDEO_ID,
        "7FwDP17XPlk",
        "5SZYz7lZRRI",
        OTHER_VIDEO_ID,
        "5SopjSfIkL8",
        "di14EZRpMVo",
        "OU3UfgKJoCk",
    ]
    first_request, second_request = search_site.requests
    assert "continuation" not in json.loads(first_request.body)
    assert json.loads(second_request.body)["continuation"] == token


def test_run_search_stops_when_the_results_run_out(japi: jAPI, search_site: SearchSite):
    context.search_results = 50
    search_site.pages = {
        (VIDEO_SP, False): search_site.ok(
            search_doc([video_renderer("a")], continuation="TOKEN")
        ),
        (VIDEO_SP, True): search_site.ok(continuation_doc([video_renderer("b")])),
    }

    items = japi.run_search("q", VIDEO_SP)

    assert video_ids_of(items) == ["a", "b"]
    assert len(search_site.requests) == 2


def test_run_search_does_not_ask_for_more_than_the_limit(
    japi: jAPI, search_site: SearchSite
):
    context.search_results = 1
    search_site.pages = {
        (VIDEO_SP, False): search_site.ok(
            search_doc([video_renderer("a")], continuation="TOKEN")
        )
    }

    assert video_ids_of(japi.run_search("q", VIDEO_SP)) == ["a"]
    assert len(search_site.requests) == 1


def test_run_search_reads_every_item_section_of_a_page(
    japi: jAPI, search_site: SearchSite
):
    doc = search_doc([video_renderer("a")])
    sections = doc["contents"]["twoColumnSearchResultsRenderer"]["primaryContents"][
        "sectionListRenderer"
    ]["contents"]
    sections.append({"itemSectionRenderer": {"contents": [video_renderer("b")]}})
    search_site.pages = {(VIDEO_SP, False): search_site.ok(doc)}

    assert video_ids_of(japi.run_search("q", VIDEO_SP)) == ["a", "b"]


def test_run_search_keeps_what_it_has_when_a_later_page_fails(
    japi: jAPI, search_site: SearchSite
):
    context.search_results = 50
    search_site.pages = {
        (VIDEO_SP, False): search_site.ok(
            search_doc([video_renderer("a")], continuation="TOKEN")
        ),
        (VIDEO_SP, True): (503, "unavailable"),
    }

    assert video_ids_of(japi.run_search("q", VIDEO_SP)) == ["a"]


def test_run_search_returns_nothing_for_a_failed_request(
    japi: jAPI, search_site: SearchSite
):
    search_site.pages = {(VIDEO_SP, False): (403, "forbidden")}

    assert japi.run_search("q", VIDEO_SP) == []


def test_run_search_returns_nothing_for_a_response_that_is_not_json(
    japi: jAPI, search_site: SearchSite, caplog: pytest.LogCaptureFixture
):
    search_site.pages = {(VIDEO_SP, False): (200, "<html>captcha</html>")}

    assert japi.run_search("q", VIDEO_SP) == []
    assert "invalid JSON" in caplog.text


def test_run_search_returns_nothing_for_a_response_without_sections(
    japi: jAPI, search_site: SearchSite, caplog: pytest.LogCaptureFixture
):
    search_site.pages = {(VIDEO_SP, False): search_site.ok({"error": {"code": 400}})}

    assert japi.run_search("q", VIDEO_SP) == []
    assert "could not find search sections" in caplog.text
    assert len(search_site.requests) == 1


def test_run_search_gives_up_on_an_empty_response(japi: jAPI, search_site: SearchSite):
    search_site.pages = {(VIDEO_SP, False): search_site.ok({})}

    assert japi.run_search("q", VIDEO_SP) == []


# -- search -------------------------------------------------------------------


def test_search_asks_for_videos_and_playlists(japi: jAPI, search_site: SearchSite):
    search_site.pages = {
        (VIDEO_SP, False): search_site.ok(search_doc([video_renderer("v1")])),
        (PLAYLIST_SP, False): search_site.ok(search_doc([playlist_renderer("PL1")])),
    }

    result = japi.search("some music")

    assert [item["id"] for item in result["items"]] == [
        {"kind": "youtube#video", "videoId": "v1"},
        {"kind": "youtube#playlist", "playlistId": "PL1"},
    ]
    sent = sorted(query_of(request)["params"] for request in search_site.requests)
    assert sent == sorted([VIDEO_SP, PLAYLIST_SP])
    assert {query_of(request)["query"] for request in search_site.requests} == {
        "some music"
    }


def test_search_truncates_each_branch_to_the_configured_number_of_results(
    japi: jAPI, search_site: SearchSite
):
    context.search_results = 2
    search_site.pages = {
        (VIDEO_SP, False): search_site.ok(load_fixture("japi/search_videos.json")),
        (PLAYLIST_SP, False): search_site.ok(
            search_doc([playlist_renderer(f"PL{n}") for n in range(5)])
        ),
    }

    result = japi.search("some music")

    assert [
        item["id"].get("videoId") or item["id"]["playlistId"]
        for item in result["items"]
    ] == [VIDEO_ID, "7FwDP17XPlk", "PL0", "PL1"]


def test_search_uses_the_given_params(japi: jAPI, search_site: SearchSite):
    search_site.pages = {
        (VIDEO_SP, False): search_site.ok(search_doc([video_renderer("v1")]))
    }

    result = japi.search("q", params=[VIDEO_SP])

    assert [item["id"]["videoId"] for item in result["items"]] == ["v1"]
    assert len(search_site.requests) == 1


def test_search_survives_a_failing_branch(
    japi: jAPI, search_site: SearchSite, caplog: pytest.LogCaptureFixture
):
    search_site.pages = {
        (VIDEO_SP, False): search_site.ok(search_doc([video_renderer("v1")]))
    }

    result = japi.search("some music")

    assert [item["id"]["videoId"] for item in result["items"]] == ["v1"]
    assert "youtube search branch failed for query 'some music'" in caplog.text


def test_search_returns_nothing_when_every_branch_fails(
    japi: jAPI, search_site: SearchSite
):
    assert japi.search("some music") == {"items": []}


def test_search_returns_plain_json_data(japi: jAPI, search_site: SearchSite):
    search_site.pages = {
        (VIDEO_SP, False): search_site.ok(search_doc([video_renderer("v1")]))
    }

    result = japi.search("q", params=[VIDEO_SP])

    assert result == json.loads(json.dumps(result))
    assert list(result) == ["items"]


def test_search_finds_playlists_in_current_youtube_responses(
    japi: jAPI, search_site: SearchSite
):
    search_site.pages = {
        (PLAYLIST_SP, False): search_site.ok(
            load_fixture("japi/search_playlists_lockups.json")
        ),
        # the recorded page ends with a continuation token
        (PLAYLIST_SP, True): search_site.ok(continuation_doc([])),
    }

    result = japi.search("never gonna give you up", params=[PLAYLIST_SP])

    assert [item["id"]["playlistId"] for item in result["items"]] == [
        "PLl8RNOyzcwBjjIajUplE6oV8Vi5Od65H2",
        "PLd5Vfgy_sILZXNGHKlAHnwPOEhboVQNBG",
        "PLL8jFEKG82Z7vNDMUamdAcNL4JwGZ8CMG",
    ]


# -- list_related_videos ------------------------------------------------------


def test_list_related_videos_converts_the_videos_next_to_the_player(
    japi: jAPI, youtube_site: FakeYouTube
):
    youtube_site.add(
        "GET",
        BASE + "watch",
        body=yt_initial_data_page(
            related_doc(
                [
                    video_renderer("r1", kind="compactVideoRenderer"),
                    video_renderer("r2", kind="compactVideoRenderer"),
                ]
            )
        ),
    )

    result = japi.list_related_videos(VIDEO_ID)

    assert video_ids_of(result["items"]) == ["r1", "r2"]
    assert result["items"][0]["snippet"]["title"] == "Title r1"
    assert only_call(youtube_site, "GET", BASE + "watch") == {
        "v": VIDEO_ID,
        "app": "desktop",
        "persist_app": "1",
    }


@pytest.mark.parametrize("status", [404, 429, 500])
def test_list_related_videos_returns_nothing_for_a_failed_request(
    japi: jAPI, youtube_site: FakeYouTube, status: int
):
    youtube_site.add("GET", BASE + "watch", body="nope", status=status)

    assert japi.list_related_videos(VIDEO_ID) == {"items": []}


def test_list_related_videos_finds_them_on_a_current_watch_page(
    japi: jAPI, youtube_site: FakeYouTube
):
    youtube_site.add("GET", BASE + "watch", body=page("watch_zoo.json"))

    result = japi.list_related_videos(ZOO_VIDEO_ID)

    assert video_ids_of(result["items"]) == [
        "P4Ex2AafR1U",
        "Y_BCuvEcISY",
        "fu0mb3PmOoE",
    ]


# -- list_videos --------------------------------------------------------------


def test_list_videos_finds_a_video_by_searching_for_its_id(
    japi: jAPI, youtube_site: FakeYouTube
):
    youtube_site.add("GET", BASE + "results", body=page("search_videos.json"))

    result = japi.list_videos([VIDEO_ID])

    assert result == {
        "items": [
            {
                "id": VIDEO_ID,
                "snippet": {
                    "title": RICK_TITLE,
                    "resourceId": {"videoId": VIDEO_ID},
                    "thumbnails": {
                        "default": {
                            "url": f"https://i.ytimg.com/vi/{VIDEO_ID}/hq720.jpg",
                            "width": 720,
                            "height": 404,
                        }
                    },
                    "channelTitle": "Rick Astley",
                    "channelId": CHANNEL_ID,
                },
                "contentDetails": {"duration": "PT3M34S"},
            }
        ]
    }
    assert only_call(youtube_site, "GET", BASE + "results") == {
        "search_query": f'"{VIDEO_ID}"',
        "sp": VIDEO_SP,
        "app": "desktop",
        "persist_app": "1",
    }
    assert not youtube_site.calls("GET", BASE + "watch")


def test_list_videos_only_keeps_the_exact_match(japi: jAPI, youtube_site: FakeYouTube):
    youtube_site.add("GET", BASE + "results", body=page("search_videos.json"))

    result = japi.list_videos([OTHER_VIDEO_ID])

    assert ids_of(result) == [OTHER_VIDEO_ID]
    assert titles_of(result) == ["Never Gonna Give You Up (2022 Remaster)"]


def test_list_videos_ignores_playlists_among_the_search_results(
    japi: jAPI, youtube_site: FakeYouTube
):
    youtube_site.add(
        "GET",
        BASE + "results",
        body=yt_initial_data_page(
            search_doc([playlist_renderer("PL1"), video_renderer("vid")])
        ),
    )

    assert ids_of(japi.list_videos(["vid"])) == ["vid"]


def test_list_videos_looks_up_several_ids_in_the_order_given(
    japi: jAPI, youtube_site: FakeYouTube
):
    youtube_site.add("GET", BASE + "results", body=page("search_videos.json"))

    result = japi.list_videos([OTHER_VIDEO_ID, VIDEO_ID, "7FwDP17XPlk"])

    assert ids_of(result) == [OTHER_VIDEO_ID, VIDEO_ID, "7FwDP17XPlk"]
    queries = sorted(
        query_of(request)["search_query"]
        for request in youtube_site.calls("GET", BASE + "results")
    )
    assert queries == sorted(
        f'"{vid}"' for vid in [OTHER_VIDEO_ID, VIDEO_ID, "7FwDP17XPlk"]
    )


def test_list_videos_falls_back_to_the_watch_page(
    japi: jAPI, youtube_site: FakeYouTube
):
    youtube_site.add("GET", BASE + "results", body=page("search_videos.json"))
    youtube_site.add(
        "GET", BASE + f"watch?v={ZOO_VIDEO_ID}", body=page("watch_zoo.json")
    )

    result = japi.list_videos([ZOO_VIDEO_ID])

    (item,) = result["items"]
    assert item["id"] == ZOO_VIDEO_ID
    assert item["snippet"]["title"] == "Me at the zoo"
    assert item["snippet"]["channelTitle"] == "jawed"
    assert item["snippet"]["resourceId"] == {"videoId": ZOO_VIDEO_ID}
    thumbnail = item["snippet"]["thumbnails"]["default"]
    assert thumbnail["width"] == 176
    assert thumbnail["url"].endswith("s176-c-k-c0x00ffffff-no-rj")
    # the watch page has no reliable duration
    assert item["contentDetails"] == {"duration": "PT0S"}


def test_list_videos_mixes_found_and_fallback_videos(
    japi: jAPI, youtube_site: FakeYouTube
):
    youtube_site.add("GET", BASE + "results", body=page("search_videos.json"))
    youtube_site.add(
        "GET", BASE + f"watch?v={ZOO_VIDEO_ID}", body=page("watch_zoo.json")
    )
    youtube_site.add(
        "GET", BASE + f"watch?v={MISSING_VIDEO_ID}", body=page("watch_unavailable.json")
    )

    result = japi.list_videos([ZOO_VIDEO_ID, MISSING_VIDEO_ID, VIDEO_ID])

    assert ids_of(result) == [ZOO_VIDEO_ID, VIDEO_ID]


def test_list_videos_skips_an_unavailable_video(
    japi: jAPI, youtube_site: FakeYouTube, caplog: pytest.LogCaptureFixture
):
    youtube_site.add("GET", BASE + "results", body=page("search_videos.json"))
    youtube_site.add(
        "GET", BASE + f"watch?v={MISSING_VIDEO_ID}", body=page("watch_unavailable.json")
    )

    assert japi.list_videos([MISSING_VIDEO_ID]) == {"items": []}
    assert "watch fallback failed" in caplog.text


@pytest.mark.parametrize("status", [404, 500])
def test_list_videos_skips_a_video_whose_page_cannot_be_loaded(
    japi: jAPI, youtube_site: FakeYouTube, status: int
):
    youtube_site.add("GET", BASE + "results", body="nope", status=status)
    youtube_site.add("GET", BASE + "watch", body="nope", status=status)

    assert japi.list_videos([MISSING_VIDEO_ID]) == {"items": []}


def test_list_videos_fallback_copes_with_extra_renderers_on_the_watch_page(
    japi: jAPI, youtube_site: FakeYouTube
):
    youtube_site.add("GET", BASE + "results", body=yt_initial_data_page(search_doc([])))
    youtube_site.add(
        "GET", BASE + f"watch?v={VIDEO_ID}", body=page("watch_ticket_shelf.json")
    )

    result = japi.list_videos([VIDEO_ID])

    assert ids_of(result) == [VIDEO_ID]
    assert titles_of(result) == [RICK_TITLE]


# -- list_playlists -----------------------------------------------------------


def test_list_playlists_finds_a_playlist_by_searching_for_its_id(
    japi: jAPI, youtube_site: FakeYouTube
):
    youtube_site.add(
        "GET",
        BASE + "results",
        body=yt_initial_data_page(
            search_doc([playlist_renderer("PL2"), playlist_renderer("PL1")])
        ),
    )

    result = japi.list_playlists(["PL1"])

    assert result == {
        "items": [
            {
                "id": "PL1",
                "contentDetails": {"itemCount": 3},
                "snippet": {
                    "title": "Playlist PL1",
                    "thumbnails": {"default": {"url": "https://i.ytimg.com/PL1.jpg"}},
                    "channelTitle": "Owner of PL1",
                },
            }
        ]
    }
    assert only_call(youtube_site, "GET", BASE + "results") == {
        "search_query": '"PL1"',
        "sp": PLAYLIST_SP,
        "app": "desktop",
        "persist_app": "1",
    }
    assert not youtube_site.calls("GET", BASE + "playlist")


def test_list_playlists_falls_back_to_the_playlist_page(
    japi: jAPI, youtube_site: FakeYouTube
):
    youtube_site.add(
        "GET", BASE + "results", body=page("search_playlists_lockups.json")
    )
    youtube_site.add("GET", BASE + "playlist", body=page("playlist_page.json"))

    result = japi.list_playlists([PLAYLIST_ID])

    (item,) = result["items"]
    assert item["id"] == PLAYLIST_ID
    assert item["snippet"]["title"] == "Popular Music Videos"
    assert item["snippet"]["channelTitle"] == "Music"
    thumbnail = item["snippet"]["thumbnails"]["default"]
    assert thumbnail["width"] == 176
    assert thumbnail["url"].endswith("s176-c-k-c0x00ffffff-no-rj")
    assert item["contentDetails"] == {"itemCount": 182}
    assert only_call(youtube_site, "GET", BASE + "playlist") == {"list": PLAYLIST_ID}


def test_list_playlists_looks_up_several_ids_in_the_order_given(
    japi: jAPI, youtube_site: FakeYouTube
):
    youtube_site.add(
        "GET",
        BASE + "results?search_query=%22PL1%22",
        body=yt_initial_data_page(search_doc([playlist_renderer("PL1")])),
    )
    youtube_site.add(
        "GET",
        BASE + f"results?search_query=%22{PLAYLIST_ID}%22",
        body=page("search_playlists_lockups.json"),
    )
    youtube_site.add("GET", BASE + "playlist", body=page("playlist_page.json"))

    result = japi.list_playlists([PLAYLIST_ID, "PL1"])

    assert ids_of(result) == [PLAYLIST_ID, "PL1"]
    assert result["items"][0]["contentDetails"]["itemCount"] == 182
    assert result["items"][1]["contentDetails"]["itemCount"] == 3


def test_list_playlists_accepts_any_collection_of_ids(
    japi: jAPI, youtube_site: FakeYouTube
):
    youtube_site.add(
        "GET",
        BASE + "results",
        body=yt_initial_data_page(
            search_doc([playlist_renderer("PL1"), playlist_renderer("PL2")])
        ),
    )

    assert ids_of(japi.list_playlists({"PL1", "PL2"})) in (
        ["PL1", "PL2"],
        ["PL2", "PL1"],
    )
    assert ids_of(japi.list_playlists(("PL2",))) == ["PL2"]


@pytest.mark.parametrize("status", [404, 500])
def test_list_playlists_skips_a_playlist_whose_page_cannot_be_loaded(
    japi: jAPI, youtube_site: FakeYouTube, status: int
):
    youtube_site.add("GET", BASE + "results", body="nope", status=status)
    youtube_site.add("GET", BASE + "playlist", body="nope", status=status)

    assert japi.list_playlists(["PL1"]) == {"items": []}


def test_list_playlists_returns_nothing_for_a_playlist_that_does_not_exist(
    japi: jAPI, youtube_site: FakeYouTube
):
    youtube_site.add(
        "GET", BASE + "results", body=page("search_playlists_lockups.json")
    )
    youtube_site.add("GET", BASE + "playlist", body=page("playlist_unavailable.json"))

    assert japi.list_playlists(["PLzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz"]) == {"items": []}


# -- list_playlistitems -------------------------------------------------------


def test_list_playlistitems_converts_the_videos_of_the_playlist(
    japi: jAPI, youtube_site: FakeYouTube
):
    items = [video_renderer(f"v{n}", kind="playlistVideoRenderer") for n in range(5)]
    youtube_site.add(
        "GET", BASE + "playlist", body=yt_initial_data_page(playlist_doc(items))
    )

    result = japi.list_playlistitems("PL1", None, 50)

    assert list(result) == ["nextPageToken", "items"]
    assert result["nextPageToken"] is None
    assert video_ids_of(result["items"]) == [f"v{n}" for n in range(5)]
    assert result["items"][0]["snippet"]["title"] == "Title v0"
    assert only_call(youtube_site, "GET", BASE + "playlist") == {
        "list": "PL1",
        "app": "desktop",
        "persist_app": "1",
    }


@pytest.mark.parametrize(("max_results", "expected"), [(0, 0), (1, 1), (3, 3), (9, 5)])
def test_list_playlistitems_returns_at_most_max_results(
    japi: jAPI, youtube_site: FakeYouTube, max_results: int, expected: int
):
    items = [video_renderer(f"v{n}", kind="playlistVideoRenderer") for n in range(5)]
    youtube_site.add(
        "GET", BASE + "playlist", body=yt_initial_data_page(playlist_doc(items))
    )

    result = japi.list_playlistitems("PL1", None, max_results)

    assert video_ids_of(result["items"]) == [f"v{n}" for n in range(expected)]


def test_list_playlistitems_ignores_the_page_and_the_removed_videos(
    japi: jAPI, youtube_site: FakeYouTube
):
    items = [
        video_renderer("v1", kind="playlistVideoRenderer"),
        video_renderer(
            "v2",
            kind="playlistVideoRenderer",
            title={"runs": [{"text": "[Deleted video]"}]},
        ),
        video_renderer("v3", kind="playlistVideoRenderer"),
    ]
    youtube_site.add(
        "GET", BASE + "playlist", body=yt_initial_data_page(playlist_doc(items))
    )

    result = japi.list_playlistitems("PL1", "next-page-token", 50)

    assert video_ids_of(result["items"]) == ["v1", "v3"]


@pytest.mark.parametrize("status", [404, 429, 500])
def test_list_playlistitems_returns_nothing_for_a_failed_request(
    japi: jAPI, youtube_site: FakeYouTube, status: int
):
    youtube_site.add("GET", BASE + "playlist", body="nope", status=status)

    assert japi.list_playlistitems("PL1", None, 50) == {"items": []}


def test_list_playlistitems_reads_a_current_playlist_page(
    japi: jAPI, youtube_site: FakeYouTube
):
    youtube_site.add("GET", BASE + "playlist", body=page("playlist_page.json"))

    result = japi.list_playlistitems(PLAYLIST_ID, None, 50)

    assert video_ids_of(result["items"]) == [
        "fOT0BUpITw8",
        "NFvDHYMzj9U",
        "8c7KOGxeY3w",
    ]


# -- list_channelplaylists ----------------------------------------------------


def test_list_channelplaylists_converts_the_playlists_of_the_channel(
    japi: jAPI, youtube_site: FakeYouTube
):
    youtube_site.add(
        "GET",
        BASE + f"channel/{CHANNEL_ID}/playlists",
        body=yt_initial_data_page(
            channel_doc(
                [
                    grid_playlist_renderer("PL1"),
                    grid_playlist_renderer("PL2", thumbnail_kind=None),
                ]
            )
        ),
    )

    result = japi.list_channelplaylists(CHANNEL_ID)

    assert result == {
        "items": [
            {
                "id": "PL1",
                "contentDetails": {"itemCount": 1234},
                "snippet": {
                    "title": "Grid PL1",
                    "thumbnails": {"default": {"url": "https://i.ytimg.com/PL1/b.jpg"}},
                    "channelTitle": "unknown",
                },
            },
            {
                "id": "PL2",
                "contentDetails": {"itemCount": 1234},
                "snippet": {
                    "title": "Grid PL2",
                    "thumbnails": {"default": None},
                    "channelTitle": "unknown",
                },
            },
        ]
    }


def test_list_channelplaylists_finds_playlists_wherever_they_are_on_the_page(
    japi: jAPI, youtube_site: FakeYouTube
):
    doc = {"tabs": [{"deeper": {"nested": [grid_playlist_renderer("PL1")]}}]}
    youtube_site.add(
        "GET", BASE + f"channel/{CHANNEL_ID}/playlists", body=yt_initial_data_page(doc)
    )

    assert ids_of(japi.list_channelplaylists(CHANNEL_ID)) == ["PL1"]


def test_list_channelplaylists_returns_nothing_without_a_channel(
    japi: jAPI, youtube_site: FakeYouTube
):
    assert japi.list_channelplaylists(None) == {"items": []}
    assert not youtube_site.requests


def test_list_channelplaylists_returns_nothing_for_a_channel_without_playlists(
    japi: jAPI, youtube_site: FakeYouTube
):
    youtube_site.add("GET", BASE + "channel/", body=page("channel_unavailable.json"))

    assert japi.list_channelplaylists("UCzzzzzzzzzzzzzzzzzzzzzz") == {"items": []}


def test_list_channelplaylists_returns_nothing_when_a_playlist_cannot_be_read(
    japi: jAPI, youtube_site: FakeYouTube, caplog: pytest.LogCaptureFixture
):
    broken = grid_playlist_renderer("PL2", title=None)
    youtube_site.add(
        "GET",
        BASE + f"channel/{CHANNEL_ID}/playlists",
        body=yt_initial_data_page(channel_doc([grid_playlist_renderer("PL1"), broken])),
    )

    assert japi.list_channelplaylists(CHANNEL_ID) == {"items": []}
    assert "list_channelplaylists' exception" in caplog.text


def test_list_channelplaylists_reads_a_current_channel_page(
    japi: jAPI, youtube_site: FakeYouTube
):
    youtube_site.add(
        "GET",
        BASE + f"channel/{CHANNEL_ID}/playlists",
        body=page("channel_playlists_lockups.json"),
    )

    result = japi.list_channelplaylists(CHANNEL_ID)

    assert ids_of(result) == [
        "PLlaN88a7y2_qHDbY9eQbuNTAuEJUSEeuu",
        "PLlaN88a7y2_oK0nKMjZSwdU_njxUYWykm",
        "PLlaN88a7y2_pVVkl4fGdTny21_LRyT85E",
    ]
    assert titles_of(result)[0] == "Rick Astley Live at The O2"


# -- lockupViewModel ----------------------------------------------------------
#
# The current layout. The lockups below are cut out of the recorded pages.

PLAYLIST_ID_SEARCHED = "PLl8RNOyzcwBjjIajUplE6oV8Vi5Od65H2"
CHANNEL_PLAYLIST_ID = "PLlaN88a7y2_qHDbY9eQbuNTAuEJUSEeuu"
STATION_ID = "RDCLAK5uy_kmPRjHDECIcuVwnKsx2Ng7fyNgFKWNJFs"


def find_lockup(fixture: str, content_id: str) -> dict[str, Any]:
    """The `lockupViewModel` with `content_id` from a fixture (a fresh copy)."""

    def search(node: Any) -> dict[str, Any] | None:
        if isinstance(node, dict):
            if node.get("lockupViewModel", {}).get("contentId") == content_id:
                return node["lockupViewModel"]
            node = list(node.values())
        for child in node if isinstance(node, list) else []:
            if found := search(child):
                return found
        return None

    lockup = search(load_fixture(f"japi/{fixture}"))
    assert lockup, f"no lockup {content_id} in {fixture}"
    return lockup


def zoo_lockup() -> dict[str, Any]:
    return find_lockup("watch_zoo.json", "P4Ex2AafR1U")


def playlist_page_lockup() -> dict[str, Any]:
    return find_lockup("playlist_page.json", "fOT0BUpITw8")


def search_playlist_lockup() -> dict[str, Any]:
    return find_lockup("search_playlists_lockups.json", PLAYLIST_ID_SEARCHED)


def channel_playlist_lockup() -> dict[str, Any]:
    return find_lockup("channel_playlists_lockups.json", CHANNEL_PLAYLIST_ID)


def convert(*lockups: dict[str, Any]) -> list[dict[str, Any]]:
    return jAPI.json_to_items([{"lockupViewModel": lockup} for lockup in lockups])


def test_a_video_lockup_becomes_a_video_item():
    assert convert(zoo_lockup()) == [
        {
            "id": {"kind": "youtube#video", "videoId": "P4Ex2AafR1U"},
            "snippet": {
                "title": "Turn Your Screen Into a Soft Warm Light "
                "(Instant Fix For Video Lighting)",
                "resourceId": {"videoId": "P4Ex2AafR1U"},
                "thumbnails": {
                    "default": {
                        "url": "https://i.ytimg.com/vi/P4Ex2AafR1U/hqdefault.jpg",
                        "width": 336,
                        "height": 188,
                    }
                },
                "channelTitle": "Use Your Screen As Light",
            },
            "contentDetails": {"duration": "PT2H00M00S"},
        }
    ]


def test_a_video_lockup_in_a_playlist_names_its_channel():
    (item,) = convert(playlist_page_lockup())

    assert item["snippet"]["channelTitle"] == "Peso Pluma"
    assert item["snippet"]["channelId"] == "UCzrM_068Odho89mTRrrxqbA"
    assert item["contentDetails"] == {"duration": "PT3M55S"}


def test_a_video_lockup_finds_the_channel_id_in_the_avatar():
    """On a watch page only the avatar links to the channel."""
    lockup = zoo_lockup()
    lockup["metadata"]["lockupMetadataViewModel"]["image"] = {
        "decoratedAvatarViewModel": {
            "rendererContext": {
                "commandContext": {
                    "onTap": {
                        "innertubeCommand": {
                            "browseEndpoint": {"browseId": "UC-ZK_AD388lNwLicR6j4umw"}
                        }
                    }
                }
            }
        }
    }

    (item,) = convert(lockup)

    assert item["snippet"]["channelId"] == "UC-ZK_AD388lNwLicR6j4umw"


def test_a_video_lockup_without_details_still_gives_a_usable_item():
    lockup = zoo_lockup()
    del lockup["contentImage"]
    del lockup["metadata"]

    assert convert(lockup) == [
        {
            "id": {"kind": "youtube#video", "videoId": "P4Ex2AafR1U"},
            "snippet": {
                "title": "unknown",
                "resourceId": {"videoId": "P4Ex2AafR1U"},
                "thumbnails": {
                    "default": {"url": "https://i.ytimg.com/vi/P4Ex2AafR1U/default.jpg"}
                },
                "channelTitle": "unknown",
            },
            "contentDetails": {"duration": "PT0S"},
        }
    ]


@pytest.mark.parametrize("badge", ["LIVE", "UPCOMING", "Shorts"])
def test_a_video_lockup_that_is_not_a_recording_has_no_duration(badge: str):
    lockup = zoo_lockup()
    (found,) = time_badges(lockup)
    found["text"] = badge

    (item,) = convert(lockup)

    assert item["contentDetails"] == {"duration": "PT0S"}


def time_badges(lockup: dict[str, Any]) -> list[dict[str, Any]]:
    badges = lockup["contentImage"]["thumbnailViewModel"]["overlays"][0][
        "thumbnailBottomOverlayViewModel"
    ]["badges"]
    return [badge["thumbnailBadgeViewModel"] for badge in badges]


@pytest.mark.parametrize("title", ["[Private video]", "[Deleted video]"])
def test_a_video_lockup_of_a_removed_video_is_skipped(title: str):
    lockup = zoo_lockup()
    lockup["metadata"]["lockupMetadataViewModel"]["title"] = {"content": title}

    assert convert(lockup) == []


def test_lockups_without_an_id_or_of_another_kind_are_skipped():
    no_id = zoo_lockup()
    del no_id["contentId"]
    podcast = zoo_lockup()
    podcast["contentType"] = "LOCKUP_CONTENT_TYPE_PODCAST"
    station = find_lockup("channel_playlists_rich_grid.json", STATION_ID)

    assert convert(no_id, podcast, station, zoo_lockup()) == convert(zoo_lockup())


def test_a_playlist_lockup_from_a_search_names_its_owner():
    assert convert(search_playlist_lockup()) == [
        {
            "id": {"kind": "youtube#playlist", "playlistId": PLAYLIST_ID_SEARCHED},
            "contentDetails": {"itemCount": 56},
            "snippet": {
                "title": "Rick Astley - Never Gonna Give You Up",
                "thumbnails": {
                    "default": {
                        "url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hq720.jpg",
                        "width": 720,
                        "height": 404,
                    }
                },
                "channelTitle": "Seh",
                "channelId": "UCXhPrL3sla_Iaabtx5X5CAw",
            },
        }
    ]


def test_a_playlist_lockup_on_a_channel_has_no_owner_but_a_channel_id():
    (item,) = convert(channel_playlist_lockup())

    assert item["id"]["playlistId"] == CHANNEL_PLAYLIST_ID
    assert item["contentDetails"] == {"itemCount": 3}
    assert item["snippet"]["channelTitle"] == "unknown"
    assert item["snippet"]["channelId"] == "UCuAXFkgsw1L7xaCfnd5JJOw"


def test_a_playlist_lockup_without_details_still_gives_a_usable_item():
    lockup = channel_playlist_lockup()
    del lockup["contentImage"]
    del lockup["metadata"]

    assert convert(lockup) == [
        {
            "id": {"kind": "youtube#playlist", "playlistId": CHANNEL_PLAYLIST_ID},
            "contentDetails": {"itemCount": 0},
            "snippet": {
                "title": "unknown",
                "thumbnails": {},
                "channelTitle": "unknown",
            },
        }
    ]


def test_a_mix_is_not_a_playlist():
    lockup = channel_playlist_lockup()
    lockup["contentId"] = "RDdQw4w9WgXcQ"

    assert convert(lockup) == []


def test_lockups_and_renderers_can_share_a_page():
    items = jAPI.json_to_items(
        [
            video_renderer("old", kind="compactVideoRenderer"),
            {"lockupViewModel": zoo_lockup()},
            playlist_renderer("PL1"),
            {"lockupViewModel": search_playlist_lockup()},
        ]
    )

    assert [item["id"] for item in items] == [
        {"kind": "youtube#video", "videoId": "old"},
        {"kind": "youtube#video", "videoId": "P4Ex2AafR1U"},
        {"kind": "youtube#playlist", "playlistId": "PL1"},
        {"kind": "youtube#playlist", "playlistId": PLAYLIST_ID_SEARCHED},
    ]


def test_list_related_videos_leaves_out_the_playlists_among_them(
    japi: jAPI, youtube_site: FakeYouTube
):
    doc = {
        "contents": {
            "twoColumnWatchNextResults": {
                "secondaryResults": {
                    "secondaryResults": {
                        "results": [
                            {
                                "itemSectionRenderer": {
                                    "contents": [
                                        {"lockupViewModel": search_playlist_lockup()},
                                        {"lockupViewModel": zoo_lockup()},
                                    ]
                                }
                            }
                        ]
                    }
                }
            }
        }
    }
    youtube_site.add("GET", BASE + "watch", body=yt_initial_data_page(doc))

    result = japi.list_related_videos(ZOO_VIDEO_ID)

    assert video_ids_of(result["items"]) == ["P4Ex2AafR1U"]


def test_list_related_videos_returns_nothing_for_a_page_without_any(
    japi: jAPI, youtube_site: FakeYouTube
):
    youtube_site.add("GET", BASE + "watch", body=page("watch_unavailable.json"))

    assert japi.list_related_videos(ZOO_VIDEO_ID) == {"items": []}


def test_list_playlistitems_respects_max_results_on_a_current_playlist_page(
    japi: jAPI, youtube_site: FakeYouTube
):
    youtube_site.add("GET", BASE + "playlist", body=page("playlist_page.json"))

    result = japi.list_playlistitems(PLAYLIST_ID, None, 2)

    assert video_ids_of(result["items"]) == ["fOT0BUpITw8", "NFvDHYMzj9U"]
    assert result["nextPageToken"] is None


def test_list_playlistitems_returns_nothing_for_a_playlist_that_does_not_exist(
    japi: jAPI, youtube_site: FakeYouTube
):
    youtube_site.add("GET", BASE + "playlist", body=page("playlist_unavailable.json"))

    assert japi.list_playlistitems(PLAYLIST_ID, None, 50) == {"items": []}


def test_list_channelplaylists_finds_only_the_playlists_in_a_rich_grid(
    japi: jAPI, youtube_site: FakeYouTube
):
    """The channel of YouTube Music lists a mix, a video and two playlists."""
    youtube_site.add(
        "GET",
        BASE + f"channel/{CHANNEL_ID}/playlists",
        body=page("channel_playlists_rich_grid.json"),
    )

    result = japi.list_channelplaylists(CHANNEL_ID)

    assert ids_of(result) == [
        "PL4fGSI1pDJn7xvYy-bP6UFeG5tITQgScd",
        "PL4fGSI1pDJn44PMHPLYatj8rta8WYtZ8_",
    ]
    assert result["items"][0]["contentDetails"] == {"itemCount": 100}
    assert result["items"][0]["snippet"]["channelTitle"] == (
        "YouTube Music Global Charts"
    )


def test_list_playlists_ignores_videos_among_the_search_results(
    japi: jAPI, youtube_site: FakeYouTube
):
    youtube_site.add(
        "GET",
        BASE + "results",
        body=yt_initial_data_page(search_doc([video_renderer("v1")])),
    )
    youtube_site.add("GET", BASE + "playlist", body=page("playlist_unavailable.json"))

    assert japi.list_playlists(["PL1"]) == {"items": []}


def test_list_playlists_logs_the_playlist_that_does_not_exist(
    japi: jAPI, youtube_site: FakeYouTube, caplog: pytest.LogCaptureFixture
):
    youtube_site.add("GET", BASE + "results", body=yt_initial_data_page(search_doc([])))
    youtube_site.add("GET", BASE + "playlist", body=page("playlist_unavailable.json"))

    japi.list_playlists(["PL1"])

    assert "found no playlist PL1" in caplog.text


def test_list_playlists_reads_the_sidebar_of_a_current_playlist_page(
    japi: jAPI, youtube_site: FakeYouTube
):
    youtube_site.add("GET", BASE + "results", body=yt_initial_data_page(search_doc([])))
    youtube_site.add("GET", BASE + "playlist", body=page("playlist_page.json"))

    (item,) = japi.list_playlists([PLAYLIST_ID])["items"]

    assert item["id"] == PLAYLIST_ID
    assert item["snippet"]["title"] == "Popular Music Videos"
    assert item["contentDetails"] == {"itemCount": 182}


def test_find_yt_data_gives_up_on_data_that_is_not_json():
    with pytest.raises(NoYtDataError, match="No data found"):
        jAPI._find_yt_data("var ytInitialData = {not json};")
