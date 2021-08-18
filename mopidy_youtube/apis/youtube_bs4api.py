import json
import re
from urllib.parse import urlencode, urljoin

from bs4 import BeautifulSoup

from mopidy_youtube import logger
from mopidy_youtube.apis.youtube_japi import jAPI
from mopidy_youtube.comms import Client
from mopidy_youtube.youtube import Video


class bs4API(Client):
    """
    Indirect access to YouTube data, without API
    using BS4 (instead of regex, as used by scrAPI)
    """

    time_regex = (
        r"(?:(?:(?P<durationHours>[0-9]+)\:)?"
        r"(?P<durationMinutes>[0-9]+)\:"
        r"(?P<durationSeconds>[0-9]{2}))"
    )

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

        search_results = []

        logger.info(f"jAPI search triggered session.get: {q}")

        search_results = cls.run_search(q)

        return json.loads(
            json.dumps(
                {
                    "items": [
                        x
                        for _, x in zip(
                            range(Video.search_results), search_results
                        )
                    ]
                },
                sort_keys=False,
                indent=1,
            )
        )

    @classmethod
    def run_search(cls, search_query):
        continuation = None
        results = []
        data = {}
        logger.info("session.get triggered: japi run_search")

        while len(results) < Video.search_results:

            query = {
                "query": search_query,
                "key": "AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8",
                "contentCheckOk": True,
                "racyCheckOk": True,
            }

            if continuation:
                data["continuation"] = continuation

            data.update(
                {
                    "context": {
                        "client": {
                            "clientName": "WEB",
                            "clientVersion": "2.20200720.00.02",
                        },
                    },
                }
            )

            result = cls.session.post(
                url=f'{urljoin(cls.endpoint, "youtubei/v1/search")}?{urlencode(query)}',
                data=bytes(json.dumps(data), encoding="utf-8"),
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "accept-language": "en-US,en",
                    "Content-Type": "application/json",
                },
            )

            if result.status_code == 200:
                logger.info("trying japi")
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
                    results.extend(jAPI.json_to_items(cls, extracted_json))

        return results

    def _find_yt_data(text):
        for r in bs4API.ytdata_regex:
            result = re.search(r, text)
            if result:
                return json.loads(result.group(1))

        logger.error("No data found on page")
        raise Exception("No data found on page")

    @classmethod
    def pl_run_search(cls, query):
        logger.info(f"bs4api pl_run_search triggered session.get: {query}")
        result = cls.session.get(urljoin(cls.endpoint, "results"), params=query)
        if result.status_code == 200:

            # make japi first option, since it seems to be most reliable
            logger.info("trying japi")
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
                results = jAPI.json_to_items(cls, extracted_json)
                return results

            else:

                logger.info("japi failed, trying bs4 as a last ditch attempt")
                soup = BeautifulSoup(result.text, "html.parser")
                # hack because youtube result sometimes seem to be missing a </script> tag
                if not soup.find_all(
                    "div", class_=["yt-lockup-video", "yt-lockup-playlist"]
                ):
                    for script in soup.find_all("script"):
                        # assume scripts should not contain "<div>" tags
                        # and that, if they do, there is a missing "</script>" tag
                        if script.find(text=re.compile("<div")):
                            new_soup = BeautifulSoup(
                                re.sub(
                                    "<div",
                                    "</script><div",
                                    script.string,
                                    count=1,
                                ),
                                "html.parser",
                            )
                            script.replace_with(new_soup)

                # strip out ads that are returned
                [
                    ad.decompose()
                    for ad in soup.find_all(
                        "div", class_="pyv-afc-ads-container"
                    )
                ]

                results = soup.find_all(
                    "div", class_=["yt-lockup-video", "yt-lockup-playlist"]
                )

                if results:
                    return cls.soup_to_items(results)

    @classmethod
    def soup_to_items(cls, results):
        items = []
        for result in results:
            if "yt-lockup-video" in result.get("class"):
                try:
                    videoId = result["data-context-item-id"]
                except Exception as e:
                    # videoID = "Unknown"
                    logger.error("videoId exception %s" % e)
                    continue

                try:
                    title_text = result.find("a", {"aria-describedby": True})
                    title = title_text.text.strip()
                except Exception:
                    try:
                        title_text = result.find("a", {"title": True})
                        title = title_text.text.strip()
                    except Exception as e:
                        # title = "Unknown"
                        logger.error("title exception %s" % e, videoId)
                        continue

                try:
                    channelTitle_text = result.find(class_="yt-lockup-byline")
                    channelTitle = channelTitle_text.text.strip()
                except Exception as e:
                    # channelTitle = "Unknown"
                    logger.error("channelTitle exception %s" % e)
                    continue

                item = {
                    "id": {"kind": "youtube#video", "videoId": videoId},
                    "snippet": {
                        "title": title,
                        # TODO: full support for thumbnails
                        "thumbnails": {
                            "default": {
                                "url": "https://i.ytimg.com/vi/"
                                + videoId
                                + "/default.jpg",
                                "width": 120,
                                "height": 90,
                            },
                        },
                        "channelTitle": channelTitle,
                    },
                }
                try:
                    duration_text = result.find(class_="video-time").text
                    duration = "PT" + cls.format_duration(
                        re.match(cls.time_regex, duration_text)
                    )
                except Exception as e:
                    logger.info(
                        "no video-time, possibly live: ",
                        e,
                        result["data-context-item-id"],
                    )
                    duration = "PT0S"
                item.update({"contentDetails": {"duration": duration}})
                items.append(item)

            elif "yt-lockup-playlist" in result.get("class"):
                item = {
                    "id": {
                        "kind": "youtube#playlist",
                        "playlistId": result.find(class_="yt-lockup-title")
                        .next["href"]
                        .partition("list=")[2],
                    },
                    "contentDetails": {
                        "itemCount": re.sub(
                            r"[^\d\.]",
                            "",
                            result.find(
                                class_="formatted-video-count-label"
                            ).text.split(" ")[0],
                        )
                    },
                    "snippet": {
                        "title": result.find(
                            class_="yt-lockup-title"
                        ).next.text,
                        # TODO: full support for thumbnails
                        "thumbnails": {
                            "default": {
                                "url": (
                                    "https://i.ytimg.com/vi/"
                                    + result.find(class_="yt-lockup-thumbnail")
                                    .find("a")["href"]
                                    .partition("v=")[2]
                                    .partition("&")[0]
                                    + "/default.jpg"
                                ),
                                "width": 120,
                                "height": 90,
                            },
                        },
                        "channelTitle": result.find(
                            class_="yt-lockup-byline"
                        ).text,
                    },
                }
                # don't append radiolist playlists
                if str(item["id"]["playlistId"]).startswith(("PL", "OL")):
                    items.append(item)
        return items

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
    def plsoup_to_items(cls, videos):
        items = []
        for video in videos:
            item = {
                "id": video["data-video-id"],
                "contentDetails": {
                    "duration": "PT"
                    + cls.format_duration(
                        re.match(
                            cls.time_regex, video.find(class_="timestamp").text,
                        )
                    ),
                },
                "snippet": {
                    "resourceId": {"videoId": video["data-video-id"]},
                    "title": video["data-title"],
                    # TODO: full support for thumbnails
                    "thumbnails": {
                        "default": {
                            "url": "https://i.ytimg.com/vi/"
                            + video["data-video-id"]
                            + "/default.jpg",
                            "width": 120,
                            "height": 90,
                        },
                    },
                    "channelTitle": video.find(class_="pl-video-owner")
                    .find("a")
                    .text,
                },
            }

            items.append(item)

        return items

    @classmethod
    def list_videos(cls, ids):
        """
        list videos - EXPERIMENTAL, using exact search for ids
        """
        logger.info("session.get triggered: list_videos (experimental)")

        items = []

        rs = [
            {
                "search_query": '"' + id + '"',
                "sp": "EgIQAQ%3D%3D",
                "app": "desktop",
                "persist_app": 1,
            }
            for id in ids
        ]
        results = [
            result
            for r in rs
            for result in cls.pl_run_search(r)
            if result["id"]["videoId"] in ids
        ]
        for result in results:
            result.update({"id": result["id"]["videoId"]})
            items.extend([result])
        return json.loads(
            json.dumps({"items": items}, sort_keys=False, indent=1)
        )

    @classmethod
    def list_playlists(cls, ids):
        """
        list playlists - EXPERIMENTAL, using exact search for ids
        """
        logger.info("session.get triggered: list_playlists (experimental)")

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
    def list_related_videos(cls, video_id):
        """
        returns related videos for a given video_id
        """
        items = []

        query = {"v": video_id, "app": "desktop", "persist_app": 1}
        logger.info("session.get triggered: list_related_videos")
        result = cls.session.get(cls.endpoint + "watch", params=query)
        if result.status_code == 200:
            soup = BeautifulSoup(result.text, "html.parser")
            results = soup.find_all("li", class_=["related-list-item"])
            if not results:
                logger.info("nothing in the soup, trying japi related videos")

                yt_data = cls._find_yt_data(result.text)
                extracted_json = yt_data["contents"][
                    "twoColumnWatchNextResults"
                ]["secondaryResults"]["secondaryResults"]["results"]

                items = jAPI.json_to_items(cls, extracted_json)

            for result in results:
                if "related-list-item-compact-video" in result.get("class"):

                    try:
                        videoId = result.find("span", {"data-vid": True})[
                            "data-vid"
                        ]
                    except Exception as e:
                        # videoID = "Unknown"
                        logger.error("videoId exception %s" % e)
                        continue

                    try:
                        title_text = result.find("span", class_="title")
                        title = title_text.text.strip()
                    except Exception as e:
                        # title = "Unknown"
                        logger.error("title exception %s" % e)
                        continue

                    try:
                        channelTitle_text = result.find(
                            "span", class_="stat attribution"
                        )
                        channelTitle = channelTitle_text.text.strip()
                    except Exception as e:
                        # channelTitle = "Unknown"
                        logger.error("channelTitle exception %s" % e)
                        continue

                    item = {
                        "id": {"kind": "youtube#video", "videoId": videoId},
                        "snippet": {
                            "title": title,
                            "resourceId": {"videoId": videoId},
                            # TODO: full support for thumbnails
                            "thumbnails": {
                                "default": {
                                    "url": "https://i.ytimg.com/vi/"
                                    + videoId
                                    + "/default.jpg",
                                    "width": 120,
                                    "height": 90,
                                },
                            },
                            "channelTitle": channelTitle,
                        },
                    }

                    try:
                        duration_text = result.find(class_="video-time")
                        duration = "PT" + cls.format_duration(
                            re.match(cls.time_regex, duration_text.text)
                        )
                        item.update({"contentDetails": {"duration": duration}})
                    except Exception as e:
                        # don't set duration on exception
                        logger.warn("duration exception %s" % e)
                        # because duration error doesn't invalidate item (live tracks, eg)
                    items.append(item)

        return json.loads(
            json.dumps({"items": items}, sort_keys=False, indent=1)
        )

    @classmethod
    def list_channelplaylists(cls, channel_id):
        """
        list playlists in a channel
        """
        logger.info("session.get triggered: list_channelplaylists")

        result = cls.session.get(cls.endpoint + "channel/" + channel_id)

        yt_data = cls._find_yt_data(result.text)

        extracted_json = yt_data["contents"]["twoColumnBrowseResultsRenderer"][
            "tabs"
        ][0]["tabRenderer"]["content"]["sectionListRenderer"]["contents"][0][
            "itemSectionRenderer"
        ][
            "contents"
        ][
            0
        ][
            "shelfRenderer"
        ][
            "content"
        ]

        if "expandedShelfContentsRenderer" in extracted_json:
            extracted_json = extracted_json["expandedShelfContentsRenderer"]

        if "horizontalListRenderer" in extracted_json:
            extracted_json = extracted_json["horizontalListRenderer"]

        if "items" in extracted_json:
            extracted_json = extracted_json["items"]
        else:
            logger.info("no items found")

        try:
            items = jAPI.json_to_items(cls, extracted_json)
            [
                item.update({"id": item["id"]["playlistId"]})
                for item in items
                if "playlistId" in item["id"]
            ]
        except Exception as e:
            logger.info(f"items exception {e}")
            items = []

        return json.loads(
            json.dumps({"items": items}, sort_keys=False, indent=1)
        )
