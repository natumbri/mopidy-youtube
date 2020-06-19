import json
import re

from mopidy_youtube import logger

# from youtube import Client, Video
from mopidy_youtube.apis.youtube_scrapi import scrAPI


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
        logger.info("session.get triggered: jAPI search")
        result = cls.session.get(jAPI.endpoint + "results", params=query)
        json_regex = r'window\["ytInitialData"] = ({.*?});'
        extracted_json = re.search(json_regex, result.text).group(1)
        result_json = json.loads(extracted_json)["contents"][
            "twoColumnSearchResultsRenderer"
        ]["primaryContents"]["sectionListRenderer"]["contents"][0][
            "itemSectionRenderer"
        ][
            "contents"
        ]  # noqa: E501
        items = cls.json_to_items(cls, result_json)
        return json.loads(
            json.dumps(
                {"items": [i for i in items if i]}, sort_keys=False, indent=1
            )
        )

    def json_to_items(cls, result_json):
        items = []
        for content in result_json:
            if "videoRenderer" in content:
                base = "videoRenderer"
            elif "compactVideoRenderer" in content:
                base = "compactVideoRenderer"
            else:
                base = ""

            if base in ["videoRenderer", "compactVideoRenderer"]:
                try:
                    videoId = content[base]["videoId"]
                    logger.debug(videoId)
                except Exception as e:
                    # videoID = "Unknown"
                    logger.error("videoId exception %s" % e)
                    continue

                try:
                    title = content[base]["title"]["simpleText"]
                    logger.debug(title)
                except Exception:
                    try:
                        title = content[base]["title"]["runs"][0]["text"]
                        logger.debug(title)
                    except Exception as e:
                        # title = "Unknown"
                        logger.error("title exception %s" % e)
                        continue
                try:
                    channelTitle = content[base]["longBylineText"]["runs"][0][
                        "text"
                    ]
                    logger.debug(channelTitle)
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
                    duration_text = content[base]["lengthText"]["simpleText"]
                    duration = "PT" + cls.format_duration(
                        re.match(cls.time_regex, duration_text)
                    )
                    logger.debug("duration: ", duration)
                except Exception as e:
                    logger.warn("no video-time, possibly live: ", e)
                    duration = "PT0S"

                item.update({"contentDetails": {"duration": duration}})
                items.append(item)

            elif "radioRenderer" in content:
                continue

            elif "playlistRenderer" in content:
                item = {
                    "id": {
                        "kind": "youtube#playlist",
                        "playlistId": content["playlistRenderer"][
                            "playlistId"
                        ],  # noqa: E501
                    },
                    "contentDetails": {
                        "itemCount": content["playlistRenderer"]["videoCount"]
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
                        },
                        "channelTitle": content["playlistRenderer"][
                            "longBylineText"
                        ]["runs"][0][
                            "text"
                        ],  # noqa: E501
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
