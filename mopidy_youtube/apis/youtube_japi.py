import json
import re
from concurrent.futures import as_completed
from concurrent.futures.thread import ThreadPoolExecutor
from urllib.parse import urlencode, urljoin

from mopidy_youtube import logger
from mopidy_youtube.comms import Client
from mopidy_youtube.youtube import Video


def traverse(input_dict, keys):
    internal_dict_value = input_dict
    for key in keys:
        if isinstance(internal_dict_value, list):
            internal_dict_value = internal_dict_value[key]
        else:
            internal_dict_value = internal_dict_value.get(key, None)
        if internal_dict_value is None:
            raise KeyError
    return internal_dict_value


sectionListRendererContentsPath = [
    "contents",
    "twoColumnSearchResultsRenderer",
    "primaryContents",
    "sectionListRenderer",
    "contents",
]

continuationItemsPath = [
    "onResponseReceivedCommands",
    0,
    "appendContinuationItemsAction",
    "continuationItems",
]

watchVideoPath = [
    "contents",
    "twoColumnWatchNextResults",
    "results",
    "results",
    "contents",
]

relatedVideosPath = [
    "contents",
    "twoColumnWatchNextResults",
    "secondaryResults",
    "secondaryResults",
    "results",
]

playlistBasePath = [
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
    0,
]

listPlaylistitemsPath = playlistBasePath + [
    "playlistVideoListRenderer",
    "contents",
]

listChannelPlaylistsPath = playlistBasePath + ["shelfRenderer", "content"]

textPath = ["runs", 0, "text"]


