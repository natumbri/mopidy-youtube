import json
import re

from bs4 import BeautifulSoup
from mopidy_youtube import logger

from mopidy_youtube.apis.youtube_scrapi import scrAPI


# Indirect access to YouTube data, without API
# but use BS4 instead of regex
#
class bs4API(scrAPI):

    time_regex = (
        r"(?:(?:(?P<durationHours>[0-9]+)\:)?"
        r"(?P<durationMinutes>[0-9]+)\:"
        r"(?P<durationSeconds>[0-9]{2}))"
    )

    @classmethod
    def run_search(cls, query):
        items = []

        result = cls.session.get(cls.endpoint + "results", params=query)

        if result.status_code == 200:
            soup = BeautifulSoup(result.text, "html.parser")
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
                            # 'uploadDate': result.find(
                            #     class_ = "yt-lockup-meta-info"
                            #     ).find_all("li")[0].text,
                            # 'views': result.find(
                            #     class_ = "yt-lockup-meta-info"
                            #     ).find_all("li")[1].text,
                            # 'url': 'https://www.youtube.com'+result.find(
                            #     class_ = "yt-lockup-title").next['href']
                        },
                    }

                    # if result.find(class_ = "yt-lockup-description") is not None:
                    #   item['snippet']['description'] = result.find(
                    #       class_ = "yt-lockup-description").text or "NA"
                    # else:
                    #   item['snippet']['description'] = "NA"

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
                            # 'url': ('https://www.youtube.com/playlist?list='
                            #     +info['id']['playlistId'])
                        },
                    }
                    # don't append radiolist playlists
                    if str(item["id"]["playlistId"]).startswith("PL"):
                        items.append(item)
        return items

    # list playlist items
    #
    @classmethod
    def run_list_playlistitems(cls, query):
        items = []

        result = cls.session.get(cls.endpoint + "playlist", params=query)

        if result.status_code == 200:
            soup = BeautifulSoup(result.text, "html.parser")
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
        return items

    # list videos - EXPERIMENTAL, using search
    #
    @classmethod
    def list_videos(cls, ids):
        items = []

        rs = [
            {
                "search_query": '"' + id + '"',
                "sp": "EgIQAQ%3D%3D",
                "app": "desktop",
            }
            for id in ids
            # This may be more exact:
            # {"search_query": '"' + id + '"', "sp": "EgIQAUICCAE%253D"} for id in ids
        ]

        for result in [cls.run_search(r)[0] for r in rs]:
            logger.info("session.get triggered: list_videos (experimental)")
            result.update({"id": result["id"]["videoId"]})
            items.extend([result])

        return json.loads(
            json.dumps({"items": items}, sort_keys=False, indent=1)
        )

    # list playlists - EXPERIMENTAL, using search
    #
    @classmethod
    def list_playlists(cls, ids):
        items = []

        rs = [
            {
                "search_query": '"' + id + '"',
                "sp": "EgIQAw%3D%3D",
                "app": "desktop",
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
