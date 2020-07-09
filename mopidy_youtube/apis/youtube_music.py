import json
import re

from mopidy_youtube import logger
from mopidy_youtube.youtube import Client, Video


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
            logger.info('triggered session.get for api_key')
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
                    # 'contentDetails': {
                    #     'duration': 'PT'+duration
                    # }
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
                        for _, x in zip(
                            range(Video.search_results), search_results
                        )
                    ]
                },
                sort_keys=False,
                indent=1,
            )
        )

