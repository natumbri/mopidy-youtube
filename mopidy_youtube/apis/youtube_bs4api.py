import json
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from mopidy_youtube import logger
from mopidy_youtube.apis.youtube_scrapi import scrAPI


class bs4API(scrAPI):
    """
    Indirect access to YouTube data, without API
    using BS4 (instead of regex, as used by scrAPI)
    """

    time_regex = (
        r"(?:(?:(?P<durationHours>[0-9]+)\:)?"
        r"(?P<durationMinutes>[0-9]+)\:"
        r"(?P<durationSeconds>[0-9]{2}))"
    )

    @classmethod
    def run_search(cls, query):
        items = []

        result = cls.session.get(urljoin(cls.endpoint, "results"), params=query)

        if result.status_code == 200:
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
                                "<div", "</script><div", script.string, count=1
                            ),
                            "html.parser",
                        )
                        script.replace_with(new_soup)

            # strip out ads that are returned
            [
                ad.decompose()
                for ad in soup.find_all("div", class_="pyv-afc-ads-container")
            ]

            results = soup.find_all(
                "div", class_=["yt-lockup-video", "yt-lockup-playlist"]
            )
            for result in results:
                if "yt-lockup-video" in result.get("class"):
                    duration_text = result.find(class_="video-time").text
                    duration = cls.format_duration(
                        re.match(cls.time_regex, duration_text)
                    )
                    item = {
                        "id": {
                            "kind": "youtube#video",
                            "videoId": result["data-context-item-id"],
                        },
                        "contentDetails": {"duration": "PT" + duration},
                        "snippet": {
                            "title": result.find(
                                class_="yt-lockup-title"
                            ).next.text,
                            # TODO: full support for thumbnails
                            "thumbnails": {
                                "default": {
                                    "url": "https://i.ytimg.com/vi/"
                                    + result["data-context-item-id"]
                                    + "/default.jpg",
                                    "width": 120,
                                    "height": 90,
                                },
                            },
                            "channelTitle": result.find(
                                class_="yt-lockup-byline"
                            ).text,
                        },
                    }
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
                                        + result.find(
                                            class_="yt-lockup-thumbnail"
                                        )
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
                    if str(item["id"]["playlistId"]).startswith("PL"):
                        items.append(item)
        return items

    @classmethod
    def list_playlistitems(cls, id, page, max_results):
        query = {"list": id, "app": "desktop", "persist_app": 1}
        logger.info("session.get triggered: list_playlist_items")
        ajax_css = "button[data-uix-load-more-href]"

        items = []
        if page == "":
            r = cls.session.get(urljoin(cls.endpoint, "playlist"), params=query)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, "html.parser")
        else:
            r = cls.session.get(urljoin(cls.endpoint, page))
            if r.status_code == 200:
                soup = BeautifulSoup("".join(r.json().values()), "html.parser")

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

        result = json.loads(
            json.dumps(
                {"nextPageToken": ajax, "items": items},  # noqa: E501
                sort_keys=False,
                indent=1,
            )
        )

        return result

    @classmethod
    def list_videos(cls, ids):
        """
        list videos - EXPERIMENTAL, using exact search for ids
        """

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

        for result in [cls.run_search(r)[0] for r in rs]:
            logger.info("session.get triggered: list_videos (experimental)")
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

        for result in [cls.run_search(r)[0] for r in rs]:
            logger.info("session.get triggered: list_playlists (experimental)")
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
        logger.info(result)
        if result.status_code == 200:
            soup = BeautifulSoup(result.text, "html.parser")
            results = soup.find_all("li", class_=["related-list-item"])
            for result in results:
                if "related-list-item-compact-video" in result.get("class"):

                    videoId = result.find("span", {"data-vid": True})[
                        "data-vid"
                    ]

                    title_text = result.find("span", class_="title")
                    try:
                        title = title_text.text.strip()
                    except Exception as e:
                        title = "Unknown"
                        logger.info("title exception %s" % e)

                    channelTitle_text = result.find(
                        "span", class_="stat attribution"
                    )
                    try:
                        channelTitle = channelTitle_text.text.strip()
                    except Exception as e:
                        channelTitle = "Unknown"
                        logger.info("channelTitle exception %s" % e)

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

                    duration_text = result.find(class_="video-time")
                    try:
                        duration = cls.format_duration(
                            re.match(cls.time_regex, duration_text.text)
                        )
                        item["contentDetails"] = {"duration": "PT" + duration}
                    except Exception as e:
                        logger.info("duration exception %s" % e)
                    items.append(item)
        logger.info("related items: %d" % len(items))
        return json.loads(
            json.dumps({"items": items}, sort_keys=False, indent=1)
        )
