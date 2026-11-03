from __future__ import annotations

import contextlib
import json
import re
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode, urljoin

from mopidy_youtube import logger
from mopidy_youtube.apis.client import Client
from mopidy_youtube.apis.json_paths import (
    CONTINUATION_ITEMS_PATH,
    PLAYLIST_SECTION_CONTENTS_PATH,
    RELATED_VIDEOS_PATH,
    SECTION_LIST_RENDERER_CONTENTS_PATH,
    TEXT_PATH,
    WATCH_VIDEO_PATH,
    deep_search,
    traverse,
    traverse_or_none,
)
from mopidy_youtube.context import context
from mopidy_youtube.timeformat import format_duration

if TYPE_CHECKING:
    from collections.abc import Collection


class NoYtDataError(Exception):
    """Raised when a YouTube page contains no ytInitialData payload."""


LOCKUP_VIDEO = "LOCKUP_CONTENT_TYPE_VIDEO"
LOCKUP_PLAYLIST = "LOCKUP_CONTENT_TYPE_PLAYLIST"
MIX_PLAYLIST_PREFIX = "RD"  # auto-generated mixes, the old radioRenderer


def _duration_from_candidates(candidates: list[str], video_id: str) -> str:
    """The first usable duration text as ISO8601, `PT0S` when there is none."""
    for raw_candidate in candidates:
        candidate = (raw_candidate or "").strip()
        if not candidate:
            continue

        lowered = candidate.lower()
        if lowered in {"live", "upcoming", "premiere", "shorts"}:
            logger.info(
                f"video {video_id} marked as {candidate}; "
                "treating as non-playable duration"
            )
            return "PT0S"

        if re.fullmatch(r"\d+:\d{2}(:\d{2})?", candidate):
            duration = "PT" + format_duration(candidate)
            logger.debug(f"video {video_id} duration: {duration}")
            return duration

    logger.warning(f"video {video_id} no video-time, possibly live")
    return "PT0S"


def _find_renderer(nodes: list[dict[str, Any]], key: str) -> dict[str, Any]:
    """The `key` renderer among `nodes`, wherever YouTube put it."""
    for node in nodes:
        if isinstance(node, dict) and key in node:
            return node[key]
    raise KeyError(key)


def _lockup_thumbnail(image_holder: Any) -> dict[str, Any] | None:
    """The largest image of a `thumbnailViewModel`, without tracking parameters."""
    sources = traverse_or_none(image_holder, ["image", "sources"])
    if not isinstance(sources, list) or not sources:
        return None
    best = sources[-1]
    if not isinstance(best, dict) or not isinstance(best.get("url"), str):
        return None
    return {**best, "url": best["url"].split("?", 1)[0]}


def _lockup_badges(lockup: dict[str, Any]) -> list[str]:
    """The texts of the badges on the thumbnail: duration, video count, ..."""
    return [
        text
        for found in deep_search("thumbnailBadgeViewModel", lockup.get("contentImage"))
        if isinstance(text := found["thumbnailBadgeViewModel"].get("text"), str)
    ]


def _lockup_byline(meta: dict[str, Any]) -> tuple[list[str], str | None]:
    """The texts of the first metadata row, and the channel id found in it."""
    row = traverse_or_none(
        meta, ["metadata", "contentMetadataViewModel", "metadataRows", 0]
    )
    parts = (row or {}).get("metadataParts", [])
    texts = [
        text
        for part in parts
        if isinstance(text := (part.get("text") or {}).get("content"), str)
    ]
    channel_id = next(
        (
            browse_id
            for found in deep_search("browseEndpoint", [row, meta.get("image")])
            if str(browse_id := found["browseEndpoint"].get("browseId")).startswith(
                "UC"
            )
        ),
        None,
    )
    return texts, channel_id


