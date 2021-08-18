import json
import re
from urllib.parse import urlencode, urljoin

from mopidy_youtube import logger
from mopidy_youtube.apis.youtube_scrapi import scrAPI
from mopidy_youtube.youtube import Video


# JSON based scrAPI
class jAPI(scrAPI):

    endpoint = "https://www.youtube.com/"

    @classmethod
    def search(cls, q):
        """
        search for videos and playlists
        """

        logger.info(f"jAPI search triggered session.get: {q}")

        result = cls.run_search(q)

        return json.loads(
            json.dumps(
                {
                    "items": [
                        x for _, x in zip(range(Video.search_results), result)
                    ]
                },
                sort_keys=False,
                indent=1,
            )
        )

    @classmethod
    def list_playlistitems(cls, id, page, max_results):
        query = {"list": id, "app": "desktop", "persist_app": 1}
        logger.info(f"bs4api list_playlistitems triggered session.get: {id}")
        ajax_css = "button[data-uix-load-more-href]"

        items = []
        videos = []

        if page == "":
            result = cls.session.get(
                urljoin(cls.endpoint, "playlist"), params=query
            )
            if result.status_code == 200:
                soup = BeautifulSoup(result.text, "html.parser")
        else:
            result = cls.session.get(urljoin(cls.endpoint, page))
            if result.status_code == 200:
                soup = BeautifulSoup(
                    "".join(result.json().values()), "html.parser"
                )
        if soup:
            # get load more button
            full_ajax = soup.select(ajax_css)
            if len(full_ajax) > 0:
                ajax = full_ajax[0]["data-uix-load-more-href"]
            else:
                ajax = None
            videos = [
                video
                for video in soup.find_all("tr", {"class": "pl-video"})
                if all(
                    [
                        video.find(class_="timestamp"),
                        video.find(class_="pl-video-owner"),
                    ]
                )
            ]

            if not videos:
                logger.info(
                    "nothing in the soup, trying japi list_playlistitems"
                )

                yt_data = cls._find_yt_data(result.text)
                extracted_json = yt_data["contents"][
                    "twoColumnBrowseResultsRenderer"
                ]["tabs"][0]["tabRenderer"]["content"]["sectionListRenderer"][
                    "contents"
                ][
                    0
                ][
                    "itemSectionRenderer"
                ][
                    "contents"
                ][
                    0
                ][
                    "playlistVideoListRenderer"
                ][
                    "contents"
                ]

                items = jAPI.json_to_items(cls, extracted_json)
            else:
                items = cls.plsoup_to_items(videos)

            return json.loads(
                json.dumps(
                    {"nextPageToken": ajax, "items": items},
                    sort_keys=False,
                    indent=1,
                )
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

            logger.info(
                f"japi run_search triggered session.post: {search_query}"
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
                        sections = yt_data["contents"][
                            "twoColumnSearchResultsRenderer"
                        ]["primaryContents"]["sectionListRenderer"]["contents"]
                    except KeyError:
                        sections = yt_data["onResponseReceivedCommands"][0][
                            "appendContinuationItemsAction"
                        ]["continuationItems"]

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
                    results.extend(cls.json_to_items(cls, extracted_json))

        return results

    @classmethod
    def pl_run_search(cls, query):
        logger.info(f"japi run_search triggered session.get: {query}")
        result = cls.session.get(urljoin(cls.endpoint, "results"), params=query)
        if result.status_code == 200:
            yt_data = None
            yt_data = cls._find_yt_data(result.text)
            if yt_data:
                extracted_json = yt_data["contents"][
                    "twoColumnSearchResultsRenderer"
                ]["primaryContents"]["sectionListRenderer"]["contents"][0][
                    "itemSectionRenderer"
                ][
                    "contents"
                ]
                results = cls.json_to_items(cls, extracted_json)
                return results

        return []

    def json_to_items(cls, result_json):
        if len(result_json) > 1 and "itemSectionRenderer" in result_json[1]:
            result_json = result_json[1]["itemSectionRenderer"]["contents"]

        items = []

        for content in result_json:
            if "videoRenderer" in content:
                base = "videoRenderer"
            elif "compactVideoRenderer" in content:
                base = "compactVideoRenderer"
            elif "playlistVideoRenderer" in content:
                base = "playlistVideoRenderer"
            else:
                base = ""

            if base in [
                "videoRenderer",
                "compactVideoRenderer",
                "playlistVideoRenderer",
            ]:
                if "longBylineText" in content[base]:
                    byline = "longBylineText"
                else:
                    byline = "shortBylineText"

                try:
                    videoId = content[base]["videoId"]
                except Exception as e:
                    # videoID = "Unknown"
                    logger.error("videoId exception %s" % e)
                    continue

                try:
                    title = content[base]["title"]["simpleText"]
                except Exception:
                    try:
                        title = content[base]["title"]["runs"][0]["text"]
                    except Exception as e:
                        # title = "Unknown"
                        logger.error("title exception %s" % e)
                        continue

                try:
                    thumbnails = content[base]["thumbnail"]["thumbnails"][-1]
                    thumbnails["url"] = thumbnails["url"].split("?", 1)[
                        0
                    ]  # is the rest tracking stuff? Omit
                except Exception as e:
                    logger.error(f"thumbnail exception {e}")

                try:
                    channelTitle = content[base][byline]["runs"][0]["text"]
                except Exception as e:
                    # channelTitle = "Unknown"
                    logger.error("channelTitle exception %s, %s" % (e, title))
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
                    duration_text = content[base]["lengthText"]["simpleText"]
                    duration = "PT" + cls.format_duration(
                        re.match(cls.time_regex, duration_text)
                    )
                    logger.debug("duration: ", duration)
                except Exception as e:
                    logger.warn("no video-time, possibly live: ", e)
                    duration = "PT0S"

                item.update({"contentDetails": {"duration": duration}})

                # is channelId useful for anything?
                try:
                    channelId = content[base][byline]["runs"][0][
                        "navigationEndpoint"
                    ]["browseEndpoint"]["browseId"]
                    logger.debug(channelId)
                    item["snippet"].update({"channelId": channelId})
                except Exception as e:
                    logger.error("channelId exception %s, %s" % (e, title))

                items.append(item)

            elif "radioRenderer" in content:
                continue

            elif "playlistRenderer" in content:

                try:
                    thumbnails = content["playlistRenderer"]["thumbnails"][0][
                        "thumbnails"
                    ][-1]
                    thumbnails["url"] = thumbnails["url"].split("?", 1)[
                        0
                    ]  # is the rest tracking stuff? Omit
                except Exception as e:
                    logger.error(
                        f"thumbnail exception {e}, {content['playlistRenderer']['playlistId']}"
                    )

                try:
                    channelTitle = content["playlistRenderer"][
                        "longBylineText"
                    ]["runs"][0]["text"]
                except Exception as e:
                    logger.error(
                        f"channelTitle exception {e}, {content['playlistRenderer']['playlistId']}"
                    )

                item = {
                    "id": {
                        "kind": "youtube#playlist",
                        "playlistId": content["playlistRenderer"]["playlistId"],
                    },
                    "contentDetails": {
                        "itemCount": content["playlistRenderer"]["videoCount"]
                    },
                    "snippet": {
                        "title": content["playlistRenderer"]["title"][
                            "simpleText"
                        ],
                        "thumbnails": {"default": thumbnails,},
                        "channelTitle": channelTitle,
                    },
                }
                items.append(item)

            elif "gridPlaylistRenderer" in content:
                try:
                    thumbnails = content["gridPlaylistRenderer"][
                        "thumbnailRenderer"
                    ]["playlistVideoThumbnailRenderer"]["thumbnail"][
                        "thumbnails"
                    ][
                        -1
                    ]
                    thumbnails["url"] = thumbnails["url"].split("?", 1)[
                        0
                    ]  # is the rest tracking stuff? Omit
                except Exception as e:
                    logger.error(
                        f"thumbnail exception {e}, {content['gridPlaylistRenderer']['playlistId']}"
                    )

                item = {
                    "id": {
                        "kind": "youtube#playlist",
                        "playlistId": content["gridPlaylistRenderer"][
                            "playlistId"
                        ],
                    },
                    "contentDetails": {
                        "itemCount": int(
                            content["gridPlaylistRenderer"][
                                "videoCountShortText"
                            ]["simpleText"].replace(",", "")
                        )
                    },
                    "snippet": {
                        "title": content["gridPlaylistRenderer"]["title"][
                            "runs"
                        ][0]["text"],
                        "thumbnails": {"default": thumbnails,},
                        "channelTitle": "unknown",  # note: do better
                    },
                }
                items.append(item)

        # remove duplicates
        items[:] = [
            json.loads(t)
            # for t in {json.dumps(d) for d in items}
            for t in {json.dumps(d, sort_keys=True) for d in items}
        ]

        return items
