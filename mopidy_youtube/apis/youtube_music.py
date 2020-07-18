import json
import re

from mopidy_youtube import logger
from mopidy_youtube.youtube import Client, Video
from mopidy_youtube.apis.youtube_japi import jAPI
from mopidy_youtube.apis.youtube_scrapi import scrAPI


# Direct access to YouTube Music API
#
class Music(Client):
    endpoint = "https://music.youtube.com"
    searchEndpoint = endpoint + "/youtubei/v1/search"
    api_key = ""

    # Get YouTube Music Token
    #
    @classmethod
    def get_token(cls):
        if not Music.api_key:
            headers = {
                "user-agent": "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:66.0)"
                " Gecko/20100101 Firefox/66.0",
                "Cookie": "PREF=hl=en;",
                "Accept-Language": "en;q=0.5",
                "content_type": "application/json",
            }
            logger.info("triggered session.get for api_key")
            response = cls.session.get(Music.endpoint, headers=headers)
            json_regex = r"ytcfg.set\((.*?)\);"
            extracted_json = re.search(json_regex, response.text).group(1)

            Music.api_key = json.loads(extracted_json)["INNERTUBE_API_KEY"]
        return Music.api_key

    @classmethod
    def base_search(cls, q, continuationToken=None, videos=True):
        searchHeaders = {
            "Referer": "https://music.youtube.com/",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:71.0) Gecko/20100101 Firefox/71.0",
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.5",
        }

        query = {
            "alt": "json",
            "key": cls.get_token(),
        }

        if continuationToken:
            query["cToken"] = continuationToken
            query["continuation"] = continuationToken

        typeFilter = {
            "songs": "Eg-KAQwIARAAGAAgACgAMABqChAJEAMQBBAKEAU%3D",
            "albums": "Eg-KAQwIABAAGAEgACgAMABqChAJEAMQBBAKEAU%3D",
        }

        data = {
            "context": {
                "client": {
                    "clientName": "WEB_REMIX",
                    "clientVersion": "0.1",
                    "hl": "en",
                    "gl": "US",
                },
            },
        }

        if not continuationToken:
            data["query"] = q
            data["params"] = (
                typeFilter["songs"] if videos else typeFilter["albums"]
            )

        json_response = cls.session.post(
            Music.searchEndpoint, params=query, headers=searchHeaders, json=data
        )
        result_json = json_response.json()
        results = None
        if "contents" in result_json:
            results = result_json["contents"]["sectionListRenderer"]["contents"]
        elif "continuationContents" in result_json:
            results = result_json["continuationContents"]

        if not results:
            return

        items = []
        nextToken = None
        if "musicShelfContinuation" in results:
            musicShelf = results["musicShelfContinuation"]
            items.append(musicShelf["contents"])
            if "continuations" in musicShelf:
                nextToken = musicShelf["continuations"][0][
                    "nextContinuationData"
                ]["continuation"]
        else:
            for content in results:
                musicShelf = content["musicShelfRenderer"]
                items.append(musicShelf["contents"])
                if musicShelf["continuations"]:
                    nextToken = musicShelf["continuations"][0][
                        "nextContinuationData"
                    ]["continuation"]

        normalized_items = []
        for thing in items:
            for x in thing:
                normalized_items.append(x["musicResponsiveListItemRenderer"])

        if nextToken and len(normalized_items) < Video.search_results:
            values = cls.base_search(
                q, continuationToken=nextToken, videos=videos
            )
            if values:
                normalized_items += values

        return normalized_items

    @classmethod
    def search_videos(cls, q):
        results = cls.base_search(q)
        videos = []
        for item in results:
            video = {}
            video.update(
                {
                    "id": {
                        "kind": "youtube#video",
                        "videoId": item["doubleTapCommand"]["watchEndpoint"][
                            "videoId"
                        ],
                    },
                    "contentDetails": {
                        "duration": "PT"
                        + cls.format_duration(
                            re.match(
                                cls.time_regex,
                                item["flexColumns"][3][
                                    "musicResponsiveListItemFlexColumnRenderer"
                                ]["text"]["runs"][0]["text"],
                            )
                        )
                    },
                    "snippet": {
                        "channelTitle": item["flexColumns"][1][
                            "musicResponsiveListItemFlexColumnRenderer"
                        ]["text"]["runs"][0][
                            "text"
                        ],  # noqa: E501
                        "thumbnails": {
                            "default": item["thumbnail"][
                                "musicThumbnailRenderer"
                            ]["thumbnail"]["thumbnails"][0],
                        },
                        "title": item["flexColumns"][0][
                            "musicResponsiveListItemFlexColumnRenderer"
                        ]["text"]["runs"][0][
                            "text"
                        ],  # noqa: E501
                    },
                }
            )
            videos.append(video)
        return videos

    @classmethod
    def search_albums(cls, q):
        results = cls.base_search(q, videos=False)

        playlists = []
        for item in results:
            playlist = {}
            playlist.update(
                {
                    "id": {
                        "kind": "youtube#playlist",
                        "playlistId": item["doubleTapCommand"][
                            "watchPlaylistEndpoint"
                        ]["playlistId"],
                    },
                    "snippet": {
                        "channelTitle": item["flexColumns"][1][
                            "musicResponsiveListItemFlexColumnRenderer"
                        ]["text"]["runs"][0][
                            "text"
                        ],  # noqa: E501
                        "thumbnails": {
                            "default": item["thumbnail"][
                                "musicThumbnailRenderer"
                            ]["thumbnail"]["thumbnails"][0],
                        },
                        "title": item["flexColumns"][0][
                            "musicResponsiveListItemFlexColumnRenderer"
                        ]["text"]["runs"][0][
                            "text"
                        ],  # noqa: E501
                    },
                }
            )
            playlists.append(playlist)
        return playlists

    @classmethod
    def search(cls, q):
        search_results = []
        video_results = cls.search_albums(q)
        [search_results.append(result) for result in video_results]
        album_results = cls.search_videos(q)
        [search_results.append(result) for result in album_results]

        return json.loads(
            json.dumps(
                {
                    "items": [
                        x
                        for x in search_results
                        # for _, x in zip(
                        #     range(Video.search_results), search_results
                        # )
                    ]
                },
                sort_keys=False,
                indent=1,
            )
        )

    @classmethod
    def list_playlists(cls, ids):
        """
        list playlists
        """

        items = []

        for id in ids:

            query = {
                "list": id,
                "app": "desktop",
                "persist_app": 1,
            }

            logger.info("session.get triggered: youtube-music list_playlists")
            result = cls.session.get(scrAPI.endpoint + "playlist", params=query)

            if result.status_code == 200:
                logger.info("nothing in the soup, trying japi")
                json_regex = r'window\["ytInitialData"] = ({.*?});'
                extracted_json = re.search(json_regex, result.text).group(1)
                thumbnails = json.loads(extracted_json)["microformat"][
                    "microformatDataRenderer"
                ]["thumbnail"]["thumbnails"][0]
                title = json.loads(extracted_json)["microformat"][
                    "microformatDataRenderer"
                ]["title"]
                channelTitle = "YouTube"
                playlistVideos = json.loads(extracted_json)["contents"][
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

                itemCount = len(playlistVideos)

                item = {
                    "id": id,
                    "snippet": {
                        "title": title,
                        "thumbnails": {"default": thumbnails},
                    },
                    "channelTitle": channelTitle,
                    "contentDetails": {"itemCount": itemCount},
                }

                for playlistVideo in jAPI.json_to_items(cls, playlistVideos):
                    set_api_data = ["title", "channel"]
                    if "contentDetails" in item:
                        set_api_data.append("length")
                    if "thumbnails" in item["snippet"]:
                        set_api_data.append("thumbnails")
                    video = Video.get(
                        playlistVideo["snippet"]["resourceId"]["videoId"]
                    )
                    video._set_api_data(set_api_data, playlistVideo)

                items.append(item)

        return json.loads(
            json.dumps({"items": items}, sort_keys=False, indent=1)
        )
