from __future__ import annotations

import contextlib
import json
import os
import re
from concurrent.futures.thread import ThreadPoolExecutor
from typing import Any
from urllib.parse import urlencode, urljoin

from mopidy_youtube import logger
from mopidy_youtube.apis import require_session
from mopidy_youtube.apis.json_paths import (
    CONTINUATION_ITEMS_PATH,
    LIST_PLAYLIST_ITEMS_PATH,
    RELATED_VIDEOS_PATH,
    SECTION_LIST_RENDERER_CONTENTS_PATH,
    TEXT_PATH,
    WATCH_VIDEO_PATH,
    deep_search,
    traverse,
)
from mopidy_youtube.comms import Client
from mopidy_youtube.timeformat import format_duration
from mopidy_youtube.youtube import Video


class NoYtDataError(Exception):
    """Raised when a YouTube page contains no ytInitialData payload."""


class jAPI(Client):  # noqa: N801 - public class name, used by backend and tests
    """
    Indirect access to YouTube data, without API
    using json where available
    """

    _executor: ThreadPoolExecutor | None = None

    @classmethod
    def get_executor(cls) -> ThreadPoolExecutor:
        if cls._executor is None:
            cls._executor = ThreadPoolExecutor(
                max_workers=max(2, min(8, (os.cpu_count() or 1) + 2))
            )
        return cls._executor

    ytdata_regex: tuple[str, ...] = (
        r'window\["ytInitialData"] = ({.*?});',
        r"ytInitialData = ({.*?});",
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

        for raw_candidate in candidates:
            candidate = (raw_candidate or "").strip()
            if not candidate:
                continue

            lowered = candidate.lower()
            if lowered in {"live", "upcoming", "premiere", "shorts"}:
                logger.info(
                    f"video {video_id} marked as {candidate}; treating as non-playable duration"
                )
                return "PT0S"

            if re.fullmatch(r"\d+:\d{2}(:\d{2})?", candidate):
                duration = "PT" + format_duration(candidate)
                logger.debug(f"video {video_id} duration: {duration}")
                return duration

        logger.warning(f"video {video_id} no video-time, possibly live")
        return "PT0S"

    @classmethod
    def search(cls, q: str, params: list[str] | None = None) -> dict[str, Any]:
        if not params:
            params = ["EgIQAQ%3D%3D", "EgIQAw%3D%3D"]

        result: list[dict[str, Any]] = []
        executor = cls.get_executor()

        futures = [executor.submit(cls.run_search, q, param) for param in params]
        for future in futures:
            try:
                value = future.result()
                result.extend(value[: int(Video.search_results)])
            except Exception as e:
                logger.error(f"youtube search branch failed for query {q!r}: {e}")

        return json.loads(
            json.dumps(
                {"items": result},
                sort_keys=False,
                indent=1,
            )
        )

    @classmethod
    def list_related_videos(cls, video_id: str) -> dict[str, Any]:
        """
        returns related videos for a given video_id
        """
        query = {"v": video_id, "app": "desktop", "persist_app": 1}

        logger.debug(f"jAPI 'list_related_videos' triggered session.get: {video_id}")

        items = []

        result = require_session(cls).get(cls.endpoint + "watch", params=query)
        if result.status_code == 200:
            yt_data = cls._find_yt_data(result.text)
            extracted_json = traverse(yt_data, RELATED_VIDEOS_PATH)
            items = cls.json_to_items(extracted_json)

        return json.loads(json.dumps({"items": items}, sort_keys=False, indent=1))

    @classmethod
    def list_videos(cls, ids: list[str]) -> dict[str, Any]:
        """
        list videos - EXPERIMENTAL, using exact search for ids,
        fall back to loading the watch page for the video
        (which doesn't reliably provide a duration for all variants).
        """
        items = []

        def job(id: str) -> list[dict[str, Any]]:
            results = cls.pl_run_search(
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
            result = require_session(cls).get(cls.endpoint + "watch?v=" + id)
            if result.status_code == 200:
                yt_data = cls._find_yt_data(result.text)

                if yt_data:
                    try:
                        extracted_json = traverse(yt_data, WATCH_VIDEO_PATH)
                        title = cls._safe_text(
                            extracted_json[0]["videoPrimaryInfoRenderer"]["title"],
                            default="unknown",
                        )
                        channel_title = cls._safe_text(
                            extracted_json[1]["videoSecondaryInfoRenderer"]["owner"][
                                "videoOwnerRenderer"
                            ]["title"],
                            default="unknown",
                        )
                        thumbnails = extracted_json[1]["videoSecondaryInfoRenderer"][
                            "owner"
                        ]["videoOwnerRenderer"]["thumbnail"]["thumbnails"][-1]

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
            executor = cls.get_executor()
            for result_items in executor.map(job, ids):
                items.extend(result_items or [])

        return json.loads(
            json.dumps(
                {"items": items},
                sort_keys=False,
                indent=1,
            )
        )

    @classmethod
    def list_playlists(cls, ids: list[str]) -> dict[str, Any]:
        """
        list playlists - EXPERIMENTAL, using exact search for ids
        """

        items = []

        def job(id: str) -> list[dict[str, Any]]:
            results = cls.pl_run_search(
                {
                    "search_query": '"' + id + '"',
                    "sp": "EgIQAw%3D%3D",
                    "app": "desktop",
                    "persist_app": 1,
                }
            )

            for result in results:
                result.update({"id": result["id"]["playlistId"]})

            results = [result for result in results if result["id"] == id]

            if results:
                return results

            logger.debug(f"jAPI 'list_playlists' triggered session.get: {id}")
            result = require_session(cls).get(cls.endpoint + "playlist?list=" + id)
            if result.status_code == 200:
                yt_data = cls._find_yt_data(result.text)

                if yt_data:
                    extracted_json = yt_data["sidebar"]["playlistSidebarRenderer"][
                        "items"
                    ]

                    title = traverse(
                        extracted_json[0]["playlistSidebarPrimaryInfoRenderer"][
                            "title"
                        ],
                        TEXT_PATH,
                    )

                    channel_title = traverse(
                        extracted_json[1]["playlistSidebarSecondaryInfoRenderer"][
                            "videoOwner"
                        ]["videoOwnerRenderer"]["title"],
                        TEXT_PATH,
                    )

                    thumbnails = extracted_json[1][
                        "playlistSidebarSecondaryInfoRenderer"
                    ]["videoOwner"]["videoOwnerRenderer"]["thumbnail"]["thumbnails"][-1]

                    item_count = int(
                        traverse(
                            extracted_json[0]["playlistSidebarPrimaryInfoRenderer"][
                                "stats"
                            ][0],
                            TEXT_PATH,
                        )
                        .split(" ", 1)[0]
                        .replace(",", "")
                    )

                    item = {
                        "contentDetails": {"itemCount": item_count},
                        "id": id,
                        "snippet": {
                            "channelTitle": channel_title,
                            "thumbnails": {"default": thumbnails},
                            "title": title,
                        },
                    }

                    return [item]

            return []

        if len(ids) == 1:
            items.extend(job(ids[0]))
        else:
            executor = cls.get_executor()
            # make sure order is deterministic so that HTTP requests
            # are replayable in tests
            for result_items in executor.map(job, ids):
                items.extend(result_items or [])

        return json.loads(json.dumps({"items": items}, sort_keys=False, indent=1))

    @classmethod
    def list_playlistitems(
        cls,
        id: str,
        page: str | None,  # noqa: ARG003 - kept for API interface parity
        max_results: int,
    ) -> dict[str, Any] | list[Any]:
        query = {"list": id, "app": "desktop", "persist_app": 1}
        logger.debug(f"jAPI 'list_playlistitems' triggered session.get: {id}")

        items = []

        result = require_session(cls).get(
            urljoin(cls.endpoint, "playlist"), params=query
        )
        if result.status_code == 200:
            yt_data = cls._find_yt_data(result.text)
            extracted_json = traverse(yt_data, LIST_PLAYLIST_ITEMS_PATH)
            items = cls.json_to_items(extracted_json)
            items = items[:max_results]
            return json.loads(
                json.dumps(
                    {"nextPageToken": None, "items": items},
                    sort_keys=False,
                    indent=1,
                )
            )

        return []

    @classmethod
    def list_channelplaylists(cls, channel_id: str) -> dict[str, Any]:
        """
        list playlists in a channel
        """
        logger.debug(
            f"jAPI 'list_channelplaylists' triggered session.get: {channel_id}"
        )
        result = require_session(cls).get(
            cls.endpoint + "channel/" + channel_id + "/playlists"
        )

        yt_data = cls._find_yt_data(result.text)
        extracted_json = deep_search(["gridPlaylistRenderer"], yt_data)

        try:
            items = cls.json_to_items(extracted_json)
            [
                item.update({"id": item["id"]["playlistId"]})
                for item in items
                if "playlistId" in item["id"]
            ]
        except Exception as e:
            logger.error(f"jAPI 'list_channelplaylists' exception {e}")
            items = []

        return json.loads(json.dumps({"items": items}, sort_keys=False, indent=1))

    @classmethod
    def run_search(cls, search_query: str, sp: str) -> list[dict[str, Any]]:
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

        url = f"{urljoin(cls.endpoint, 'youtubei/v1/search')}?{urlencode(query)}"

        while len(results) < int(Video.search_results):
            payload = dict(data)
            if continuation:
                payload.update({"continuation": continuation})

            logger.debug(f"jAPI run_search triggered session.post: {search_query}")

            result = require_session(cls).post(
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

            if yt_data:
                try:
                    sections = traverse(yt_data, SECTION_LIST_RENDERER_CONTENTS_PATH)
                except KeyError:
                    try:
                        sections = traverse(yt_data, CONTINUATION_ITEMS_PATH)
                    except KeyError:
                        logger.warning(
                            f"jAPI run_search could not find search sections for query {search_query}"
                        )
                        return results

                extracted_json = None
                continuation_renderer = None

                for s in sections:
                    if "itemSectionRenderer" in s:
                        extracted_json = s["itemSectionRenderer"]["contents"]
                        results.extend(cls.json_to_items(extracted_json))
                    if "continuationItemRenderer" in s:
                        continuation_renderer = s["continuationItemRenderer"]

                if continuation_renderer:
                    continuation = continuation_renderer["continuationEndpoint"][
                        "continuationCommand"
                    ]["token"]
                else:
                    return results

        return results

    @classmethod
    def pl_run_search(cls, query: dict[str, Any]) -> list[dict[str, Any]]:
        logger.debug(f"jAPI pl_run_search triggered session.get: {query}")
        result = require_session(cls).get(
            urljoin(cls.endpoint, "results"), params=query
        )
        if result.status_code == 200:
            yt_data = cls._find_yt_data(result.text)
            if yt_data:
                try:
                    sections = traverse(yt_data, SECTION_LIST_RENDERER_CONTENTS_PATH)
                    for section in sections:
                        if "itemSectionRenderer" in section:
                            extracted_json = section["itemSectionRenderer"].get(
                                "contents", []
                            )
                            return cls.json_to_items(extracted_json)
                except Exception as e:
                    logger.warning(f"jAPI pl_run_search parse failed: {e}")

        return []

    @staticmethod
    def _find_yt_data(text: str) -> dict[str, Any]:
        for r in jAPI.ytdata_regex:
            result = re.search(r, text)
            if not result:
                continue

            try:
                return json.loads(result.group(1))
            except json.JSONDecodeError as e:
                logger.debug(f"_find_yt_data exception {e}; probably ok")
                return json.loads(result.group(1)[: e.pos])

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

                try:
                    channel_title = traverse(playlist["longBylineText"], TEXT_PATH)
                except Exception as e:
                    logger.error(
                        f"channelTitle exception {e}, {playlist['playlistId']}"
                    )

                item = {
                    "id": {
                        "kind": "youtube#playlist",
                        "playlistId": playlist["playlistId"],
                    },
                    "contentDetails": {"itemCount": int(playlist["videoCount"])},
                    "snippet": {
                        "title": playlist["title"]["simpleText"],
                        "thumbnails": {
                            "default": thumbnails  # pyright: ignore[reportPossiblyUnboundVariable]
                        },
                        "channelTitle": channel_title,  # pyright: ignore[reportPossiblyUnboundVariable]
                    },
                }
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
