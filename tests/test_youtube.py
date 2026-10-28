"""Characterization tests of the entity layer: `Entry`, `Video`, `Playlist`, `Channel`.

The entities are lazily loaded objects whose properties are futures, filled from
the data api in `context.api`. These tests pin what can be observed from outside:
the values the futures resolve to after a flow, and which api calls were made and
how many. They do not look at how the data gets into the entities, so that the
api clients may hand over their data in another way (today `Music` creates and
fills entities itself while it answers a request).

There are two kinds of tests:

- unit tests with `FakeApi`, a few canned Data-API-shaped answers that record
  every call, and
- integration tests with the real `Music` (the `YTMusic` class mocked with the
  recorded responses of `tests/fixtures/music`) and the real `jAPI` (served by
  `FakeYouTube` from `tests/fixtures/japi`).

Futures are always awaited with a timeout, and `settle()` waits for background
loads before the number of api calls is asserted.
"""

from __future__ import annotations

import copy
import json
import logging
import threading
from concurrent.futures import Future
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from unittest import mock
from urllib.parse import parse_qs, urlparse

import pykka
import pytest
from mopidy.models import Image

from mopidy_youtube.apis.youtube_japi import jAPI
from mopidy_youtube.apis.youtube_music import Music
from mopidy_youtube.context import context
from mopidy_youtube.youtube import Channel, Entry, Playlist, Video

from tests.support import FakeYouTube, load_fixture, yt_initial_data_page

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from concurrent.futures import Executor

    import requests

TIMEOUT = 5
# for futures that are expected never to resolve (known bugs): fail fast
SHORT_TIMEOUT = 0.5


# ---------------------------------------------------------------------------
# helpers


def got(future: pykka.ThreadingFuture[Any]) -> Any:
    """The value of a future, waiting at most `TIMEOUT` seconds for it."""
    return future.get(timeout=TIMEOUT)


def future_value(entity: Entry, field: str) -> Any:
    """The loaded value of an entity field; fails instead of starting a load."""
    return entity.__dict__["_" + field].get(timeout=0)


def drain(executor: Executor) -> None:
    """Return when everything submitted to `executor` so far has finished."""
    workers = executor._max_workers  # type: ignore[attr-defined]
    barrier = threading.Barrier(workers, timeout=TIMEOUT)
    futures: list[Future[Any]] = [executor.submit(barrier.wait) for _ in range(workers)]
    for future in futures:
        future.result(timeout=TIMEOUT)


def settle() -> None:
    """Wait for the background loads that were started (they chain in this order)."""
    drain(Playlist.get_playlist_videos_executor())
    drain(Video.get_load_executor())


@pytest.fixture(autouse=True)
def no_background_loads_leak_between_tests() -> Iterator[None]:
    """Loads run against whatever `context.api` is when they get to run."""
    settle()
    yield
    settle()