def _lockup_video_to_item(
    lockup: dict[str, Any], video_id: str
) -> dict[str, Any] | None:
    meta = lockup.get("metadata", {}).get("lockupMetadataViewModel", {})
    title = traverse_or_none(meta, ["title", "content"])
    if not title:
        logger.error(f"lockup: no title detected for {video_id}")
        title = "unknown"
    if title in ["[Private video]", "[Deleted video]"]:
        logger.info(f"skipping video {video_id}: {title}")
        return None

    thumbnail = _lockup_thumbnail(
        traverse_or_none(lockup, ["contentImage", "thumbnailViewModel"])
    )
    if thumbnail is None:
        logger.error(f"lockup: no thumbnails detected for {video_id}")
        thumbnail = {"url": f"https://i.ytimg.com/vi/{video_id}/default.jpg"}

    byline, channel_id = _lockup_byline(meta)
    if not byline:
        logger.error(f"lockup: no channelTitle detected for {video_id}")

    snippet = {
        "title": title,
        "resourceId": {"videoId": video_id},
        "thumbnails": {"default": thumbnail},
        "channelTitle": byline[0] if byline else "unknown",
    }
    if channel_id:
        snippet["channelId"] = channel_id

    return {
        "id": {"kind": "youtube#video", "videoId": video_id},
        "snippet": snippet,
        "contentDetails": {
            "duration": _duration_from_candidates(_lockup_badges(lockup), video_id)
        },
    }


def _lockup_playlist_to_item(
    lockup: dict[str, Any], playlist_id: str
) -> dict[str, Any] | None:
    if playlist_id.startswith(MIX_PLAYLIST_PREFIX):
        logger.debug(f"lockup: skipping mix {playlist_id}")
        return None

    meta = lockup.get("metadata", {}).get("lockupMetadataViewModel", {})
    title = traverse_or_none(meta, ["title", "content"])
    if not title:
        logger.error(f"lockup: no title detected for {playlist_id}")
        title = "unknown"

    thumbnail = _lockup_thumbnail(
        traverse_or_none(
            lockup,
            [
                "contentImage",
                "collectionThumbnailViewModel",
                "primaryThumbnail",
                "thumbnailViewModel",
            ],
        )
    )
    item_count = next(
        (
            int(match.group().replace(",", ""))
            for badge in _lockup_badges(lockup)
            if (match := re.match(r"\d[\d,]*", badge))
        ),
        0,
    )

    # "<owner> · Playlist"; on a channel's own tab the owner is left out
    byline, channel_id = _lockup_byline(meta)
    snippet: dict[str, Any] = {
        "title": title,
        "thumbnails": {"default": thumbnail} if thumbnail else {},
        "channelTitle": byline[0] if len(byline) > 1 else "unknown",
    }
    if channel_id:
        snippet["channelId"] = channel_id

    return {
        "id": {"kind": "youtube#playlist", "playlistId": playlist_id},
        "contentDetails": {"itemCount": item_count},
        "snippet": snippet,
    }


def _lockup_to_item(lockup: dict[str, Any]) -> dict[str, Any] | None:
    """A `lockupViewModel` as the Data API item the older renderers give."""
    content_id = lockup.get("contentId")
    content_type = lockup.get("contentType")
    if not isinstance(content_id, str) or not content_id:
        logger.error("json_to_items: lockup without contentId, unable to process")
        return None

    if content_type == LOCKUP_VIDEO:
        return _lockup_video_to_item(lockup, content_id)
    if content_type == LOCKUP_PLAYLIST:
        return _lockup_playlist_to_item(lockup, content_id)

    logger.debug(f"json_to_items: skipping lockup {content_id} ({content_type})")
    return None


