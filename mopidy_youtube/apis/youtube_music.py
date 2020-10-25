import json
import re

from mopidy_youtube import logger
from mopidy_youtube.youtube import Client, Playlist, Video
from mopidy_youtube.apis.youtube_japi import jAPI
from mopidy_youtube.apis.youtube_scrapi import scrAPI
from ytmusicapi import YTMusic

ytmusic = YTMusic()


# Direct access to YouTube Music API
#
class Music(Client):
    endpoint = "https://music.youtube.com"
    searchEndpoint = endpoint + "/youtubei/v1/search"
    api_key = ""

    @classmethod
    def search(cls, q):
        search_results = []
        api_search_results = ytmusic.search(query=q)
        video_results = cls.search_albums(q)
        [
            search_results.append(result)
            for result in video_results[: int(Video.search_results)]
        ]
        album_results = cls.search_videos(q)
        [
            search_results.append(result)
            for result in album_results[: int(Video.search_results)]
        ]

        json_results = json.loads(
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

        api_json_results = json.loads(
            json.dumps(
                {
                    "items": [
                        x
                        for x in api_search_results
                        # for _, x in zip(
                        #     range(Video.search_results), search_results
                        # )
                    ]
                },
                sort_keys=False,
                indent=1,
            )
        )

        
        # Writing to sample.json 
        with open("/tmp/api.json", "w") as outfile: 
                outfile.write(json.dumps(api_json_results))

        # Writing to sample.json 
        with open("/tmp/non-api.json", "w") as outfile: 
                outfile.write(json.dumps(json_results)) 

        return json_results

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

        logger.info("session.post triggered: music base_search")

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

        return {"nextPageToken": nextToken, "items": normalized_items}

    @classmethod
    def search_videos(cls, q):
        results = []
        continuationToken = None
        while len(results) < Video.search_results:
            result = cls.base_search(q, continuationToken=continuationToken)
            results.extend(result["items"])
            continuationToken = result["nextPageToken"]
            if continuationToken is None:
                break

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
        results = []
        continuationToken = None
        while len(results) < Video.search_results:
            result = cls.base_search(
                q, continuationToken=continuationToken, videos=False
            )
            results.extend(result["items"])
            continuationToken = result["nextPageToken"]
            if continuationToken is None:
                break

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
    def list_playlists(cls, ids):
        """
        list playlists
        """
        # until this is faster, just return an empty dict
        # the consequence is that the number of track on each
        # album is shown as 'None videos'
        return json.loads(json.dumps({"items": {}}, sort_keys=False, indent=1))

        # what follows works, but takes ages, mainly because
        # it loads each playlist separately. So, if you have 50 playlists
        # that's 50 trips to the endpoint.
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

                myvideos = []

                for playlistVideo in jAPI.json_to_items(cls, playlistVideos):
                    set_api_data = ["title", "channel"]
                    if "contentDetails" in item:
                        set_api_data.append("length")
                    if "thumbnails" in item["snippet"]:
                        set_api_data.append("thumbnails")
                    video = Video.get(
                        playlistVideo["snippet"]["resourceId"]["videoId"]
                    )
                    myvideos.append(video)
                    video._set_api_data(set_api_data, playlistVideo)

                # start loading video info in the background
                Video.load_info(
                    [
                        x
                        for _, x in zip(
                            range(Playlist.playlist_max_videos), myvideos
                        )
                    ]
                )

                items.append(item)

        return json.loads(
            json.dumps({"items": items}, sort_keys=False, indent=1)
        )
