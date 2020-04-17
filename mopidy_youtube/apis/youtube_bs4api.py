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
                            "itemCount": result.find(
                                class_="formatted-video-count-label"
                            ).text.split(" ")[0]
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

        items = []

        r = cls.session.get(urljoin(cls.endpoint, "playlist"), params=query)

        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")

            # get load more button
            ajax_css = "button[data-uix-load-more-href]"
            ajax = soup.select(ajax_css)
            # if there is no more, there is no "Load more" button
            if ajax:
                ajax = ajax[0]["data-uix-load-more-href"]
            else:
                ajax = None

            # get first visible videos
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

            # get the videos that are behind the ajax curtain
            while ajax is not None and len(videos) < max_results:
                r = cls.session.get(urljoin(cls.endpoint, ajax))

                # next html is stored in the json.values()
                soup = BeautifulSoup("".join(r.json().values()), "html.parser")
                videos.extend(
                    [
                        video
                        for video in soup.find_all("tr", {"class": "pl-video"})
                        if all(
                            [
                                video.find(class_="timestamp"),
                                video.find(class_="pl-video-owner"),
                            ]
                        )
                    ]
                )

                ajax = soup.select(ajax_css)
                # if empty "Load more" button would be gone
                if not ajax:
                    break
                ajax = ajax[0]["data-uix-load-more-href"]

            del videos[max_results:]

            for video in videos:
                item = {
                    "id": video["data-video-id"],
                    "contentDetails": {
                        "duration": "PT"
                        + cls.format_duration(
                            re.match(
                                cls.time_regex,
                                video.find(class_="timestamp").text,
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
                    {"nextPageToken": None, "items": items},  # noqa: E501
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
    def get_related_videos(cls, video_id):
        """
        returns related videos for a given video_id
        """

        items = []

        query = {"v": video_id, "app": "desktop", "persist_app": 1}
        logger.info("session.get triggered: get_related_videos")
        result = cls.session.get(cls.endpoint + "watch", params=query)
        if result.status_code == 200:
            soup = BeautifulSoup(result.text, "html.parser")
            results = soup.find_all("li", class_=["related-list-item"])
            for result in results:
                if "related-list-item-compact-video" in result.get("class"):
                    duration_text = result.find(class_="video-time").text
                    duration = cls.format_duration(
                        re.match(cls.time_regex, duration_text)
                    )
                    item = {
                        "id": {
                            "kind": "youtube#video",
                            "videoId": result.find("span", {"data-vid": True})[
                                "data-vid"
                            ],
                        },
                        "contentDetails": {"duration": "PT" + duration},
                        "snippet": {
                            "title": result.find(
                                "span", class_="title"
                            ).text.strip(),
                            # TODO: full support for thumbnails
                            "thumbnails": {
                                "default": {
                                    "url": "https://i.ytimg.com/vi/"
                                    + result.find("span", {"data-vid": True})[
                                        "data-vid"
                                    ]
                                    + "/default.jpg",
                                    "width": 120,
                                    "height": 90,
                                },
                            },
                            "channelTitle": result.find(
                                "span", class_="stat attribution"
                            ).text.strip(),
                        },
                    }
                    items.append(item)
        return items