class jAPI(Client):  # noqa: N801 - public class name, used by backend and tests
    """
    Indirect access to YouTube data, without API
    using json where available
    """

    ytdata_regex: tuple[str, ...] = (
        r'window\["ytInitialData"] = (?={)',
        r"ytInitialData = (?={)",
    )

    endpoint: str = "https://www.youtube.com/"

    @staticmethod
    def _safe_text(node: Any, default: str = "unknown") -> str:
        if node is None:
            return default

        if isinstance(node, str):
            return node

        with contextlib.suppress(Exception):
            if isinstance(node, dict):
                if "simpleText" in node:
                    return node["simpleText"]
                if "runs" in node:
                    return (
                        "".join(
                            run.get("text", "")
                            for run in node.get("runs", [])
                            if isinstance(run, dict)
                        ).strip()
                        or default
                    )

        with contextlib.suppress(Exception):
            value = traverse(node, TEXT_PATH)
            if value:
                return value

        return default

    @classmethod
    def _extract_duration(cls, video: dict[str, Any], video_id: str) -> str:
        candidates: list[str] = []

        length_text = video.get("lengthText")
        if length_text:
            with contextlib.suppress(Exception):
                if "simpleText" in length_text:
                    candidates.append(length_text["simpleText"])
                else:
                    candidates.append(traverse(length_text, TEXT_PATH))

        for overlay in video.get("thumbnailOverlays", []):
            with contextlib.suppress(Exception):
                if "thumbnailOverlayTimeStatusRenderer" in overlay:
                    txt = overlay["thumbnailOverlayTimeStatusRenderer"].get("text", {})
                    if "simpleText" in txt:
                        candidates.append(txt["simpleText"])
                    else:
                        candidates.append(traverse(txt, TEXT_PATH))

        return _duration_from_candidates(candidates, video_id)

    def search(self, q: str, params: list[str] | None = None) -> dict[str, Any]:
        if not params:
            params = ["EgIQAQ%3D%3D", "EgIQAw%3D%3D"]

        result: list[dict[str, Any]] = []
        executor = self.executor

        futures = [executor.submit(self.run_search, q, param) for param in params]
        for future in futures:
            try:
                value = future.result()
                result.extend(value[: context.search_results])
            except Exception as e:
                logger.error(f"youtube search branch failed for query {q!r}: {e}")

        return json.loads(
            json.dumps(
                {"items": result},
                sort_keys=False,
                indent=1,
            )
        )

    def list_related_videos(self, video_id: str) -> dict[str, Any]:
        """
        returns related videos for a given video_id
        """
        query = {"v": video_id, "app": "desktop", "persist_app": 1}

        logger.debug(f"jAPI 'list_related_videos' triggered session.get: {video_id}")

        items = []

        result = self.session.get(self.endpoint + "watch", params=query)
        if result.status_code == 200:
            yt_data = self._find_yt_data(result.text)
            sections = traverse_or_none(yt_data, RELATED_VIDEOS_PATH) or []
            extracted_json = [
                entry
                for section in sections
                for entry in section.get("itemSectionRenderer", {}).get("contents", [])
            ]
            # the callers want videos, not the playlists YouTube mixes in
            items = [
                item
                for item in self.json_to_items(extracted_json)
                if "videoId" in item["id"]
            ]

        return json.loads(json.dumps({"items": items}, sort_keys=False, indent=1))

    def list_videos(self, ids: list[str]) -> dict[str, Any]:
        """
        list videos - EXPERIMENTAL, using exact search for ids,
        fall back to loading the watch page for the video
        (which doesn't reliably provide a duration for all variants).
        """
        items = []

        def job(id: str) -> list[dict[str, Any]]:
            results = self.pl_run_search(
                {
                    "search_query": '"' + id + '"',
                    "sp": "EgIQAQ%3D%3D",
                    "app": "desktop",
                    "persist_app": 1,
                }
            )

            normalized = []
            for result in results:
                with contextlib.suppress(Exception):
                    result.update({"id": result["id"]["videoId"]})
                    normalized.append(result)

            results = [result for result in normalized if result["id"] == id]

            if results:
                return results

            logger.debug(f"jAPI 'list_videos' triggered session.get: {id}")
            result = self.session.get(self.endpoint + "watch?v=" + id)
            if result.status_code == 200:
                yt_data = self._find_yt_data(result.text)

                if yt_data:
                    try:
                        extracted_json = traverse(yt_data, WATCH_VIDEO_PATH)
                        primary = _find_renderer(
                            extracted_json, "videoPrimaryInfoRenderer"
                        )
                        secondary = _find_renderer(
                            extracted_json, "videoSecondaryInfoRenderer"
                        )
                        owner = secondary["owner"]["videoOwnerRenderer"]
                        title = self._safe_text(primary["title"], default="unknown")
                        channel_title = self._safe_text(
                            owner["title"], default="unknown"
                        )
                        thumbnails = owner["thumbnail"]["thumbnails"][-1]

                        item = {
                            "id": id,
                            "snippet": {
                                "title": title,
                                "resourceId": {"videoId": id},
                                "thumbnails": {"default": thumbnails},
                                "channelTitle": channel_title,
                            },
                            "contentDetails": {"duration": "PT0S"},
                        }
                    except Exception as e:
                        logger.warning(
                            f"jAPI 'list_videos' watch fallback failed for {id}: {e}"
                        )
                    else:
                        return [item]

            return []

        if len(ids) == 1:
            items.extend(job(ids[0]))
        else:
            executor = self.executor
            for result_items in executor.map(job, ids):
                items.extend(result_items or [])

        return json.loads(
            json.dumps(
                {"items": items},
                sort_keys=False,
                indent=1,
            )
        )

    def list_playlists(self, ids: Collection[str]) -> dict[str, Any]:
        """
        list playlists - EXPERIMENTAL, using exact search for ids
        """

        items = []

        def job(id: str) -> list[dict[str, Any]]:
            results = self.pl_run_search(
                {
                    "search_query": '"' + id + '"',
                    "sp": "EgIQAw%3D%3D",
                    "app": "desktop",
                    "persist_app": 1,
                }
            )

            results = [
                {**result, "id": result["id"]["playlistId"]}
                for result in results
                if "playlistId" in result["id"]
            ]
            results = [result for result in results if result["id"] == id]

            if results:
                return results

            logger.debug(f"jAPI 'list_playlists' triggered session.get: {id}")
            result = self.session.get(self.endpoint + "playlist?list=" + id)
            if result.status_code == 200:
                item = self._playlist_from_sidebar(id, self._find_yt_data(result.text))
                if item:
                    return [item]

            return []

        if len(ids) == 1:
            items.extend(job(next(iter(ids))))
        else:
            executor = self.executor
            # make sure order is deterministic so that HTTP requests
            # are replayable in tests
            for result_items in executor.map(job, ids):
                items.extend(result_items or [])

        return json.loads(json.dumps({"items": items}, sort_keys=False, indent=1))

    @staticmethod
    def _playlist_from_sidebar(
        playlist_id: str, yt_data: dict[str, Any]
    ) -> dict[str, Any] | None:
        """A playlist described by the sidebar of its page, None if it has none."""
        try:
            sidebar = yt_data["sidebar"]["playlistSidebarRenderer"]["items"]
            primary = _find_renderer(sidebar, "playlistSidebarPrimaryInfoRenderer")
            secondary = _find_renderer(sidebar, "playlistSidebarSecondaryInfoRenderer")
            owner = secondary["videoOwner"]["videoOwnerRenderer"]

            item_count = int(
                traverse(primary["stats"][0], TEXT_PATH)
                .split(" ", 1)[0]
                .replace(",", "")
            )
            return {
                "contentDetails": {"itemCount": item_count},
                "id": playlist_id,
                "snippet": {
                    "channelTitle": traverse(owner["title"], TEXT_PATH),
                    "thumbnails": {"default": owner["thumbnail"]["thumbnails"][-1]},
                    "title": traverse(primary["title"], TEXT_PATH),
                },
            }
        except (KeyError, IndexError, TypeError, ValueError, AttributeError) as e:
            logger.warning(
                f"jAPI 'list_playlists' found no playlist {playlist_id} on its page: "
                f"{e!r}"
            )
            return None

    def list_playlistitems(
        self,
        playlist_id: str,
        page: str | None,  # noqa: ARG002 - the whole playlist is on one page
        max_results: int,
    ) -> dict[str, Any]:
        query = {"list": playlist_id, "app": "desktop", "persist_app": 1}
        logger.debug(f"jAPI 'list_playlistitems' triggered session.get: {playlist_id}")

        result = self.session.get(urljoin(self.endpoint, "playlist"), params=query)
        if result.status_code == 200:
            yt_data = self._find_yt_data(result.text)
            contents = traverse_or_none(yt_data, PLAYLIST_SECTION_CONTENTS_PATH)
            if not contents:
                logger.warning(
                    f"jAPI 'list_playlistitems' found no videos for {playlist_id}"
                )
                return {"items": []}
            if "playlistVideoListRenderer" in contents[0]:  # the older layout
                contents = contents[0]["playlistVideoListRenderer"]["contents"]
            items = self.json_to_items(contents)[:max_results]
            return json.loads(
                json.dumps(
                    {"nextPageToken": None, "items": items},
                    sort_keys=False,
                    indent=1,
                )
            )

        return {"items": []}

    def list_channelplaylists(self, channel_id: str | None) -> dict[str, Any]:
        """
        list playlists in a channel
        """
        if channel_id is None:
            return {"items": []}
        logger.debug(
            f"jAPI 'list_channelplaylists' triggered session.get: {channel_id}"
        )
        result = self.session.get(
            self.endpoint + "channel/" + channel_id + "/playlists"
        )

        yt_data = self._find_yt_data(result.text)
        extracted_json = deep_search(
            ["gridPlaylistRenderer", "lockupViewModel"], yt_data
        )

        try:
            # the channel page lists videos next to the playlists
            items = [
                item
                for item in self.json_to_items(extracted_json)
                if "playlistId" in item["id"]
            ]
            for item in items:
                item.update({"id": item["id"]["playlistId"]})
        except Exception as e:
            logger.error(f"jAPI 'list_channelplaylists' exception {e}")
            items = []

        return json.loads(json.dumps({"items": items}, sort_keys=False, indent=1))

    def run_search(self, search_query: str, sp: str) -> list[dict[str, Any]]:
        continuation: str | None = None
        results: list[dict[str, Any]] = []
        headers = {
            "User-Agent": "Mozilla/5.0",
            "accept-language": "en-US,en",
            "Content-Type": "application/json",
        }

        data: dict[str, Any] = {
            "context": {
                "client": {"clientName": "WEB", "clientVersion": "2.20200720.00.02"},
            }
        }

        query = {
            "query": search_query,
            "key": "AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8",
            "params": sp,
            "contentCheckOk": True,
            "racyCheckOk": True,
        }

        url = f"{urljoin(self.endpoint, 'youtubei/v1/search')}?{urlencode(query)}"

        while len(results) < context.search_results:
            payload = dict(data)
            if continuation:
                payload.update({"continuation": continuation})

            logger.debug(f"jAPI run_search triggered session.post: {search_query}")

            result = self.session.post(
                url=url,
                data=bytes(json.dumps(payload), encoding="utf-8"),
                headers=headers,
            )

            if result.status_code != 200:
                return results

            try:
                yt_data = json.loads(result.text)
            except Exception as e:
                logger.error(f"jAPI run_search invalid JSON for {search_query}: {e}")
                return results

            if not yt_data:
                logger.warning(f"jAPI run_search got an empty response: {search_query}")
                return results

            try:
                sections = traverse(yt_data, SECTION_LIST_RENDERER_CONTENTS_PATH)
            except KeyError:
                try:
                    sections = traverse(yt_data, CONTINUATION_ITEMS_PATH)
                except KeyError:
                    logger.warning(
                        "jAPI run_search could not find search sections "
                        f"for query {search_query}"
                    )
                    return results

            extracted_json = None
            continuation_renderer = None

            for s in sections:
                if "itemSectionRenderer" in s:
                    extracted_json = s["itemSectionRenderer"]["contents"]
                    results.extend(self.json_to_items(extracted_json))
                if "continuationItemRenderer" in s:
                    continuation_renderer = s["continuationItemRenderer"]

            if not continuation_renderer:
                return results

            continuation = continuation_renderer["continuationEndpoint"][
                "continuationCommand"
            ]["token"]

        return results

    def pl_run_search(self, query: dict[str, Any]) -> list[dict[str, Any]]:
        logger.debug(f"jAPI pl_run_search triggered session.get: {query}")
        result = self.session.get(urljoin(self.endpoint, "results"), params=query)
        if result.status_code == 200:
            yt_data = self._find_yt_data(result.text)
            if yt_data:
                try:
                    sections = traverse(yt_data, SECTION_LIST_RENDERER_CONTENTS_PATH)
                    for section in sections:
                        if "itemSectionRenderer" in section:
                            extracted_json = section["itemSectionRenderer"].get(
                                "contents", []
                            )
                            return self.json_to_items(extracted_json)
                except Exception as e:
                    logger.warning(f"jAPI pl_run_search parse failed: {e}")

        return []

    @staticmethod
    def _find_yt_data(text: str) -> dict[str, Any]:
        decoder = json.JSONDecoder()
        for r in jAPI.ytdata_regex:
            result = re.search(r, text)
            if not result:
                continue

            try:
                # raw_decode ignores whatever follows the object, and knows
                # that a `};` inside a string is not the end of it
                data, _ = decoder.raw_decode(text, result.end())
            except json.JSONDecodeError as e:
                logger.debug(f"_find_yt_data exception {e}; trying the next pattern")
                continue
            return data

        msg = "No data found on page"
        logger.error(msg)
        raise NoYtDataError(msg)

    @staticmethod
    def _grid_thumbnail_renderer_key(playlist: dict[str, Any]) -> str:
        if "playlistVideoThumbnailRenderer" in playlist["thumbnailRenderer"]:
            return "playlistVideoThumbnailRenderer"
        if "playlistCustomThumbnailRenderer" in playlist["thumbnailRenderer"]:
            return "playlistCustomThumbnailRenderer"
        msg = f"could not find playlist Thumbnail Renderer {playlist}"
        raise KeyError(msg)

    @staticmethod
    def json_to_items(result_json: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if len(result_json) > 1 and "itemSectionRenderer" in result_json[1]:
            result_json = result_json[1]["itemSectionRenderer"]["contents"]

        items = []

        for content in result_json:
            base = []

            content_renderers = [
                "videoRenderer",
                "compactVideoRenderer",
                "playlistVideoRenderer",
            ]

            base = [renderer for renderer in content_renderers if renderer in content]

            if base:
                video = content[base[0]]

                try:
                    video_id = video["videoId"]
                except Exception as e:
                    logger.error(
                        f"json_to_items: no videoId detected, unable to process; ({e})"
                    )
                    continue

                try:
                    title = video["title"]["simpleText"]
                except Exception:
                    try:
                        title = traverse(video["title"], TEXT_PATH)
                    except Exception as e:
                        logger.error(
                            f"json_to_items: no title detected for {video_id}; ({e})"
                        )
                        title = "unknown"

                if title in ["[Private video]", "[Deleted video]"]:
                    logger.info(f"skipping video {video_id}: {title}")
                    continue

                byline = next(
                    (
                        field
                        for field in ("longBylineText", "shortBylineText")
                        if field in video
                    ),
                    "unknown",
                )
                if byline == "unknown":
                    logger.error(f"json_to_items: no byline detected for {video_id};")

                try:
                    thumbnails = video["thumbnail"]["thumbnails"][-1]
                    thumbnails["url"] = thumbnails["url"].split("?", 1)[0]
                except Exception as e:
                    logger.error(
                        f"json_to_items: no thumbnails detected for {video_id}; ({e})"
                    )
                    thumbnails = {
                        "url": f"https://i.ytimg.com/vi/{video_id}/default.jpg"
                    }

                try:
                    channel_title = traverse(video[byline], TEXT_PATH)
                except Exception as e:
                    logger.error(
                        f"json_to_items: no channelTitle detected for {video_id}; ({e})"
                    )
                    channel_title = "unknown"

                item = {
                    "id": {"kind": "youtube#video", "videoId": video_id},
                    "snippet": {
                        "title": title,
                        "resourceId": {"videoId": video_id},
                        "thumbnails": {"default": thumbnails},
                        "channelTitle": channel_title,
                    },
                }

                duration = jAPI._extract_duration(video, video_id)
                item.update({"contentDetails": {"duration": duration}})

                try:
                    channel_id = video[byline]["runs"][0]["navigationEndpoint"][
                        "browseEndpoint"
                    ]["browseId"]
                    logger.debug(f"video {video_id} channelId: {channel_id}")
                    item["snippet"].update({"channelId": channel_id})
                except Exception as e:
                    logger.debug(f"video {video_id}, no channelId detected; ({e})")

                items.append(item)

            elif "radioRenderer" in content:
                continue

            elif "playlistRenderer" in content:
                playlist = content["playlistRenderer"]

                try:
                    thumbnails = playlist["thumbnails"][0]["thumbnails"][-1]
                    thumbnails["url"] = thumbnails["url"].split("?", 1)[0]
                except Exception as e:
                    logger.error(f"thumbnail exception {e}, {playlist['playlistId']}")
                    continue

                try:
                    channel_title = traverse(playlist["longBylineText"], TEXT_PATH)
                except Exception as e:
                    logger.error(
                        f"channelTitle exception {e}, {playlist['playlistId']}"
                    )
                    channel_title = "unknown"

                item = {
                    "id": {
                        "kind": "youtube#playlist",
                        "playlistId": playlist["playlistId"],
                    },
                    "contentDetails": {"itemCount": int(playlist["videoCount"])},
                    "snippet": {
                        "title": playlist["title"]["simpleText"],
                        "thumbnails": {"default": thumbnails},
                        "channelTitle": channel_title,
                    },
                }
                items.append(item)

            elif "lockupViewModel" in content:
                item = _lockup_to_item(content["lockupViewModel"])
                if item:
                    items.append(item)

            elif "gridPlaylistRenderer" in content:
                playlist = content["gridPlaylistRenderer"]

                try:
                    ptr = jAPI._grid_thumbnail_renderer_key(playlist)

                    thumbnails = playlist["thumbnailRenderer"][ptr]["thumbnail"][
                        "thumbnails"
                    ][-1]
                    thumbnails["url"] = thumbnails["url"].split("?", 1)[0]
                except Exception as e:
                    logger.error(f"thumbnail exception {e}, {playlist['playlistId']}")
                    thumbnails = None

                try:
                    item_count = int(
                        playlist["videoCountShortText"]["simpleText"].replace(",", "")
                    )
                except Exception as e:
                    logger.error(f"itemCount exception {e}, {playlist['playlistId']}")
                    item_count = 0

                item = {
                    "id": {
                        "kind": "youtube#playlist",
                        "playlistId": playlist["playlistId"],
                    },
                    "contentDetails": {"itemCount": item_count},
                    "snippet": {
                        "title": traverse(playlist["title"], TEXT_PATH),
                        "thumbnails": {"default": thumbnails},
                        "channelTitle": "unknown",
                    },
                }
                items.append(item)

        deduped = {json.dumps(item, sort_keys=True): item for item in items}
        return list(deduped.values())
