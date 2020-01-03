import json
import re

from mopidy_youtube import logger

# from youtube import Client, Video
from youtube_scrapi import scrAPI


# JSON based scrAPI
class jAPI(scrAPI):

    # search for videos and playlists
    #
    @classmethod
    def search(cls, q):
        query = {
            # get videos only
            # 'sp': 'EgIQAQ%253D%253D',
            "search_query": q.replace(" ", "+")
        }

        cls.session.headers = {
            "user-agent": "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:66.0)"
            " Gecko/20100101 Firefox/66.0",
            "Cookie": "PREF=hl=en;",
            "Accept-Language": "en;q=0.5",
            "content_type": "application/json",
        }
        logger.info("session.get triggered: search")
        result = cls.session.get(jAPI.endpoint + "results", params=query)

        json_regex = r'window\["ytInitialData"] = (.*?);'
        extracted_json = re.search(json_regex, result.text).group(1)
        result_json = json.loads(extracted_json)["contents"][
            "twoColumnSearchResultsRenderer"
        ]["primaryContents"]["sectionListRenderer"]["contents"][0][
            "itemSectionRenderer"
        ][
            "contents"
        ]  # noqa: E501

        items = []
        for content in result_json:
            item = {}
            if "videoRenderer" in content:
                item.update(
                    {
                        "id": {
                            "kind": "youtube#video",
                            "videoId": content["videoRenderer"]["videoId"],
                        },
                        # 'contentDetails': {
                        #     'duration': 'PT'+duration
                        # }
                        "snippet": {
                            "title": content["videoRenderer"]["title"][
                                "simpleText"
                            ],  # noqa: E501
                            # TODO: full support for thumbnails
                            "thumbnails": {
                                "default": {
                                    "url": "https://i.ytimg.com/vi/"
                                    + content["videoRenderer"]["videoId"]
                                    + "/default.jpg",
                                    "width": 120,
                                    "height": 90,
                                },
                            },
                            "channelTitle": content["videoRenderer"][
                                "longBylineText"
                            ]["runs"][0][
                                "text"
                            ],  # noqa: E501
                        },
                    }
                )
            elif "radioRenderer" in content:
                pass
            elif "playlistRenderer" in content:
                item.update(
                    {
                        "id": {
                            "kind": "youtube#playlist",
                            "playlistId": content["playlistRenderer"][
                                "playlistId"
                            ],  # noqa: E501
                        },
                        "contentDetails": {
                            "itemCount": content["playlistRenderer"][
                                "videoCount"
                            ]
                        },
                        "snippet": {
                            "title": content["playlistRenderer"]["title"][
                                "simpleText"
                            ],  # noqa: E501
                            # TODO: full support for thumbnails
                            "thumbnails": {
                                "default": {
                                    "url": "https://i.ytimg.com/vi/"
                                    + content["playlistRenderer"][
                                        "navigationEndpoint"
                                    ]["watchEndpoint"][
                                        "videoId"
                                    ]  # noqa: E501
                                    + "/default.jpg",
                                    "width": 120,
                                    "height": 90,
                                },
                                "channelTitle": content["playlistRenderer"][
                                    "longBylineText"
                                ]["runs"][0][
                                    "text"
                                ],  # noqa: E501
                            },
                        },
                    }
                )
            items.append(item)
        return json.loads(
            json.dumps(
                {"items": [i for i in items if i]}, sort_keys=False, indent=1
            )
        )