class jAPI(Client):
    """
    Indirect access to YouTube data, without API
    using json where available
    """

    ytdata_regex = (
        r'window\["ytInitialData"] = ({.*?});',
        r"ytInitialData = ({.*?});",
    )

    endpoint = "https://www.youtube.com/"

    @classmethod
    def search(cls, q):
        """
        search for videos and playlists
        """
        result = cls.run_search(q)
        return json.loads(
            json.dumps(
                {
                    "items": result
                    # [
                    #     x for _, x in zip(range(Video.search_results), result)
                    # ]
                },
                sort_keys=False,
                indent=1,
            )
        )

    @classmethod
    def list_related_videos(cls, video_id):
        """
        returns related videos for a given video_id
        """
        query = {"v": video_id, "app": "desktop", "persist_app": 1}

        logger.debug(
            f"jAPI 'list_related_videos' triggered session.get: {video_id}"
        )

        result = cls.session.get(cls.endpoint + "watch", params=query)
        if result.status_code == 200:
            yt_data = cls._find_yt_data(result.text)
            extracted_json = traverse(yt_data, relatedVideosPath)
            items = cls.json_to_items(extracted_json)

        return json.loads(
            json.dumps({"items": items}, sort_keys=False, indent=1)
        )

    @classmethod
    def list_videos(cls, ids):
        """
        list videos - EXPERIMENTAL, using exact search for ids,
        fall back to loading the watch page for the video
        (which doesn't provide a duration).
        """
        items = []

        # for id in ids:
        def job(id):

            results = cls.pl_run_search(
                {
                    "search_query": '"' + id + '"',
                    "sp": "EgIQAQ%3D%3D",
                    "app": "desktop",
                    "persist_app": 1,
                }
            )

            for result in results:
                result.update({"id": result["id"]["videoId"]})
                if result["id"] in ids:
                    items.append(result)

            if results:
                return results

            else:

                logger.info(f"jAPI 'list_videos' triggered session.get: {id}")
                result = cls.session.get(cls.endpoint + "watch?v=" + id)
                if result.status_code == 200:
                    yt_data = cls._find_yt_data(result.text)
                    if yt_data:
                        extracted_json = traverse(yt_data, watchVideoPath)

                        title = traverse(
                            extracted_json[0]["videoPrimaryInfoRenderer"][
                                "title"
                            ],
                            textPath,
                        )
                        channelTitle = traverse(
                            extracted_json[1]["videoSecondaryInfoRenderer"][
                                "owner"
                            ]["videoOwnerRenderer"]["title"],
                            textPath,
                        )
                        thumbnails = extracted_json[1][
                            "videoSecondaryInfoRenderer"
                        ]["owner"]["videoOwnerRenderer"]["thumbnail"][
                            "thumbnails"
                        ][
                            -1
                        ]

                        item = {
                            "id": id,
                            "snippet": {
                                "title": title,
                                "resourceId": {"videoId": id},
                                "thumbnails": {"default": thumbnails},
                                "channelTitle": channelTitle,
                            },
                            "contentDetails": {
                                "duration": "PT0S"
                            },  # where to find this...?
                        }
                        return [item]

        if len(ids) == 1:
            items.extend(job(ids[0]))
        else:
            with ThreadPoolExecutor() as executor:
                futures = [executor.submit(job, id) for id in ids]
                for future in as_completed(futures):
                    items.extend(future.result())

        return json.loads(
            json.dumps({"items": items}, sort_keys=False, indent=1,)
        )

    @classmethod
    def list_playlists(cls, ids):
        """
        list playlists - EXPERIMENTAL, using exact search for ids
        """

        items = []

        rs = [
            {
                "search_query": '"' + id + '"',
                "sp": "EgIQAw%3D%3D",
                "app": "desktop",
                "persist_app": 1,
            }
            for id in ids
        ]
        results = [
            result
            for r in rs
            for result in cls.pl_run_search(r)
            if result["id"]["playlistId"] in ids
        ]
        for result in results:
            result.update({"id": result["id"]["playlistId"]})
            items.extend([result])

        return json.loads(
            json.dumps({"items": items}, sort_keys=False, indent=1)
        )

    @classmethod
    def list_playlistitems(cls, id, page, max_results):
        query = {"list": id, "app": "desktop", "persist_app": 1}
        logger.debug(f"jAPI 'list_playlistitems' triggered session.get: {id}")

        items = []

        result = cls.session.get(
            urljoin(cls.endpoint, "playlist"), params=query
        )
        if result.status_code == 200:
            yt_data = cls._find_yt_data(result.text)
            extracted_json = traverse(yt_data, listPlaylistitemsPath)
            items = cls.json_to_items(extracted_json)

            return json.loads(
                json.dumps(
                    {"nextPageToken": None, "items": items},
                    sort_keys=False,
                    indent=1,
                )
            )

        return []

    @classmethod
    def list_channelplaylists(cls, channel_id):
        """
        list playlists in a channel
        """
        logger.debug(
            f"jAPI 'list_channelplaylists' triggered session.get: {channel_id}"
        )
        result = cls.session.get(cls.endpoint + "channel/" + channel_id)

        yt_data = cls._find_yt_data(result.text)
        extracted_json = traverse(yt_data, listChannelPlaylistsPath)

        renderers = ["expandedShelfContentsRenderer", "horizontalListRenderer"]
        extracted_json = [
            extracted_json[renderer]["items"]
            for renderer in renderers
            if renderer in extracted_json
        ][0]

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

        return json.loads(
            json.dumps({"items": items}, sort_keys=False, indent=1)
        )

    @classmethod
    def run_search(cls, search_query):
        # with thanks (or perhaps apologies) to pytube:
        # https://pytube.io/en/stable/api.html#pytube.contrib.search.Search.fetch_and_parse

        continuation = None
        results = []
        headers = {
            "User-Agent": "Mozilla/5.0",
            "accept-language": "en-US,en",
            "Content-Type": "application/json",
        }

        data = {
            "context": {
                "client": {
                    "clientName": "WEB",
                    "clientVersion": "2.20200720.00.02",
                },
            },
        }

        query = {
            "query": search_query,
            "key": "AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8",
            "contentCheckOk": True,
            "racyCheckOk": True,
        }

        url = (
            f'{urljoin(cls.endpoint, "youtubei/v1/search")}?{urlencode(query)}'
        )

        while len(results) < Video.search_results:

            if continuation:
                data.update({"continuation": continuation})

            logger.debug(
                f"jAPI run_search triggered session.post: {search_query}"
            )

            result = cls.session.post(
                url=url,
                data=bytes(json.dumps(data), encoding="utf-8"),
                headers=headers,
            )

            if result.status_code == 200:
                yt_data = json.loads(result.text)
                if yt_data:
                    # Initial result is handled by try block, continuations by except block
                    try:
                        sections = traverse(
                            yt_data, sectionListRendererContentsPath
                        )
                    except KeyError:
                        sections = traverse(yt_data, continuationItemsPath)

                    extracted_json = None
                    continuation_renderer = None

                    for s in sections:
                        if "itemSectionRenderer" in s:
                            extracted_json = s["itemSectionRenderer"][
                                "contents"
                            ]
                        if "continuationItemRenderer" in s:
                            continuation_renderer = s[
                                "continuationItemRenderer"
                            ]

                    # If the continuationItemRenderer doesn't exist, assume no further results
                    if continuation_renderer:
                        continuation = continuation_renderer[
                            "continuationEndpoint"
                        ]["continuationCommand"]["token"]
                    else:
                        continuation = None
                    results.extend(cls.json_to_items(extracted_json))

        return results

    @classmethod
    def pl_run_search(cls, query):
        logger.debug(f"jAPI pl_run_search triggered session.get: {query}")
        result = cls.session.get(urljoin(cls.endpoint, "results"), params=query)
        if result.status_code == 200:
            yt_data = None
            yt_data = cls._find_yt_data(result.text)
            if yt_data:
                extracted_json = traverse(
                    yt_data, sectionListRendererContentsPath
                )[0]["itemSectionRenderer"]["contents"]
                results = cls.json_to_items(extracted_json)
                return results

        return []

    def _find_yt_data(text):
        for r in jAPI.ytdata_regex:
            result = re.search(r, text)
            if not result:
                continue

            try:
                return json.loads(result.group(1))
            except Exception as e:
                logger.debug(f"_find_yt_data exception {e}; probably ok")
                return json.loads(result.group(1)[: e.pos])

        logger.error("No data found on page")
        raise Exception("No data found on page")

    def json_to_items(result_json):
        if len(result_json) > 1 and "itemSectionRenderer" in result_json[1]:
            result_json = result_json[1]["itemSectionRenderer"]["contents"]

        items = []

        for content in result_json:

            base = []

            contentRenderers = [
                "videoRenderer",
                "compactVideoRenderer",
                "playlistVideoRenderer",
            ]

            base = [
                renderer for renderer in contentRenderers if renderer in content
            ]

            if base:

                video = content[base[0]]

                byline = [
                    bl
                    for bl in ["longBylineText", "shortBylineText"]
                    if bl in video
                ][0]

                try:
                    videoId = video["videoId"]
                except Exception as e:
                    # videoID = "Unknown"
                    logger.error("json_to_items videoId exception %s" % e)
                    continue

                try:
                    title = video["title"]["simpleText"]
                except Exception:
                    try:
                        title = traverse(video["title"], textPath)
                    except Exception as e:
                        logger.error(f"json_to_items title exception {e}")
                        continue

                try:
                    thumbnails = video["thumbnail"]["thumbnails"][-1]
                    thumbnails["url"] = thumbnails["url"].split("?", 1)[
                        0
                    ]  # is the rest tracking stuff? Omit
                except Exception as e:
                    logger.error(f"json_to_items thumbnail exception {e}")

                try:
                    channelTitle = traverse(video[byline], textPath)
                except Exception as e:
                    # channelTitle = "Unknown"
                    logger.error(
                        f"json_to_items channelTitle exception {e}, {title}"
                    )
                    continue

                item = {
                    "id": {"kind": "youtube#video", "videoId": videoId},
                    "snippet": {
                        "title": title,
                        "resourceId": {"videoId": videoId},
                        "thumbnails": {"default": thumbnails,},
                        "channelTitle": channelTitle,
                    },
                }

                try:
                    duration_text = video["lengthText"]["simpleText"]
                    duration = "PT" + Client.format_duration(
                        re.match(Client.time_regex, duration_text)
                    )
                    logger.debug("duration: ", duration)
                except Exception as e:
                    logger.warn(f"no video-time, possibly live: {e}")
                    duration = "PT0S"

                item.update({"contentDetails": {"duration": duration}})

                try:
                    channelId = video[byline]["runs"][0]["navigationEndpoint"][
                        "browseEndpoint"
                    ]["browseId"]
                    logger.debug(channelId)
                    item["snippet"].update({"channelId": channelId})
                except Exception as e:
                    logger.error(f"channelId exception {e}, {title}")

                items.append(item)

            elif "radioRenderer" in content:
                continue

            elif "playlistRenderer" in content:

                playlist = content["playlistRenderer"]

                try:
                    thumbnails = playlist["thumbnails"][0]["thumbnails"][-1]
                    thumbnails["url"] = thumbnails["url"].split("?", 1)[
                        0
                    ]  # is the rest tracking stuff? Omit
                except Exception as e:
                    logger.error(
                        f"thumbnail exception {e}, {playlist['playlistId']}"
                    )

                try:
                    channelTitle = traverse(
                        playlist["longBylineText"], textPath
                    )
                except Exception as e:
                    logger.error(
                        f"channelTitle exception {e}, {playlist['playlistId']}"
                    )

                item = {
                    "id": {
                        "kind": "youtube#playlist",
                        "playlistId": playlist["playlistId"],
                    },
                    "contentDetails": {"itemCount": playlist["videoCount"]},
                    "snippet": {
                        "title": playlist["title"]["simpleText"],
                        "thumbnails": {"default": thumbnails,},
                        "channelTitle": channelTitle,
                    },
                }
                items.append(item)

            elif "gridPlaylistRenderer" in content:

                playlist = content["gridPlaylistRenderer"]

                try:
                    thumbnails = playlist["thumbnailRenderer"][
                        "playlistVideoThumbnailRenderer"
                    ]["thumbnail"]["thumbnails"][-1]
                    thumbnails["url"] = thumbnails["url"].split("?", 1)[
                        0
                    ]  # is the rest tracking stuff? Omit
                except Exception as e:
                    logger.error(
                        f"thumbnail exception {e}, {playlist['playlistId']}"
                    )

                try:
                    itemCount = int(
                        playlist["videoCountShortText"]["simpleText"].replace(
                            ",", ""
                        )
                    )
                except Exception as e:
                    logger.error(
                        f"itemCount exception {e}, {playlist['playlistId']}"
                    )
                    itemCount = 0

                item = {
                    "id": {
                        "kind": "youtube#playlist",
                        "playlistId": playlist["playlistId"],
                    },
                    "contentDetails": {"itemCount": itemCount,},
                    "snippet": {
                        "title": traverse(playlist["title"], textPath),
                        "thumbnails": {"default": thumbnails,},
                        "channelTitle": "unknown",  # note: do better
                    },
                }
                items.append(item)

        # remove duplicates
        items[:] = [
            json.loads(t)
            for t in {json.dumps(d, sort_keys=True) for d in items}
        ]

        return items
