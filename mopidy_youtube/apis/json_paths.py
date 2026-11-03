# https://stackoverflow.com/a/14049167
from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from collections.abc import Sequence

type JsonPath = list[str | int]


def deep_search(needles: str | list[str], haystack: Any) -> list[dict[str, Any]]:
    if not isinstance(needles, list):
        needles = [needles]

    if isinstance(haystack, dict):
        found: list[dict[str, Any]] = []
        for needle in needles:
            if needle in haystack:
                found.append({needle: haystack[needle]})
            found.extend(
                result
                for key in haystack
                for result in deep_search(needle, haystack[key])
            )
        return found

    if isinstance(haystack, list):
        return [item for node in haystack for item in deep_search(needles, node)]

    return []


def traverse(input_dict: Any, keys: Sequence[str | int]) -> Any:
    internal_dict_value = input_dict
    for key in keys:
        if isinstance(internal_dict_value, list):
            internal_dict_value = internal_dict_value[cast("int", key)]
        else:
            internal_dict_value = internal_dict_value.get(key, None)
        if internal_dict_value is None:
            raise KeyError
    return internal_dict_value


def traverse_or_none(input_dict: Any, keys: Sequence[str | int]) -> Any:
    """Like `traverse`, but None when any step is missing or of the wrong type."""
    try:
        return traverse(input_dict, keys)
    except (KeyError, IndexError, TypeError, AttributeError):
        return None


# json paths

SECTION_LIST_RENDERER_CONTENTS_PATH: JsonPath = [
    "contents",
    "twoColumnSearchResultsRenderer",
    "primaryContents",
    "sectionListRenderer",
    "contents",
]

CONTINUATION_ITEMS_PATH: JsonPath = [
    "onResponseReceivedCommands",
    0,
    "appendContinuationItemsAction",
    "continuationItems",
]

WATCH_VIDEO_PATH: JsonPath = [
    "contents",
    "twoColumnWatchNextResults",
    "results",
    "results",
    "contents",
]

RELATED_VIDEOS_PATH: JsonPath = [
    "contents",
    "twoColumnWatchNextResults",
    "secondaryResults",
    "secondaryResults",
    "results",
]

# The videos of a playlist page: `lockupViewModel` entries directly in this
# list (current layout), or one `playlistVideoListRenderer` holding them (old).
PLAYLIST_SECTION_CONTENTS_PATH: JsonPath = [
    "contents",
    "twoColumnBrowseResultsRenderer",
    "tabs",
    0,
    "tabRenderer",
    "content",
    "sectionListRenderer",
    "contents",
    0,
    "itemSectionRenderer",
    "contents",
]

PLAYLIST_BASE_PATH: JsonPath = [*PLAYLIST_SECTION_CONTENTS_PATH, 0]

LIST_PLAYLIST_ITEMS_PATH: JsonPath = [
    *PLAYLIST_BASE_PATH,
    "playlistVideoListRenderer",
    "contents",
]

LIST_CHANNEL_PLAYLISTS_PATH: JsonPath = [
    *PLAYLIST_BASE_PATH,
    "shelfRenderer",
    "content",
]

TEXT_PATH: JsonPath = ["runs", 0, "text"]

YTM_ERROR_THUMBNAIL_PATH: JsonPath = [
    "playabilityStatus",
    "errorScreen",
    "playerErrorMessageRenderer",
    "thumbnail",
    "thumbnails",
    0,
]