class FakeApi:
    """A `YouTubeApi` that answers with canned responses and records its calls.

    A response is a value (copied for each call, because the entities change what
    they are given), a callable that is called with the arguments of the call, or
    an exception, which is raised. Without a response an api returns no items.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.responses: dict[str, Any] = {}
        self._lock = threading.Lock()

    def respond(self, method: str, response: Any) -> None:
        self.responses[method] = response

    def calls_to(self, method: str) -> list[tuple[Any, ...]]:
        with self._lock:
            return [args for name, args in self.calls if name == method]

    def _answer(self, method: str, *args: Any) -> Any:
        with self._lock:
            self.calls.append((method, args))
        response = self.responses.get(method, {"items": []})
        if isinstance(response, BaseException):
            raise response
        if callable(response):
            return response(*args)
        return copy.deepcopy(response)

    @property
    def session(self) -> requests.Session:
        raise NotImplementedError

    def search(self, q: str) -> dict[str, Any]:
        return self._answer("search", q)

    def list_videos(self, ids: list[str]) -> dict[str, Any]:
        return self._answer("list_videos", list(ids))

    def list_playlists(self, ids: Any) -> dict[str, Any]:
        return self._answer("list_playlists", list(ids))

    def list_playlistitems(
        self, playlist_id: str, page: str | None, max_results: int
    ) -> dict[str, Any]:
        return self._answer("list_playlistitems", playlist_id, page, max_results)

    def list_channelplaylists(self, channel_id: str | None) -> dict[str, Any]:
        return self._answer("list_channelplaylists", channel_id)

    def list_related_videos(self, video_id: str) -> dict[str, Any]:
        return self._answer("list_related_videos", video_id)

    def close(self) -> None:
        pass


@pytest.fixture
def api() -> FakeApi:
    fake = FakeApi()
    context.api = fake
    return fake


def thumbnails(name: str = "x") -> dict[str, Any]:
    """The thumbnails of a Data API item: three that are kept, and one that is not."""
    sizes = {
        "default": (120, 90),
        "medium": (320, 180),
        "high": (480, 360),
        "standard": (640, 480),
    }
    return {
        quality: {"url": f"https://img/{name}/{quality}.jpg", "width": w, "height": h}
        for quality, (w, h) in sizes.items()
    }


def images(name: str = "x") -> list[Image]:
    """The `Image`s of `thumbnails(name)`."""
    return [
        Image(uri=f"https://img/{name}/{quality}.jpg", width=w, height=h)
        for quality, (w, h) in [
            ("default", (120, 90)),
            ("medium", (320, 180)),
            ("high", (480, 360)),
        ]
    ]


def video_item(
    video_id: str,
    *,
    title: str | None = None,
    channel: str | None = None,
    duration: str | None = "PT3M",
    **snippet: Any,
) -> dict[str, Any]:
    """A `youtube#video` search result (also what related videos look like)."""
    item: dict[str, Any] = {
        "id": {"kind": "youtube#video", "videoId": video_id},
        "snippet": {
            "title": title or f"Title {video_id}",
            "channelTitle": channel or f"Channel {video_id}",
            **snippet,
        },
    }
    if duration:
        item["contentDetails"] = {"duration": duration}
    return item


def playlist_item(
    playlist_id: str, *, title: str | None = None, count: int | str = 12, **snippet: Any
) -> dict[str, Any]:
    """A `youtube#playlist` search result."""
    return {
        "id": {"kind": "youtube#playlist", "playlistId": playlist_id},
        "snippet": {
            "title": title or f"Playlist {playlist_id}",
            "channelTitle": f"Owner of {playlist_id}",
            **snippet,
        },
        "contentDetails": {"itemCount": count},
    }


def listed_video(
    video_id: str,
    *,
    title: str | None = None,
    channel: str | None = None,
    duration: str = "PT3M",
    **snippet: Any,
) -> dict[str, Any]:
    """An item of `list_videos`: its id is a plain string."""
    return {
        "id": video_id,
        "snippet": {
            "title": title or f"Listed {video_id}",
            "channelTitle": channel or f"Listed channel {video_id}",
            **snippet,
        },
        "contentDetails": {"duration": duration},
    }


def listed_playlist(
    playlist_id: str,
    *,
    title: str | None = None,
    count: int | str = 12,
    channel: str | None = None,
) -> dict[str, Any]:
    """An item of `list_playlists`."""
    return {
        "id": playlist_id,
        "snippet": {
            "title": title or f"Listed {playlist_id}",
            "channelTitle": channel or f"Listed owner of {playlist_id}",
            "thumbnails": thumbnails(playlist_id),
        },
        "contentDetails": {"itemCount": count},
    }


def channel_playlist(
    playlist_id: str, *, title: str | None = None, count: int | str = 7
) -> dict[str, Any]:
    """An item of `list_channelplaylists`: the Data API names no owner."""
    return {
        "id": playlist_id,
        "snippet": {"title": title or f"Channel playlist {playlist_id}"},
        "contentDetails": {"itemCount": count},
    }


def playlist_entry(
    video_id: str | None, title: str | None = None, owner: str | None = None
) -> dict[str, Any]:
    """An item of `list_playlistitems`."""
    return {
        "snippet": {
            "title": title or f"Entry {video_id}",
            "videoOwnerChannelTitle": owner or f"Owner {video_id}",
            "resourceId": {"videoId": video_id},
        }
    }


def serve_videos(api: FakeApi, *items: dict[str, Any]) -> None:
    """Make `list_videos` answer with those of `items` that were asked for."""
    by_id = {item["id"]: item for item in items}
    api.respond(
        "list_videos",
        lambda ids: {"items": [copy.deepcopy(by_id[i]) for i in ids if i in by_id]},
    )


def serve_playlists(api: FakeApi, *items: dict[str, Any]) -> None:
    by_id = {item["id"]: item for item in items}
    api.respond(
        "list_playlists",
        lambda ids: {"items": [copy.deepcopy(by_id[i]) for i in ids if i in by_id]},
    )


def serve_pages(api: FakeApi, pages: dict[str, dict[str, Any]]) -> None:
    """Make `list_playlistitems` answer with the page that was asked for."""
    api.respond(
        "list_playlistitems",
        lambda playlist_id, page, max_results: copy.deepcopy(pages[page]),
    )


def page_of(*video_ids: str | None, then: str | None = None) -> dict[str, Any]:
    page: dict[str, Any] = {"items": [playlist_entry(i) for i in video_ids]}
    if then:
        page["nextPageToken"] = then
    return page


def ids_of(entities: list[Any]) -> list[str]:
    return [entity.id for entity in entities]


# ---------------------------------------------------------------------------
# Entry.get


def test_get_returns_the_same_entity_for_the_same_class_and_id():
    assert Video.get("abc") is Video.get("abc")
    assert Video.get("abc") is not Video.get("other")
    assert Video.get("abc").id == "abc"


def test_get_keeps_the_entities_of_different_classes_apart():
    assert Playlist.get("abc") is not Video.get("abc")
    assert isinstance(Playlist.get("abc"), Playlist)


def test_a_new_entity_has_loaded_nothing(api: FakeApi):
    Video.get("abc")
    Playlist.get("abc")

    assert api.calls == []


def test_entry_cannot_load_info_itself():
    with pytest.raises(NotImplementedError):
        Entry.load_info([])


def test_only_videos_are_videos():
    assert Video.get("abc").is_video is True
    assert Playlist.get("abc").is_video is False


# ---------------------------------------------------------------------------
# Entry.search


@pytest.mark.parametrize("query", [None, "", "   ", "\t\n"])
def test_an_empty_search_finds_nothing_and_asks_nobody(api: FakeApi, query: str | None):
    assert Entry.search(query) == []

    assert api.calls == []


def test_the_query_is_stripped(api: FakeApi):
    Entry.search("  never gonna  ")

    assert api.calls_to("search") == [("never gonna",)]


def test_search_makes_videos_and_playlists_from_the_results_in_order(api: FakeApi):
    api.respond(
        "search",
        {
            "items": [
                video_item("v1", title="First", channel="One"),
                playlist_item("PL1", title="Second", count=3),
                video_item("v2", title="Third", channel="Two"),
            ]
        },
    )

    results = Entry.search("q")

    assert [type(r) for r in results] == [Video, Playlist, Video]
    assert ids_of(results) == ["v1", "PL1", "v2"]
    assert [got(r.title) for r in results] == ["First", "Second", "Third"]
    assert [got(r.channel) for r in results] == ["One", "Owner of PL1", "Two"]
    assert got(results[1].video_count) == 3
    assert got(results[0].length) == 180
    # one search call is all it takes: the results come with their details
    settle()
    assert api.calls == [("search", ("q",))]


def test_search_results_are_the_cached_entities(api: FakeApi):
    api.respond("search", {"items": [video_item("v1"), playlist_item("PL1")]})

    video, playlist = Entry.search("q")

    assert video is Video.get("v1")
    assert playlist is Playlist.get("PL1")


def test_search_results_without_items_find_nothing(api: FakeApi):
    api.respond("search", {})

    assert Entry.search("q") == []


@pytest.mark.parametrize(
    "response",
    [
        {"error": {"code": 403, "message": "quota"}},
        RuntimeError("no network"),
    ],
    ids=["error-dict", "raises"],
)
def test_a_failing_search_finds_nothing_and_does_not_block_the_next_one(
    api: FakeApi, response: Any, caplog: pytest.LogCaptureFixture
):
    api.respond("search", response)

    with caplog.at_level(logging.ERROR, logger="mopidy_youtube"):
        assert Entry.search("q") == []

    assert "youtube search error" in caplog.text
    api.respond("search", {"items": [video_item("v1")]})
    assert ids_of(Entry.search("q")) == ["v1"]


def test_a_search_is_skipped_while_another_one_is_running(api: FakeApi):
    started, release = threading.Event(), threading.Event()

    def slow_search(q: str) -> dict[str, Any]:
        started.set()
        release.wait(TIMEOUT)
        return {"items": [video_item("v1")]}

    api.respond("search", slow_search)
    first: list[Any] = []
    thread = threading.Thread(target=lambda: first.extend(Entry.search("one")))
    thread.start()
    try:
        assert started.wait(TIMEOUT)

        assert Entry.search("two") == []
    finally:
        release.set()
        thread.join(TIMEOUT)

    assert ids_of(first) == ["v1"]
    assert api.calls_to("search") == [("one",)]
    # the slot is free again
    assert ids_of(Entry.search("three")) == ["v1"]
    assert api.calls_to("search") == [("one",), ("three",)]


def test_results_that_cannot_be_made_into_entities_are_skipped(
    api: FakeApi, caplog: pytest.LogCaptureFixture
):
    unreadable = {"id": {"kind": "youtube#video", "videoId": "broken"}, "snippet": {}}
    api.respond(
        "search",
        {
            "items": [
                video_item("v1"),
                unreadable,
                None,
                {"id": {"kind": "youtube#channel", "channelId": "UC1"}},
                video_item("v2"),
            ]
        },
    )

    with caplog.at_level(logging.ERROR, logger="mopidy_youtube"):
        results = Entry.search("q")

    assert ids_of(results) == ["v1", "v2"]
    assert "map error while processing item" in caplog.text


# ---------------------------------------------------------------------------
# Entry.create_object


@pytest.mark.parametrize(
    "item",
    [
        None,
        {},
        {"id": "just-a-string", "snippet": {}},
        {"snippet": {"title": "no id"}},
        {"id": {"kind": "youtube#channel", "channelId": "UC1"}},
        {"id": {"kind": "youtube#video"}},
        {"id": {"kind": "youtube#video", "videoId": ""}},
        {"id": {"kind": "youtube#playlist"}},
        {"id": {"kind": "youtube#playlist", "playlistId": None}},
        {"id": {"videoId": "v1"}},
    ],
    ids=[
        "none",
        "empty",
        "id-not-a-dict",
        "no-id",
        "channel",
        "no-video-id",
        "empty-video-id",
        "no-playlist-id",
        "null-playlist-id",
        "no-kind",
    ],
)
def test_create_object_ignores_what_it_does_not_understand(item: Any):
    assert Entry.create_object(item) is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"is_live": True},
        {"live_status": "is_live"},
        {"live_status": "is_upcoming"},
        {"live_status": "post_live"},
        {
            "snippet": {
                "title": "t",
                "channelTitle": "c",
                "liveBroadcastContent": "live",
            }
        },
        {
            "snippet": {
                "title": "t",
                "channelTitle": "c",
                "liveBroadcastContent": "upcoming",
            }
        },
    ],
    ids=[
        "is-live",
        "live",
        "upcoming",
        "post-live",
        "broadcast-live",
        "broadcast-soon",
    ],
)
def test_create_object_skips_live_and_upcoming_videos(overrides: dict[str, Any]):
    item = {**video_item("v1", duration=None), **overrides}

    assert Entry.create_object(item) is None
    assert Video.get("v1").__dict__.get("_title") is None


def test_create_object_keeps_a_finished_broadcast():
    item = video_item("v1", duration="PT0S", liveBroadcastContent="none")

    assert ids_of([Entry.create_object(item)]) == ["v1"]


def test_create_object_makes_a_video_with_everything_the_item_tells(api: FakeApi):
    item = video_item(
        "v1",
        title="A song",
        channel="A band",
        channelId="UC1",
        thumbnails=thumbnails("v1"),
        duration="PT1H2M3S",
    )

    video = Entry.create_object(item)

    assert isinstance(video, Video)
    assert video is Video.get("v1")
    assert got(video.title) == "A song"
    assert got(video.channel) == "A band"
    assert got(video.channelId) == "UC1"
    assert got(video.length) == 3723
    assert got(video.thumbnails) == images("v1")
    assert got(video.artists) == [{"name": "A band (Channel)", "uri": "yt:channel:UC1"}]
    assert got(video.album) == {"name": "YouTube Playlist", "uri": None}
    assert api.calls == []


def test_create_object_takes_album_artists_and_track_number_from_the_item(
    api: FakeApi,
):
    album = {"name": "An album", "uri": "yt:playlist:MPREb_1"}
    artists = [{"name": "Singer", "uri": "yt:channel:UC9"}]
    item = {**video_item("v1", channelId="UC1"), "album": album, "artists": artists}
    item["track_no"] = 4

    video = Entry.create_object(item)

    assert got(video.album) == album
    assert got(video.artists) == artists
    assert got(video.track_no) == 4
    assert api.calls == []


def test_create_object_makes_a_playlist(api: FakeApi):
    playlist = Entry.create_object(
        playlist_item("PL1", title="Mix", count=8, thumbnails=thumbnails("PL1"))
    )

    assert isinstance(playlist, Playlist)
    assert playlist is Playlist.get("PL1")
    assert got(playlist.title) == "Mix"
    assert got(playlist.channel) == "Owner of PL1"
    assert got(playlist.video_count) == 8
    assert got(playlist.thumbnails) == images("PL1")
    assert api.calls == []


def test_create_object_without_a_channel_calls_it_unknown(api: FakeApi):
    item = {
        "id": {"kind": "youtube#video", "videoId": "v1"},
        "snippet": {"title": "No channel"},
        "contentDetails": {"duration": "PT1M"},
    }

    video = Entry.create_object(item)

    assert got(video.channel) == "unknown"
    assert got(video.title) == "No channel"


# ---------------------------------------------------------------------------
# Entry.extend_fields


def test_extend_fields_without_an_item_is_just_the_fields():
    item, fields = Entry.extend_fields(None, ["title", "channel", "title"])

    assert item is None
    assert sorted(fields) == ["channel", "title"]


@pytest.mark.parametrize(
    ("fields", "item", "expected"),
    [
        (["title"], {"snippet": {"channelTitle": "c"}}, {"title", "channel"}),
        (
            ["title"],
            {"snippet": {"videoOwnerChannelTitle": "o"}},
            {"title", "owner_channel"},
        ),
        (
            ["title"],
            {"snippet": {"videoOwnerChannelTitle": "o", "channelTitle": "c"}},
            {"title", "owner_channel"},
        ),
        (
            ["title"],
            {"snippet": {"channelTitle": "c", "channelId": "UC1"}},
            {"title", "channel", "channelId", "artists"},
        ),
        (
            ["title"],
            {"snippet": {"channelTitle": "c", "thumbnails": {}}},
            {"title", "channel", "thumbnails"},
        ),
        (
            ["title"],
            {"snippet": {"channelTitle": "c"}, "artists": []},
            {"title", "channel", "artists"},
        ),
        (
            ["title"],
            {"snippet": {"channelTitle": "c"}, "album": None},
            {"title", "channel", "album"},
        ),
        (
            ["title"],
            {"snippet": {"channelTitle": "c"}, "track_no": None},
            {"title", "channel", "track_no"},
        ),
        (
            ["title"],
            {"snippet": {"channelTitle": "c"}, "contentDetails": {"duration": "PT1S"}},
            {"title", "channel", "length"},
        ),
        (
            ["title"],
            {"snippet": {"channelTitle": "c"}, "contentDetails": {"itemCount": 3}},
            {"title", "channel", "video_count"},
        ),
        (
            ["title"],
            {
                "snippet": {"channelTitle": "c"},
                "contentDetails": {"duration": "PT1S", "itemCount": 3},
            },
            {"title", "channel", "length"},
        ),
        (
            ["title"],
            {"snippet": {"channelTitle": "c"}, "contentDetails": "not a dict"},
            {"title", "channel"},
        ),
        (["title"], {"snippet": {}}, {"title"}),
        (["title"], {"snippet": "not a dict"}, {"title"}),
        (["title"], {}, {"title"}),
        (
            ["title", "length", "channel"],
            {"snippet": {"videoOwnerChannelTitle": "o"}},
            {"title", "length", "channel", "owner_channel"},
        ),
    ],
    ids=[
        "channel",
        "owner-channel",
        "owner-channel-wins",
        "channel-id-makes-artists",
        "thumbnails",
        "artists",
        "album",
        "track-no",
        "length",
        "video-count",
        "length-wins",
        "details-not-a-dict",
        "empty-snippet",
        "snippet-not-a-dict",
        "no-snippet",
        "asked-for-fields-stay",
    ],
)
def test_extend_fields_adds_the_fields_an_item_can_fill(
    fields: list[str], item: dict[str, Any], expected: set[str]
):
    _, extended = Entry.extend_fields(item, fields)

    assert set(extended) == expected


def test_extend_fields_makes_artists_of_the_channel():
    item, _ = Entry.extend_fields(
        {"snippet": {"channelTitle": "A band", "channelId": "UC1"}}, ["title"]
    )

    assert item["artists"] == [{"name": "A band (Channel)", "uri": "yt:channel:UC1"}]


def test_extend_fields_keeps_the_artists_an_item_has():
    artists = [{"name": "Singer", "uri": None}]

    item, _ = Entry.extend_fields(
        {"snippet": {"channelTitle": "c", "channelId": "UC1"}, "artists": artists},
        ["title"],
    )

    assert item["artists"] == artists


def test_extend_fields_names_a_missing_channel_unknown(
    caplog: pytest.LogCaptureFixture,
):
    item, fields = Entry.extend_fields({"snippet": {"title": "t"}}, ["title"])

    assert item["snippet"]["channelTitle"] == "unknown"
    assert "artists" not in item
    assert "channel" not in fields
    assert "no channel or owner_channel" in caplog.text


# ---------------------------------------------------------------------------
# Entry._set_api_data


@pytest.mark.parametrize(
    ("field", "item", "expected"),
    [
        ("title", {"snippet": {"title": "T"}}, "T"),
        ("channel", {"snippet": {"channelTitle": "C"}}, "C"),
        ("owner_channel", {"snippet": {"videoOwnerChannelTitle": "O"}}, "O"),
        ("channelId", {"snippet": {"channelId": "UC1"}}, "UC1"),
        ("album", {"album": {"name": "A", "uri": "u"}}, {"name": "A", "uri": "u"}),
        ("artists", {"artists": [{"name": "X"}]}, [{"name": "X"}]),
        ("length", {"contentDetails": {"duration": "PT1H2M3S"}}, 3723),
        ("length", {"contentDetails": {"duration": "PT45S"}}, 45),
        ("length", {"contentDetails": {"duration": "PT0S"}}, 0),
        ("length", {"contentDetails": {"duration": "P1DT1M"}}, 86460),
        ("track_no", {"track_no": 3}, 3),
        ("track_no", {"track_no": None}, None),
    ],
)
def test_set_api_data_takes_each_field_from_its_own_key(
    field: str, item: dict[str, Any], expected: Any
):
    video = Video.get("v1")

    video._set_api_data([field], item)

    assert future_value(video, field) == expected


@pytest.mark.parametrize(
    ("count", "expected"), [(12, 12), ("12", 12), (0, 0), (50, 50), (51, 50), (900, 50)]
)
def test_the_video_count_is_capped_by_the_playlist_maximum(count: Any, expected: int):
    playlist = Playlist.get("PL1")

    playlist._set_api_data(["video_count"], {"contentDetails": {"itemCount": count}})

    assert future_value(playlist, "video_count") == expected


def test_the_video_count_follows_the_configured_maximum():
    context.playlist_max_videos = 7
    playlist = Playlist.get("PL1")

    playlist._set_api_data(["video_count"], {"contentDetails": {"itemCount": 40}})

    assert future_value(playlist, "video_count") == 7


def test_only_the_default_medium_and_high_thumbnails_are_kept():
    video = Video.get("v1")

    video._set_api_data(["thumbnails"], {"snippet": {"thumbnails": thumbnails("v1")}})

    assert future_value(video, "thumbnails") == images("v1")


def test_without_a_usable_thumbnail_there_are_none():
    video = Video.get("v1")
    only_large = {"maxres": {"url": "u", "width": 1, "height": 1}}

    video._set_api_data(["thumbnails"], {"snippet": {"thumbnails": only_large}})

    assert future_value(video, "thumbnails") is None


def test_with_no_item_every_field_resolves_to_nothing():
    video = Video.get("v1")
    fields = ["title", "channel", "length", "thumbnails", "album", "artists"]

    video._set_api_data(fields, None)

    assert [future_value(video, field) for field in fields] == [None] * 6


def test_a_field_that_is_already_set_keeps_its_value():
    video = Video.get("v1")
    video._set_api_data(["title"], {"snippet": {"title": "first"}})

    video._set_api_data(["title"], {"snippet": {"title": "second"}})

    assert future_value(video, "title") == "first"
    assert got(video.title) == "first"


def test_a_field_nobody_knows_is_left_alone():
    video = Video.get("v1")

    video._set_api_data(["bogus"], {"bogus": 1})

    with pytest.raises(pykka.Timeout):
        video.__dict__["_bogus"].get(timeout=0)


# ---------------------------------------------------------------------------
# Entry._add_futures


def test_add_futures_returns_the_entities_that_need_loading_and_makes_futures():
    new = Video.get("new")

    needing = Entry._add_futures([new], ["title", "length"])

    assert needing == [new]
    assert set(new.__dict__) >= {"_title", "_length"}  # the futures exist from now on


def test_add_futures_skips_entities_that_have_everything():
    done = Video.get("done")
    done._set_api_data(["title", "length"], listed_video("done"))

    assert Entry._add_futures([done], ["title", "length"]) == []


def test_add_futures_returns_an_entity_missing_any_one_of_the_fields():
    partial = Video.get("partial")
    partial._set_api_data(["title"], listed_video("partial"))

    assert Entry._add_futures([partial], ["title", "length"]) == [partial]


def test_add_futures_still_wants_an_entity_whose_future_is_pending():
    pending = Video.get("pending")

    first = Entry._add_futures([pending], ["title"])
    second = Entry._add_futures([pending], ["title"])

    assert first == [pending]
    assert second == [pending]


def test_add_futures_ignores_missing_entities_and_keeps_the_order():
    a, b = Video.get("a"), Video.get("b")

    assert Entry._add_futures([a, None, b], ["title"]) == [a, b]


# ---------------------------------------------------------------------------
# Video.load_info


def test_a_video_loads_title_length_and_channel_with_one_api_call(api: FakeApi):
    serve_videos(api, listed_video("v1", title="T", channel="C", duration="PT2M5S"))
    video = Video.get("v1")

    assert got(video.title) == "T"
    assert got(video.length) == 125
    assert got(video.channel) == "C"

    settle()
    assert api.calls_to("list_videos") == [(["v1"],)]


def test_loading_starts_with_the_first_property_that_is_asked_for(api: FakeApi):
    serve_videos(api, listed_video("v1"))

    assert api.calls == []
    video = Video.get("v1")
    assert api.calls == []
    assert got(video.length) == 180
    assert api.calls_to("list_videos") == [(["v1"],)]


def test_load_info_asks_for_the_videos_in_batches_of_fifty(api: FakeApi):
    ids = [f"v{n:03}" for n in range(120)]
    serve_videos(api, *(listed_video(i) for i in ids))
    videos = [Video.get(i) for i in ids]

    Video.load_info(videos)

    assert [got(v.title) for v in videos] == [f"Listed {i}" for i in ids]
    assert sorted(args[0] for args in api.calls_to("list_videos")) == sorted(
        [ids[:50], ids[50:100], ids[100:]]
    )


def test_load_info_does_not_ask_again_for_videos_that_are_loaded(api: FakeApi):
    serve_videos(api, listed_video("v1"), listed_video("v2"))
    first, second = Video.get("v1"), Video.get("v2")
    got(first.title)

    Video.load_info([first, second])

    assert got(second.title) == "Listed v2"
    settle()
    assert api.calls_to("list_videos") == [(["v1"],), (["v2"],)]


def test_load_info_of_videos_that_are_all_loaded_asks_nobody(api: FakeApi):
    serve_videos(api, listed_video("v1"))
    video = Video.get("v1")
    got(video.title)

    Video.load_info([video])
    Video.load_info([])

    settle()
    assert len(api.calls_to("list_videos")) == 1


@pytest.mark.parametrize(
    "response",
    [
        RuntimeError("no network"),
        {"error": {"code": 403}},
        {"items": []},
    ],
    ids=["raises", "error-dict", "not-found"],
)
def test_a_video_the_api_cannot_describe_still_resolves(
    api: FakeApi, response: Any, caplog: pytest.LogCaptureFixture
):
    api.respond("list_videos", response)
    video = Video.get("v1")

    with caplog.at_level(logging.ERROR, logger="mopidy_youtube"):
        values = [got(video.title), got(video.length), got(video.channel)]

    assert values == [None, None, None]


def test_the_other_videos_of_a_batch_survive_one_the_api_does_not_know(api: FakeApi):
    serve_videos(
        api, listed_video("v1", title="One"), listed_video("v3", title="Three")
    )
    videos = [Video.get(i) for i in ["v1", "v2", "v3"]]

    Video.load_info(videos)

    assert [got(v.title) for v in videos] == ["One", None, "Three"]


def test_a_video_that_cannot_be_read_gets_placeholder_values(
    api: FakeApi, caplog: pytest.LogCaptureFixture
):
    unreadable = {"id": "v2", "snippet": {}}
    serve_videos(api, listed_video("v1", title="Fine"), unreadable)
    fine, broken = Video.get("v1"), Video.get("v2")

    with caplog.at_level(logging.WARNING, logger="mopidy_youtube"):
        Video.load_info([fine, broken])
        assert got(fine.title) == "Fine"
        assert got(broken.title) == "Video unplayable"
        assert got(broken.length) == 0
        assert got(broken.channel) in {"Video unplayable", "unknown"}

    assert "probably private or deleted" in caplog.text


def test_a_loaded_video_gets_the_thumbnails_of_the_listing(api: FakeApi):
    serve_videos(api, listed_video("v1", thumbnails=thumbnails("v1")))
    video = Video.get("v1")
    got(video.title)

    assert got(video.thumbnails) == images("v1")


def test_a_loaded_video_gets_artists_from_the_channel_of_the_listing(api: FakeApi):
    serve_videos(
        api, listed_video("v1", channel="A band", channelId="UC1"), listed_video("v2")
    )
    with_id, without_id = Video.get("v1"), Video.get("v2")
    got(with_id.title)
    got(without_id.title)

    assert got(with_id.artists) == [
        {"name": "A band (Channel)", "uri": "yt:channel:UC1"}
    ]
    assert got(without_id.artists) == [
        {"name": "Listed channel v2", "uri": None, "thumbnail": None}
    ]
    assert len(api.calls_to("list_videos")) == 2


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Video.artists sets its future with .set() instead of set_once(): asked "
        "before the video is loaded, the load fills the artists first (the Data "
        "API listing has a channelId) and the property raises queue.Full"
    ),
)
def test_artists_asked_before_the_video_is_loaded_come_from_the_listing(api: FakeApi):
    serve_videos(api, listed_video("v1", channel="A band", channelId="UC1"))

    artists = got(Video.get("v1").artists)

    assert artists[0]["name"].startswith("A band")


def test_the_channel_id_of_a_listing(api: FakeApi):
    serve_videos(api, listed_video("v1", channelId="UC1"))

    assert got(Video.get("v1").channelId) == "UC1"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Entry.channelId future never resolves when the api item has no channelId: "
        "load_info only fills the fields extend_fields finds in the item"
    ),
)
def test_the_channel_id_resolves_even_when_the_listing_has_none(api: FakeApi):
    serve_videos(api, listed_video("v1"))

    assert Video.get("v1").channelId.get(timeout=SHORT_TIMEOUT) is None


# ---------------------------------------------------------------------------
# Video.thumbnails, album, artists, track_no


def test_a_video_without_thumbnails_shows_the_maximum_resolution_image(api: FakeApi):
    video = Video.get("v1")

    assert got(video.thumbnails) == [
        Image(uri="https://i.ytimg.com/vi_webp/v1/maxresdefault.webp")
    ]
    assert api.calls == []


def test_the_thumbnail_of_a_prefixed_id_uses_the_last_part(api: FakeApi):
    video = Video.get("yt:video:v1")

    assert got(video.thumbnails)[0].uri == (
        "https://i.ytimg.com/vi_webp/v1/maxresdefault.webp"
    )


def test_thumbnails_asked_before_the_listing_stay_the_default_image(api: FakeApi):
    serve_videos(api, listed_video("v1", thumbnails=thumbnails("v1")))
    video = Video.get("v1")
    default = got(video.thumbnails)

    assert got(video.title) == "Listed v1"

    assert got(video.thumbnails) == default
    assert default[0].uri.endswith("maxresdefault.webp")


def test_a_video_without_an_album_is_in_a_youtube_playlist(api: FakeApi):
    assert got(Video.get("v1").album) == {"name": "YouTube Playlist", "uri": None}
    assert api.calls == []


def test_a_video_without_an_album_has_no_track_number(api: FakeApi):
    assert got(Video.get("v1").track_no) is None
    assert api.calls == []


def album_video(video_id: str, album_uri: str) -> Video:
    """A video whose search result says which album it is on."""
    item = video_item(video_id)
    item["album"] = {"name": "An album", "uri": album_uri}
    video = Entry.create_object(item)
    assert isinstance(video, Video)
    return video


@pytest.mark.parametrize(
    "album_uri",
    [
        "yt:playlist:PLalbum",
        "youtube:playlist:PLalbum",
        "https://www.youtube.com/playlist?list=PLalbum",
    ],
)
def test_the_track_number_is_the_position_in_the_playlist_of_the_album(
    api: FakeApi, album_uri: str
):
    api.respond(
        "list_playlistitems",
        {
            "items": [
                {"id": {"kind": "youtube#video", "videoId": "first"}},
                {"id": {"kind": "youtube#video", "videoId": "second"}},
                {"id": {"kind": "youtube#video", "videoId": "third"}},
            ]
        },
    )

    video = album_video("second", album_uri)

    assert got(video.track_no) == 1
    assert api.calls_to("list_playlistitems") == [("PLalbum", "", 50)]


@pytest.mark.parametrize(
    "items",
    [
        [{"id": "first"}, {"id": "second"}, {"id": "third"}],
        [
            {"snippet": {"resourceId": {"videoId": "first"}}},
            {"snippet": {"resourceId": {"videoId": "second"}}},
            {"snippet": {"resourceId": {"videoId": "third"}}},
        ],
        [
            {"id": {"kind": "youtube#video", "videoId": "first"}},
            {"id": {"kind": "youtube#channel"}},
            {"id": ""},
            {"id": {"kind": "youtube#video", "videoId": "second"}},
        ],
    ],
    ids=["string-ids", "resource-ids", "ids-without-video-ids-are-skipped"],
)
def test_the_track_number_is_found_in_every_shape_of_playlist_items(
    api: FakeApi, items: list[dict[str, Any]]
):
    api.respond("list_playlistitems", {"items": items})

    assert got(album_video("second", "yt:playlist:PLalbum").track_no) == 1


@pytest.mark.parametrize(
    "response",
    [
        {"items": [{"id": "first"}, {"id": "third"}]},
        {"items": []},
        {"error": {"code": 404}},
    ],
    ids=["not-in-the-album", "empty", "error-dict"],
)
def test_a_video_that_is_not_in_its_album_has_no_track_number(
    api: FakeApi, response: dict[str, Any]
):
    api.respond("list_playlistitems", response)

    assert got(album_video("second", "yt:playlist:PLalbum").track_no) is None


def test_the_track_number_of_a_video_whose_album_is_no_playlist_is_none(api: FakeApi):
    video = album_video("v1", "https://example.com/not-youtube")

    assert got(video.track_no) is None
    assert api.calls == []


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Video.track_no and Video.related_videos run their api call inside the "
        "property: when it raises, the error escapes and the future never resolves"
    ),
)
@pytest.mark.parametrize("loader", ["track_no", "related_videos"])
def test_an_api_that_raises_does_not_leave_a_future_unresolved(
    api: FakeApi, loader: str
):
    api.respond("list_playlistitems", RuntimeError("no network"))
    api.respond("list_related_videos", RuntimeError("no network"))
    video = album_video("v1", "yt:playlist:PLalbum")

    try:
        future = getattr(video, loader)
    except RuntimeError:
        future = video.__dict__["_" + loader]

    future.get(timeout=SHORT_TIMEOUT)


# ---------------------------------------------------------------------------
# Video.related_videos


def test_related_videos_are_videos_that_know_their_title_and_channel(api: FakeApi):
    api.respond(
        "list_related_videos",
        {
            "items": [
                video_item("r1", title="First", channel="One", duration=None),
                video_item("r2", title="Second", channel="Two", duration=None),
            ]
        },
    )
    serve_videos(api, listed_video("r1", duration="PT1M"), listed_video("r2"))

    related = got(Video.get("v0").related_videos)

    assert [type(r) for r in related] == [Video, Video]
    assert related[0] is Video.get("r1")
    assert [got(r.title) for r in related] == ["First", "Second"]
    assert [got(r.channel) for r in related] == ["One", "Two"]
    assert [got(r.length) for r in related] == [60, 180]
    assert api.calls_to("list_related_videos") == [("v0",)]


def test_the_length_of_related_videos_comes_in_one_further_api_call(api: FakeApi):
    api.respond(
        "list_related_videos",
        {"items": [video_item(f"r{n}", duration=None) for n in range(3)]},
    )
    serve_videos(api, *(listed_video(f"r{n}") for n in range(3)))

    related = got(Video.get("v0").related_videos)
    for video in related:
        got(video.length)

    settle()
    assert api.calls_to("list_videos") == [(["r0", "r1", "r2"],)]


def test_related_videos_that_come_with_a_length_need_no_further_api_call(
    api: FakeApi,
):
    api.respond(
        "list_related_videos",
        {"items": [video_item("r1", duration="PT4M"), video_item("r2")]},
    )

    related = got(Video.get("v0").related_videos)

    assert [got(r.length) for r in related] == [240, 180]
    settle()
    assert api.calls_to("list_videos") == []


def test_related_videos_without_a_snippet_are_skipped(api: FakeApi):
    api.respond(
        "list_related_videos",
        {
            "items": [
                {"id": {"kind": "youtube#video", "videoId": "nosnippet"}},
                video_item("r1"),
            ]
        },
    )

    assert ids_of(got(Video.get("v0").related_videos)) == ["r1"]


def test_a_video_without_related_videos_has_an_empty_list(api: FakeApi):
    assert got(Video.get("v0").related_videos) == []


def test_related_videos_are_looked_up_once(api: FakeApi):
    api.respond("list_related_videos", {"items": [video_item("r1")]})
    video = Video.get("v0")

    first = video.related_videos
    second = video.related_videos

    assert first is second
    assert len(got(first)) == 1
    assert len(api.calls_to("list_related_videos")) == 1


# ---------------------------------------------------------------------------
# Playlist.load_info


def test_a_playlist_loads_its_details_with_one_api_call(api: FakeApi):
    serve_playlists(api, listed_playlist("PL1", title="Mix", count=30, channel="DJ"))
    playlist = Playlist.get("PL1")

    assert got(playlist.title) == "Mix"
    assert got(playlist.video_count) == 30
    assert got(playlist.channel) == "DJ"
    assert got(playlist.thumbnails) == images("PL1")

    settle()
    assert api.calls_to("list_playlists") == [(["PL1"],)]


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        ("title", "Listed PL1"),
        ("video_count", 12),
        ("thumbnails", images("PL1")),
        ("channel", "Listed owner of PL1"),
    ],
)
def test_any_detail_of_a_playlist_starts_the_one_load(
    api: FakeApi, field: str, expected: Any
):
    serve_playlists(api, listed_playlist("PL1"))
    playlist = Playlist.get("PL1")

    assert got(getattr(playlist, field)) == expected
    assert got(playlist.title) == "Listed PL1"

    settle()
    assert api.calls_to("list_playlists") == [(["PL1"],)]


def test_the_video_count_of_a_loaded_playlist_is_capped(api: FakeApi):
    context.playlist_max_videos = 10
    serve_playlists(api, listed_playlist("PL1", count=400))

    assert got(Playlist.get("PL1").video_count) == 10


def test_load_info_asks_for_the_playlists_in_batches_of_fifty(api: FakeApi):
    ids = [f"PL{n:03}" for n in range(120)]
    serve_playlists(api, *(listed_playlist(i) for i in ids))
    playlists = [Playlist.get(i) for i in ids]

    Playlist.load_info(playlists)

    assert [got(p.title) for p in playlists] == [f"Listed {i}" for i in ids]
    assert sorted(args[0] for args in api.calls_to("list_playlists")) == sorted(
        [ids[:50], ids[50:100], ids[100:]]
    )


def test_load_info_does_not_ask_again_for_playlists_that_are_loaded(api: FakeApi):
    serve_playlists(api, listed_playlist("PL1"), listed_playlist("PL2"))
    first, second = Playlist.get("PL1"), Playlist.get("PL2")
    got(first.title)
    got(first.channel)
    got(first.video_count)
    got(first.thumbnails)

    Playlist.load_info([first, second])

    assert got(second.title) == "Listed PL2"
    settle()
    assert api.calls_to("list_playlists") == [(["PL1"],), (["PL2"],)]


@pytest.mark.parametrize(
    "response",
    [RuntimeError("no network"), {"items": []}],
    ids=["raises", "not-found"],
)
def test_a_playlist_the_api_cannot_describe_still_resolves(
    api: FakeApi, response: Any, caplog: pytest.LogCaptureFixture
):
    api.respond("list_playlists", response)
    playlist = Playlist.get("PL1")

    with caplog.at_level(logging.ERROR, logger="mopidy_youtube"):
        values = [
            got(playlist.title),
            got(playlist.video_count),
            got(playlist.thumbnails),
            got(playlist.channel),
        ]

    assert values == [None] * 4


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Playlist.load_info reads data['items'] outside its error handling: an "
        "error response (quota, bad key) raises in the load job and the futures "
        "never resolve (Video.load_info copes with the same response)"
    ),
)
def test_a_playlist_resolves_when_the_api_answers_with_an_error(api: FakeApi):
    api.respond("list_playlists", {"error": {"code": 403}})

    assert Playlist.get("PL1").title.get(timeout=SHORT_TIMEOUT) is None


# ---------------------------------------------------------------------------
# Playlist.videos


def serve_listing(api: FakeApi, count: int) -> list[str]:
    """Make `list_videos` know `count` videos `v00`, `v01`, ... and return the ids."""
    ids = [f"v{n:02}" for n in range(count)]
    serve_videos(api, *(listed_video(i) for i in ids))
    return ids


def test_the_videos_of_a_playlist_are_its_playlist_items_in_order(api: FakeApi):
    serve_pages(api, {"": page_of("v00", "v01", "v02")})
    serve_listing(api, 3)

    videos = got(Playlist.get("PL1").videos)

    assert [type(v) for v in videos] == [Video] * 3
    assert ids_of(videos) == ["v00", "v01", "v02"]
    assert videos[0] is Video.get("v00")
    assert api.calls_to("list_playlistitems") == [("PL1", "", 50)]


def test_playlist_videos_know_their_title_from_the_page_and_the_rest_from_a_listing(
    api: FakeApi,
):
    serve_pages(
        api,
        {
            "": {
                "items": [
                    playlist_entry("v00", title="From the page", owner="Page owner"),
                    playlist_entry("v01"),
                ]
            }
        },
    )
    serve_videos(
        api,
        listed_video("v00", title="From the listing", duration="PT5M", channel="Chan"),
        listed_video("v01", duration="PT1M"),
    )

    first, second = got(Playlist.get("PL1").videos)

    assert got(first.title) == "From the page"
    assert got(first.length) == 300
    assert got(first.channel) == "Chan"
    assert got(second.length) == 60
    settle()
    assert api.calls_to("list_videos") == [(["v00", "v01"],)]


def test_playlist_videos_that_come_complete_need_no_listing(api: FakeApi):
    entries = [
        video_item(f"v{n:02}", duration="PT2M", thumbnails=thumbnails(f"v{n:02}"))
        for n in range(2)
    ]
    for entry in entries:
        entry["snippet"]["resourceId"] = {"videoId": entry["id"]["videoId"]}
    serve_pages(api, {"": {"items": entries}})

    videos = got(Playlist.get("PL1").videos)

    assert [got(v.length) for v in videos] == [120, 120]
    assert [got(v.thumbnails) for v in videos] == [images("v00"), images("v01")]
    settle()
    assert api.calls_to("list_videos") == []


def test_a_playlist_is_read_page_by_page_until_the_last_page(api: FakeApi):
    serve_pages(
        api,
        {
            "": page_of("v00", "v01", then="two"),
            "two": page_of("v02", "v03", then="three"),
            "three": page_of("v04"),
        },
    )
    serve_listing(api, 5)

    videos = got(Playlist.get("PL1").videos)

    assert ids_of(videos) == [f"v{n:02}" for n in range(5)]
    assert api.calls_to("list_playlistitems") == [
        ("PL1", "", 50),
        ("PL1", "two", 48),
        ("PL1", "three", 46),
    ]
    settle()
    assert api.calls_to("list_videos") == [([f"v{n:02}" for n in range(5)],)]


def test_a_playlist_has_no_more_videos_than_the_configured_maximum(api: FakeApi):
    context.playlist_max_videos = 3
    serve_pages(
        api,
        {
            "": page_of("v00", "v01", then="two"),
            "two": page_of("v02", "v03", then="three"),
            "three": page_of("v04"),
        },
    )
    serve_listing(api, 5)

    videos = got(Playlist.get("PL1").videos)

    assert ids_of(videos) == ["v00", "v01", "v02"]
    # the second page is asked for what is still missing, and there is no third
    assert api.calls_to("list_playlistitems") == [("PL1", "", 3), ("PL1", "two", 1)]
    settle()
    assert api.calls_to("list_videos") == [(["v00", "v01", "v02"],)]


def test_the_maximum_also_limits_the_size_of_a_page(api: FakeApi):
    context.playlist_max_videos = 1000
    serve_pages(api, {"": page_of("v00", then="two"), "two": page_of("v01")})
    serve_listing(api, 2)

    got(Playlist.get("PL1").videos)

    assert api.calls_to("list_playlistitems") == [("PL1", "", 50), ("PL1", "two", 50)]


def test_deleted_and_private_videos_are_left_out(api: FakeApi):
    serve_pages(
        api,
        {
            "": {
                "items": [
                    playlist_entry("v00"),
                    playlist_entry("v01", title="Deleted video"),
                    playlist_entry("v02", title="Private video"),
                    playlist_entry("v03"),
                ]
            }
        },
    )
    serve_listing(api, 4)

    videos = got(Playlist.get("PL1").videos)

    assert ids_of(videos) == ["v00", "v03"]
    settle()
    assert api.calls_to("list_videos") == [(["v00", "v03"],)]


def test_deleted_videos_do_not_count_towards_the_maximum(api: FakeApi):
    context.playlist_max_videos = 2
    serve_pages(
        api,
        {
            "": {
                "items": [
                    playlist_entry("v00", title="Deleted video"),
                    playlist_entry("v01"),
                ],
                "nextPageToken": "two",
            },
            "two": page_of("v02", "v03"),
        },
    )
    serve_listing(api, 4)

    assert ids_of(got(Playlist.get("PL1").videos)) == ["v01", "v02"]


def test_a_playlist_entry_without_a_video_is_left_out(api: FakeApi):
    serve_pages(api, {"": page_of("v00", None, "v02")})
    serve_listing(api, 3)

    assert ids_of(got(Playlist.get("PL1").videos)) == ["v00", "v02"]


def test_an_empty_playlist_has_no_videos_and_needs_no_listing(api: FakeApi):
    serve_pages(api, {"": {"items": []}})

    assert got(Playlist.get("PL1").videos) == []
    settle()
    assert api.calls_to("list_videos") == []


def test_the_videos_of_a_playlist_are_looked_up_once(api: FakeApi):
    serve_pages(api, {"": page_of("v00")})
    serve_listing(api, 1)
    playlist = Playlist.get("PL1")

    first = playlist.videos
    second = playlist.videos

    assert first is second
    assert ids_of(got(first)) == ["v00"]
    assert len(api.calls_to("list_playlistitems")) == 1


def test_a_playlist_keeps_the_videos_of_the_pages_before_an_error(
    api: FakeApi, caplog: pytest.LogCaptureFixture
):
    serve_pages(
        api,
        {
            "": page_of("v00", "v01", then="two"),
            "two": {"error": {"code": 500}},
        },
    )
    serve_listing(api, 2)

    with caplog.at_level(logging.ERROR, logger="mopidy_youtube"):
        videos = got(Playlist.get("PL1").videos)

    assert ids_of(videos) == ["v00", "v01"]
    assert len(api.calls_to("list_playlistitems")) == 2
    assert "error in list playlist items data" in caplog.text


def test_a_playlist_whose_page_is_an_error_has_no_videos(api: FakeApi):
    serve_pages(api, {"": {"error": {"code": 404}}})

    assert got(Playlist.get("PL1").videos) == []
    settle()
    assert api.calls_to("list_videos") == []


def test_a_playlist_whose_api_fails_has_no_videos(
    api: FakeApi, caplog: pytest.LogCaptureFixture
):
    api.respond("list_playlistitems", RuntimeError("no network"))

    with caplog.at_level(logging.ERROR, logger="mopidy_youtube"):
        assert got(Playlist.get("PL1").videos) == []

    assert len(api.calls_to("list_playlistitems")) == 1
    assert "list_playlistitems error" in caplog.text


def test_an_api_that_fails_halfway_keeps_what_it_gave(api: FakeApi):
    def answer(playlist_id: str, page: str, max_results: int) -> dict[str, Any]:
        if page:
            msg = "connection reset"
            raise RuntimeError(msg)
        return page_of("v00", then="two")

    api.respond("list_playlistitems", answer)
    serve_listing(api, 1)

    assert ids_of(got(Playlist.get("PL1").videos)) == ["v00"]


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Playlist.videos does not guard _set_api_data: an entry whose thumbnails "
        "lack a width (jAPI's default thumbnail) raises in the load job and the "
        "future of the videos never resolves"
    ),
)
def test_a_playlist_resolves_when_an_entry_has_a_thumbnail_without_a_width(
    api: FakeApi,
):
    entry = playlist_entry("v00")
    entry["snippet"]["thumbnails"] = {"default": {"url": "https://img/default.jpg"}}
    serve_pages(api, {"": {"items": [entry]}})
    serve_listing(api, 1)

    assert ids_of(Playlist.get("PL1").videos.get(timeout=SHORT_TIMEOUT)) == ["v00"]


# ---------------------------------------------------------------------------
# Channel.playlists


def test_the_playlists_of_a_channel_are_playlists_with_title_and_count(api: FakeApi):
    api.respond(
        "list_channelplaylists",
        {
            "items": [
                channel_playlist("PL1", title="First", count=3),
                channel_playlist("PL2", title="Second", count=900),
            ]
        },
    )

    playlists = Channel.playlists("UC1")

    assert [type(p) for p in playlists] == [Playlist, Playlist]
    assert playlists[0] is Playlist.get("PL1")
    assert [got(p.title) for p in playlists] == ["First", "Second"]
    assert [got(p.video_count) for p in playlists] == [3, 50]
    assert api.calls_to("list_channelplaylists") == [("UC1",)]


def test_the_playlists_of_a_channel_start_loading_their_videos(api: FakeApi):
    api.respond(
        "list_channelplaylists",
        {"items": [channel_playlist("PL1"), channel_playlist("PL2")]},
    )
    serve_pages(api, {"": page_of("v00", "v01")})
    serve_listing(api, 2)

    playlists = Channel.playlists("UC1")

    assert [ids_of(got(p.videos)) for p in playlists] == [["v00", "v01"]] * 2
    assert sorted(api.calls_to("list_playlistitems")) == [
        ("PL1", "", 50),
        ("PL2", "", 50),
    ]


def test_the_channel_root_is_the_configured_channel(api: FakeApi):
    context.channel = "UCown"
    api.respond("list_channelplaylists", {"items": [channel_playlist("PL1")]})

    playlists = Channel.playlists("root")

    assert ids_of(playlists) == ["PL1"]
    assert api.calls_to("list_channelplaylists") == [("UCown",)]


@pytest.mark.parametrize("channel_id", [None, "root"])
def test_without_a_channel_there_are_no_playlists_to_ask_for(
    api: FakeApi, channel_id: str | None
):
    context.channel = None

    assert Channel.playlists(channel_id) is None
    assert api.calls == []


@pytest.mark.parametrize(
    "response",
    [{"error": {"code": 404}}, RuntimeError("no network")],
    ids=["error-dict", "raises"],
)
def test_playlists_of_a_channel_the_api_fails_on_are_none(
    api: FakeApi, response: Any, caplog: pytest.LogCaptureFixture
):
    api.respond("list_channelplaylists", response)

    with caplog.at_level(logging.ERROR, logger="mopidy_youtube"):
        assert Channel.playlists("UC1") is None

    assert "list_channelplaylists error" in caplog.text


def test_a_channel_listing_that_cannot_be_read_gives_no_playlists(
    api: FakeApi, caplog: pytest.LogCaptureFixture
):
    api.respond(
        "list_channelplaylists",
        {
            "items": [
                channel_playlist("PL1"),
                {"id": "PL2", "snippet": {}, "contentDetails": {"itemCount": 1}},
            ]
        },
    )

    with caplog.at_level(logging.ERROR, logger="mopidy_youtube"):
        assert Channel.playlists("UC1") is None

    assert "map error" in caplog.text


def test_a_channel_without_playlists_has_an_empty_list(api: FakeApi):
    assert Channel.playlists("UC1") == []


# ---------------------------------------------------------------------------
# integration with the YouTube Music client


ANONYMOUS = {"Cookie": "PREF=hl=en; CONSENT=YES+20210329;"}

# ids in tests/fixtures/music
SONG_ID = "fJ9rUzIMcZQ"
UNAVAILABLE_ID = "aaaaaaaaaaa"
ALBUM_ID = "MPREb_eEpQf8QskKl"
OTHER_ALBUM_ID = "MPREb_ppvh6pdaiCc"
OLAK_ID = "OLAK5uy_mQGa-V4qspfisNHu1kXthY1w93yJNT0rw"
PLAYLIST_ID = "PL4fGSI1pDJn6jXS_Tv_N9B8Z0HTRVJE0m"
ARTIST_ID = "UCEPMVbUzImPl4p8k4LkGevA"
ALBUM_TITLE = "A Night At The Opera"
ALBUM_TRACK_IDS = ["kqVpk0qxmfA", "OU6EyXcFBxA", "oaEM4JYFPfw", "HaZpZQG2z10"]
ALBUM_TRACK_TITLES = [
    "Death On Two Legs (Dedicated To...)",
    "Lazing On A Sunday Afternoon",
    "I'm In Love With My Car",
    "You're My Best Friend",
]
ALBUM_TRACK_LENGTHS = [224, 68, 185, 171]
QUEEN = [{"name": "Queen", "uri": f"yt:channel:{ARTIST_ID}"}]
ALBUM = {"name": ALBUM_TITLE, "uri": f"yt:playlist:{ALBUM_ID}"}
PLAYLIST_TRACK_IDS = ["D968qfUZMUE", "GxChUrrY4bc", "7mDDM0eBWR0", "F_EGihOgXsg"]
RELATED_IDS = ["U-Ooxpz0Eqk", "-SaUrDhp034", "oMfMUfgjiLg", "ulRXvH8VOl8"]
WATCH_IDS = [SONG_ID, "04854XqcfCY", "kR4zpS-ky9o"]
RELATED_ALBUM_IDS = [
    "MPREb_4EH1Eo0cgGr",
    "MPREb_8lrA5KA4Gfv",
    "MPREb_fN7uwe7VDV6",
    "MPREb_jnYA50rlu4H",
]
ARTIST_ALBUM_IDS = [
    "OLAK5uy_kol_swyj7Jpirgq7d5UnCAghTEX4wLdUg",
    "OLAK5uy_mo3flQUFtMFqJlzckSzj63duhUMS6gv5Q",
    "OLAK5uy_n-Fn_Y9_8eezE8hAAvdPJHUuuKRvzVjfw",
]


def music_fixture(name: str) -> Any:
    return load_fixture(f"music/{name}.json")


def album_response(browse_id: str) -> dict[str, Any]:
    """`YTMusic.get_album`: the recorded album, and for any other id a lookalike.

    The lookalike has tracks of its own, so that albums do not share videos.
    """
    album = music_fixture("album")
    if browse_id != ALBUM_ID:
        album["title"] = f"Album {browse_id}"
        for number, track in enumerate(album["tracks"]):
            track["videoId"] = f"{browse_id}/{number}"
    return album


def album_title(browse_id: str) -> str:
    return ALBUM_TITLE if browse_id == ALBUM_ID else f"Album {browse_id}"


def album_track_ids(browse_id: str) -> list[str]:
    if browse_id == ALBUM_ID:
        return ALBUM_TRACK_IDS
    return [f"{browse_id}/{number}" for number in range(4)]


def browse_id_of(audio_playlist_id: str) -> str:
    """The browse id of the album with an `OLAK5uy_` audio playlist."""
    if audio_playlist_id == OLAK_ID:
        return ALBUM_ID
    return "MPREb_" + audio_playlist_id.removeprefix("OLAK5uy_")


class InlineExecutor:
    """Runs jobs when they are submitted, so that background work is awaited."""

    def submit(self, fn: Callable[..., Any], *args: Any) -> Future[Any]:
        future: Future[Any] = Future()
        try:
            future.set_result(fn(*args))
        except Exception as e:
            future.set_exception(e)
        return future

    def shutdown(self, *, wait: bool = True, cancel_futures: bool = False) -> None:
        pass


@dataclass
class MusicRig:
    """A real `Music` over a mocked `YTMusic` that answers with the fixtures."""

    music: Music
    ytmusic: mock.MagicMock
    fallback: mock.Mock

    def calls(self, method: str) -> int:
        return getattr(self.ytmusic, method).call_count


@pytest.fixture
def rig() -> Iterator[MusicRig]:
    def get_song(video_id: str) -> dict[str, Any]:
        if video_id == UNAVAILABLE_ID:
            return music_fixture("song_unavailable")
        return music_fixture("songs")[video_id]

    def search(filter: str, **_: Any) -> list[dict[str, Any]]:
        return music_fixture("search_albums" if filter == "albums" else "search_songs")

    with mock.patch("mopidy_youtube.apis.youtube_music.YTMusic") as ytm_class:
        fallback = mock.Mock()
        fallback.list_related_videos.return_value = {"items": []}
        music = Music(None, ANONYMOUS, fallback)
        ytmusic = music.ytmusic
        assert isinstance(ytmusic, mock.MagicMock)
        ytmusic.search.side_effect = search
        ytmusic.get_song.side_effect = get_song
        ytmusic.get_album.side_effect = album_response
        ytmusic.get_playlist.side_effect = lambda _: music_fixture("playlist")
        ytmusic.get_watch_playlist.side_effect = lambda _: music_fixture(
            "watch_playlist"
        )
        ytmusic.get_song_related.side_effect = lambda _: music_fixture("song_related")
        ytmusic.get_artist.side_effect = lambda _: music_fixture("artist")
        ytmusic.get_artist_albums.side_effect = lambda *_: music_fixture(
            "artist_albums"
        )
        ytm_class.get_album_browse_id.side_effect = lambda _ytmusic, audio_id: (
            browse_id_of(audio_id)
        )
        # the albums of related tracks are looked up in the background: wait for them
        if hasattr(music, "_lookup_executor"):
            music._lookup_executor.shutdown()
            music._lookup_executor = InlineExecutor()  # type: ignore[assignment]
        context.api = music
        try:
            yield MusicRig(music, ytmusic, fallback)
        finally:
            settle()
            music.close()


def assert_album_videos(
    videos: list[Video], album_id: str = ALBUM_ID, *, listed_as: str | None = None
) -> None:
    """The four tracks of an album, all they should know about themselves.

    `listed_as` is the id the album was asked for, when it is not its browse id.
    """
    assert ids_of(videos) == album_track_ids(album_id)
    assert [got(v.title) for v in videos] == ALBUM_TRACK_TITLES
    assert [got(v.length) for v in videos] == ALBUM_TRACK_LENGTHS
    assert [got(v.channel) for v in videos] == ["Queen"] * 4
    assert [got(v.artists) for v in videos] == [QUEEN] * 4
    album = {
        "name": album_title(album_id),
        "uri": f"yt:playlist:{listed_as or album_id}",
    }
    assert [got(v.album) for v in videos] == [album] * 4
    assert [got(v.track_no) for v in videos] == [1, 2, 3, 4]
    assert [[i.width for i in got(v.thumbnails)] for v in videos] == [[544]] * 4


def test_music_search_finds_the_albums_and_then_the_songs(rig: MusicRig):
    results = Entry.search("a night at the opera")

    assert [type(r) for r in results] == [Playlist, Playlist, Video, Video, Video]
    albums = {r.id: r for r in results[:2]}
    assert set(albums) == {ALBUM_ID, OTHER_ALBUM_ID}
    assert [got(a.title) for a in albums.values()] == [album_title(i) for i in albums]
    assert [got(a.channel) for a in albums.values()] == ["Queen", "Queen"]
    assert [got(a.video_count) for a in albums.values()] == [12, 12]
    assert [[i.width for i in got(a.thumbnails)] for a in albums.values()] == [
        [544]
    ] * 2
    songs = results[2:]
    assert ids_of(songs) == ["BSTsnWoslP4", "_Xsu44ppnFQ", "soHI4sKPQ3E"]
    assert [got(v.title) for v in songs] == [
        "Bohemian Rhapsody",
        "Bohemian Rhapsody x Walk It Talk It",
        "Bohemian Rhapsody",
    ]
    assert [got(v.channel) for v in songs] == ["Queen", "nimphia", "Ndlovu Youth Choir"]
    assert got(songs[0].length) == 355
    assert got(songs[0].artists)[0]["name"] == "Queen"
    assert all(got(v.thumbnails) for v in songs)


def test_music_search_needs_no_lookup_per_result(rig: MusicRig):
    Entry.search("a night at the opera")
    settle()

    assert rig.calls("search") == 2  # the albums and the songs
    assert rig.calls("get_album") == 2  # the track count of each album found
    assert rig.calls("get_song") == 0
    assert rig.calls("get_playlist") == 0


def test_the_tracks_of_a_found_album_are_complete(rig: MusicRig):
    album = next(r for r in Entry.search("a night at the opera") if r.id == ALBUM_ID)

    assert_album_videos(got(album.videos))

    assert (got(album.title), got(album.video_count), got(album.channel)) == (
        ALBUM_TITLE,
        12,
        "Queen",
    )
    settle()
    assert rig.calls("get_song") == 0
    assert rig.calls("get_album") <= 3  # the search, and at most one more look


def test_an_album_opened_by_its_id_has_complete_tracks(rig: MusicRig):
    album = Playlist.get(ALBUM_ID)

    assert_album_videos(got(album.videos))

    assert got(album.title) == ALBUM_TITLE
    assert got(album.video_count) == 12
    assert got(album.channel) == "Queen"
    assert [i.width for i in got(album.thumbnails)] == [544]
    settle()
    assert rig.calls("get_song") == 0
    assert rig.calls("get_playlist") == 0
    assert 1 <= rig.calls("get_album") <= 2


def test_an_album_asked_about_before_its_tracks_has_complete_tracks(rig: MusicRig):
    album = Playlist.get(ALBUM_ID)

    assert got(album.title) == ALBUM_TITLE
    assert got(album.video_count) == 12
    assert_album_videos(got(album.videos))

    settle()
    assert rig.calls("get_song") == 0
    assert 1 <= rig.calls("get_album") <= 2


def test_an_audio_playlist_of_an_album_is_the_album_under_its_own_id(rig: MusicRig):
    album = Playlist.get(OLAK_ID)

    videos = got(album.videos)

    assert got(album.title) == ALBUM_TITLE
    assert_album_videos(videos, ALBUM_ID, listed_as=OLAK_ID)
    settle()
    assert rig.calls("get_song") == 0


def test_a_music_playlist_has_complete_tracks(rig: MusicRig):
    playlist = Playlist.get(PLAYLIST_ID)

    videos = got(playlist.videos)

    assert ids_of(videos) == PLAYLIST_TRACK_IDS
    assert got(videos[0].title) == "NEON"
    assert [got(v.length) for v in videos] == [223, 205, 212, 179]
    assert [got(v.channel) for v in videos] == [
        "A2O LITE",
        "MEOMURU",
        "i-dle (아이들)",
        "EPIK HIGH",
    ]
    assert [[a["name"] for a in got(v.artists)] for v in videos] == [
        ["A2O LITE", "A2O"],
        ["MEOMURU"],
        ["i-dle (아이들)"],
        ["EPIK HIGH", "DAVICHI"],
    ]
    # a track belongs to its own album, or else to the playlist
    assert [got(v.album)["name"] for v in videos] == [
        "Top 100 Songs South Korea",
        "Top 100 Songs South Korea",
        "Top 100 Songs South Korea",
        "Mise en scène",
    ]
    assert got(videos[0].album)["uri"] == f"yt:playlist:{PLAYLIST_ID}"
    assert [got(v.track_no) for v in videos] == [None] * 4
    assert all(len(got(v.thumbnails)) == 1 for v in videos)
    assert got(playlist.title) == "Top 100 Songs South Korea"
    assert got(playlist.video_count) == 50  # the 100 are capped
    assert got(playlist.channel) == "YouTube Charts"
    assert [i.width for i in got(playlist.thumbnails)] == [1200]
    settle()
    assert rig.calls("get_song") == 0
    assert rig.calls("get_album") == 0
    assert 1 <= rig.calls("get_playlist") <= 2


def test_a_video_of_music_loads_with_one_song_lookup(rig: MusicRig):
    video = Video.get(SONG_ID)

    assert (
        got(video.title) == "Bohemian Rhapsody (Live At Milton Keynes Bowl / June 1982)"
    )
    assert got(video.length) == 359
    assert got(video.channel) == "Queen"

    settle()
    assert rig.calls("get_song") == 1


def test_an_unavailable_video_of_music_says_why(rig: MusicRig):
    video = Video.get(UNAVAILABLE_ID)

    assert got(video.title) == "Video unavailable"
    assert got(video.length) == 0
    assert rig.calls("get_song") == 1


def test_related_videos_of_music(rig: MusicRig):
    related = got(Video.get(SONG_ID).related_videos)

    assert ids_of(related) == [*RELATED_IDS, *WATCH_IDS]
    assert [got(v.title) for v in related][:4] == [
        "Somewhere Over The Rainbow/What A Wonderful World",
        "Every Breath You Take",
        "Sweet Child O' Mine",
        "Wake Me up When September Ends",
    ]
    assert [got(v.length) for v in related] == [308, 254, 356, 286, 359, 185, 266]
    assert [got(v.channel) for v in related] == [
        "Israel Kamakawiwo'ole",
        "The Police",
        "Guns N' Roses",
        "Green Day",
        "Queen",
        "Queen",
        "Aerosmith",
    ]
    assert [got(v.album)["name"] for v in related] == [
        "Facing Future",
        "Synchronicity (Remastered 2003)",
        "Appetite For Destruction",
        "American Idiot",
        "YouTube Playlist",
        "YouTube Playlist",
        "YouTube Playlist",
    ]
    assert got(related[0].album)["uri"] == f"yt:playlist:{RELATED_ALBUM_IDS[0]}"
    assert got(related[0].artists) == [
        {"name": "Israel Kamakawiwo'ole", "uri": "yt:channel:UCDrbjok3kk04f-SByjhpLYg"}
    ]
    assert got(related[4].artists) == [
        {"name": "Queen", "uri": "yt:channel:UCiMhD4jzUqG-IgPzUmmytRQ"}
    ]
    assert [got(v.track_no) for v in related] == [None] * 7
    assert all(got(v.thumbnails) for v in related)


def test_related_videos_of_music_cost_one_song_lookup_each(rig: MusicRig):
    got(Video.get(SONG_ID).related_videos)
    settle()

    assert rig.calls("get_watch_playlist") == 1
    assert rig.calls("get_song_related") == 1
    # the 4 related songs and the 3 of the watch playlist, and none to load them
    assert rig.calls("get_song") == 7
    rig.fallback.list_related_videos.assert_called_once_with(SONG_ID)


def test_the_album_of_a_related_video_opens_without_song_lookups(rig: MusicRig):
    got(Video.get(SONG_ID).related_videos)
    album = Playlist.get(RELATED_ALBUM_IDS[0])

    videos = got(album.videos)

    assert got(album.title) == album_title(RELATED_ALBUM_IDS[0])
    assert_album_videos(videos, RELATED_ALBUM_IDS[0])
    settle()
    assert rig.calls("get_song") == 7


def test_the_playlists_of_an_artist_of_music_are_its_albums(rig: MusicRig):
    playlists = Channel.playlists(ARTIST_ID)

    assert ids_of(playlists) == ARTIST_ALBUM_IDS
    assert [got(p.title) for p in playlists] == [
        "Queen Budapest",
        "Queen II (2026 Mix)",
        "Acoustic",
    ]
    rig.ytmusic.get_artist.assert_called_once_with(ARTIST_ID)
    rig.ytmusic.get_artist_albums.assert_called_once()


def test_the_albums_of_an_artist_of_music_open_with_complete_tracks(rig: MusicRig):
    playlists = Channel.playlists(ARTIST_ID)

    for playlist in playlists:
        # a lookalike of the recorded album stands in for each of them
        assert_album_videos(
            got(playlist.videos), browse_id_of(playlist.id), listed_as=playlist.id
        )
        assert got(playlist.channel) == "Queen"

    settle()
    assert rig.calls("get_song") == 0
    assert rig.calls("get_playlist") == 0
    assert 3 <= rig.calls("get_album") <= 6  # one for each, and at most one more


def test_a_channel_that_is_a_user_of_music_has_its_public_playlists(rig: MusicRig):
    rig.ytmusic.get_artist.side_effect = KeyError("not an artist")
    rig.ytmusic.get_user.side_effect = lambda _: music_fixture("user")

    playlists = Channel.playlists("UCSHZKyawb77ixDdsGog4iWA")

    assert ids_of(playlists) == ["PLrAXtmErZgOfvk4SvtkAMXNw6iF9qfMen"]
    assert got(playlists[0].title) == "Guitar & Piano"
    rig.ytmusic.get_user.assert_called_once_with("UCSHZKyawb77ixDdsGog4iWA")


# ---------------------------------------------------------------------------
# integration with the scraping client, jAPI

BASE = "https://www.youtube.com/"
SEARCH_URL = BASE + "youtubei/v1/search"
VIDEO_SP = "EgIQAQ%3D%3D"
PLAYLIST_SP = "EgIQAw%3D%3D"
JAPI_PLAYLIST_ID = "PLFgquLnL59alCl_2TQvOiD5Vgm1hCaGSI"
JAPI_CHANNEL_ID = "UCuAXFkgsw1L7xaCfnd5JJOw"
ZOO_ID = "jNQXAC9IVRw"


class JapiSite(FakeYouTube):
    """youtube.com: the search answers by the kind of result that is asked for."""

    def __init__(self) -> None:
        super().__init__()
        self.searches: dict[str, str] = {}

    def send(
        self, request: requests.PreparedRequest, *args: Any, **kwargs: Any
    ) -> requests.Response:
        if (request.url or "").startswith(SEARCH_URL):
            sp = parse_qs(urlparse(request.url).query)["params"][0]
            body = json.dumps(load_fixture(f"japi/{self.searches[sp]}")).encode()
            self._routes = [("POST", SEARCH_URL, body, 200)]
        return super().send(request, *args, **kwargs)

    def page(self, url: str, fixture: str) -> None:
        self.add("GET", url, body=yt_initial_data_page(load_fixture(f"japi/{fixture}")))

    def gets(self, url: str) -> list[str]:
        return [r.url or "" for r in self.calls("GET", url)]


@pytest.fixture
def site() -> Iterator[JapiSite]:
    site = JapiSite()
    client = jAPI(None, {})
    site.attach(client)
    context.api = client
    try:
        yield site
    finally:
        settle()
        client.close()


def test_jAPI_search_finds_videos_and_playlists_with_their_details(site: JapiSite):
    site.searches = {
        VIDEO_SP: "search_videos.json",
        PLAYLIST_SP: "search_playlists_lockups.json",
    }
    context.search_results = 3

    results = Entry.search("never gonna give you up")

    assert [type(r) for r in results] == [Video] * 3 + [Playlist] * 3
    assert ids_of(results[:3]) == ["dQw4w9WgXcQ", "7FwDP17XPlk", "5SZYz7lZRRI"]
    assert [got(v.title) for v in results[:3]] == [
        "Rick Astley - Never Gonna Give You Up (Official Video) (4K Remaster)",
        "Rick Astley - Never Gonna Give You Up",
        "Rick Astley - Never Gonna Give You Up (Official Music Video) (1987)",
    ]
    assert [got(v.channel) for v in results[:3]] == [
        "Rick Astley",
        "Amazing Lyrics",
        "Super Top Songs",
    ]
    assert [got(v.length) for v in results[:3]] == [214, 214, 213]
    assert got(results[0].artists) == [
        {
            "name": "Rick Astley (Channel)",
            "uri": "yt:channel:UCuAXFkgsw1L7xaCfnd5JJOw",
        }
    ]
    assert [(i.width, i.height) for i in got(results[0].thumbnails)] == [(720, 404)]
    assert ids_of(results[3:]) == [
        "PLl8RNOyzcwBjjIajUplE6oV8Vi5Od65H2",
        "PLd5Vfgy_sILZXNGHKlAHnwPOEhboVQNBG",
        "PLL8jFEKG82Z7vNDMUamdAcNL4JwGZ8CMG",
    ]
    assert [got(p.channel) for p in results[3:]] == [
        "Seh",
        "ゆうきtvメイン",
        "Iris Trismegistus",
    ]
    assert [got(p.video_count) for p in results[3:]] == [50, 50, 18]
    assert all(got(p.title) and got(p.thumbnails) for p in results[3:])


def test_jAPI_search_needs_nothing_but_the_search(site: JapiSite):
    site.searches = {
        VIDEO_SP: "search_videos.json",
        PLAYLIST_SP: "search_playlists_lockups.json",
    }
    context.search_results = 3

    for result in Entry.search("never gonna give you up"):
        got(result.title)
        got(result.channel)
    settle()

    assert [r.method for r in site.requests] == ["POST", "POST"]


def test_jAPI_playlist_videos_are_complete_without_loading_each_video(site: JapiSite):
    site.page(BASE + "playlist", "playlist_page.json")
    playlist = Playlist.get(JAPI_PLAYLIST_ID)

    videos = got(playlist.videos)

    assert ids_of(videos) == ["fOT0BUpITw8", "NFvDHYMzj9U", "8c7KOGxeY3w"]
    assert [got(v.title) for v in videos] == [
        "BELLAKEO (Video Oficial) - Peso Pluma, Anitta",
        "Arcángel - FN8 ( Video Lyric )",
        (
            "Becky G - POR EL CONTRARIO (Performance Video) ft. Ángela Aguilar, "
            "Leonardo Aguilar"
        ),
    ]
    assert [got(v.length) for v in videos] == [235, 650, 235]
    assert [got(v.channel) for v in videos] == ["Peso Pluma", "Arcangel", "Becky G"]
    assert [got(v.channelId) for v in videos] == [
        "UCzrM_068Odho89mTRrrxqbA",
        "UCu4bj03KW4CwAsYtHSwMEsQ",
        "UCgtNC51EUSgcZ6kKyVoPxKA",
    ]
    assert [[a["name"] for a in got(v.artists)] for v in videos] == [
        ["Peso Pluma (Channel)"],
        ["Arcangel (Channel)"],
        ["Becky G (Channel)"],
    ]
    assert [[(i.width, i.height) for i in got(v.thumbnails)] for v in videos] == [
        [(336, 188)]
    ] * 3
    assert [got(v.album) for v in videos] == [
        {"name": "YouTube Playlist", "uri": None}
    ] * 3
    assert [got(v.track_no) for v in videos] == [None] * 3
    settle()
    # the playlist page, and nothing for any of its videos
    assert [r.url for r in site.requests] == [
        f"{BASE}playlist?list={JAPI_PLAYLIST_ID}&app=desktop&persist_app=1"
    ]


def test_jAPI_playlist_details_come_from_a_playlist_lookup(site: JapiSite):
    site.searches = {PLAYLIST_SP: "search_playlists_lockups.json"}
    site.page(BASE + "results", "search_playlists_lockups.json")
    site.page(BASE + "playlist", "playlist_page.json")
    playlist = Playlist.get(JAPI_PLAYLIST_ID)

    assert got(playlist.title) == "Popular Music Videos"
    assert got(playlist.channel) == "Music"
    assert got(playlist.video_count) == 50  # of 182, capped
    assert [i.width for i in got(playlist.thumbnails)] == [176]
    settle()
    assert len(site.gets(BASE + "results")) == 1
    assert len(site.gets(BASE + "playlist")) <= 1


def test_jAPI_related_videos_are_complete_without_loading_each_video(site: JapiSite):
    site.page(BASE + "watch", "watch_zoo.json")

    related = got(Video.get(ZOO_ID).related_videos)

    assert ids_of(related) == ["P4Ex2AafR1U", "Y_BCuvEcISY", "fu0mb3PmOoE"]
    assert got(related[0].title) == (
        "Turn Your Screen Into a Soft Warm Light (Instant Fix For Video Lighting)"
    )
    assert [got(v.length) for v in related] == [7200, 17279, 4025]
    assert [got(v.channel) for v in related] == [
        "Use Your Screen As Light",
        "아오링고 잡화점 AORINGGO",
        "Tyler Vitelli 3",
    ]
    assert [got(v.artists)[0]["name"] for v in related] == [
        "Use Your Screen As Light",
        "아오링고 잡화점 AORINGGO",
        "Tyler Vitelli 3",
    ]
    assert [[(i.width, i.height) for i in got(v.thumbnails)] for v in related] == [
        [(336, 188)]
    ] * 3
    settle()
    assert [r.url for r in site.requests] == [
        f"{BASE}watch?v={ZOO_ID}&app=desktop&persist_app=1"
    ]


def test_jAPI_channel_playlists_start_loading_their_videos(site: JapiSite):
    site.page(
        BASE + f"channel/{JAPI_CHANNEL_ID}/playlists", "channel_playlists_lockups.json"
    )
    site.page(BASE + "playlist", "playlist_page.json")

    playlists = Channel.playlists(JAPI_CHANNEL_ID)

    assert ids_of(playlists) == [
        "PLlaN88a7y2_qHDbY9eQbuNTAuEJUSEeuu",
        "PLlaN88a7y2_oK0nKMjZSwdU_njxUYWykm",
        "PLlaN88a7y2_pVVkl4fGdTny21_LRyT85E",
    ]
    titles = [got(p.title) for p in playlists]
    assert titles[0] == "Rick Astley Live at The O2"
    assert titles[1].startswith("Rick Astley (")  # the Japanese edition
    assert titles[2] == "Forever and More"
    assert [got(p.video_count) for p in playlists] == [3, 5, 2]
    for playlist in playlists:
        assert ids_of(got(playlist.videos)) == [
            "fOT0BUpITw8",
            "NFvDHYMzj9U",
            "8c7KOGxeY3w",
        ]
    settle()
    assert len(site.gets(BASE + f"channel/{JAPI_CHANNEL_ID}/playlists")) == 1
    assert len(site.gets(BASE + "playlist")) == 3
    assert not site.gets(BASE + "results")
    assert not site.gets(BASE + "watch")
