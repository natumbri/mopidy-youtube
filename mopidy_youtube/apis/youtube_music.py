import json
import re
from concurrent.futures.thread import ThreadPoolExecutor

from ytmusicapi import YTMusic

from mopidy_youtube import logger
from mopidy_youtube.youtube import Client, Playlist, Video

ytmusic = YTMusic()


# Direct access to YouTube Music API
#
class Music(Client):
    endpoint = None
    searchEndpoint = None

    @classmethod
    def search(cls, q):
        search_results = []
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

        return json_results

    @classmethod
    def search_videos(cls, q):
        results = ytmusic.search(
            query=q, filter="songs", limit=Video.search_results
        )

        def _channelTitle(item):
            try:
                channelTitle = item["artists"][0]["name"]
            except Exception:
                channelTitle = "unknown"
            return channelTitle

        videos = [
            {
                "id": {
                    "kind": "youtube#video",
                    "videoId": item["videoId"],
                },
                "contentDetails": {
                    "duration": "PT"
                    + cls.format_duration(
                        re.match(cls.time_regex, item["duration"])
                    )
                },
                "snippet": {
                    "title": item["title"],
                    "resourceId": {"videoId": item["videoId"]},
                    # TODO: full support for thumbnails
                    "thumbnails": {"default": item["thumbnails"][0]},
                    "channelTitle": _channelTitle(item),
                },
            }
            for item in results
        ]
        return videos

    @classmethod
    def playlist_item_to_video(cls, item, thumbnail):
        def _convertMillis(milliseconds):
            try:
                hours, miliseconds = divmod(int(milliseconds), 3600000)
            except Exception:
                return "00:00:00"
            minutes, miliseconds = divmod(miliseconds, 60000)
            seconds = int(miliseconds) / 1000
            return "%i:%02i:%02i" % (hours, minutes, seconds)

        video = {}
        video.update(
            {
                "id": {
                    "kind": "youtube#video",
                    "videoId": item["videoId"],
                },
                "contentDetails": {
                    "duration": "PT"
                    + cls.format_duration(
                        re.match(
                            cls.time_regex, _convertMillis(item["lengthMs"])
                        )
                    )
                },
                "snippet": {
                    "title": item["title"],
                    "resourceId": {"videoId": item["videoId"]},
                    # TODO: full support for thumbnails
                    "thumbnails": {"default": thumbnail},
                    "channelTitle": item["artists"],
                },
            }
        )
        return video

    @classmethod
    def search_albums(cls, q):
        playlists = []
        results = ytmusic.search(
            query=q, filter="albums", limit=Video.search_results
        )

        def job(item):
            try:
                playlist = cls.list_playlists([item["browseId"]])
                if playlist is None:
                    return
                else:
                    playlistItem = {
                        "id": {
                            "kind": "youtube#playlist",
                            "playlistId": item["browseId"],
                        },
                        "snippet": {
                            "channelTitle": item["type"],
                            "thumbnails": {"default": item["thumbnails"][0]},
                            "title": item["title"],
                        },
                        "contentDetails": playlist["items"][0][
                            "contentDetails"
                        ],
                    }
                    playlists.append(playlistItem)

            except Exception as e:
                logger.error('search_albums error "%s"', e)

        with ThreadPoolExecutor() as executor:
            executor.map(job, results)
        return playlists

    @classmethod
    def list_playlists(cls, ids):
        """
        list playlists
        """

        # what follows works, but it loads each playlist separately.
        # So, if you have 50 playlists that's 50 trips to the endpoint.

        logger.info("session.get triggered: youtube-music list_playlists")
        results = []
        for id in ids:
            try:
                results.append(ytmusic.get_album(browseId=id))
            except Exception as e:
                logger.info(
                    f"ytmusic.get_album failed with {e} for playlist {id}"
                )

        if len(results) == 0:
            logger.info(f"list_playlists for {ids} returned no results")
            return None

        def _channelTitle(result):
            try:
                channelTitle = result["artists"][0]["name"]
            except Exception:
                channelTitle = "unknown"
            return channelTitle

        items = [
            {
                "id": result["playlistId"],
                "snippet": {
                    "title": result["title"],
                    "thumbnails": {"default": result["thumbnails"][0]},
                    # apparently, result["artist"] can be empty
                    "channelTitle": _channelTitle(result),
                },
                "contentDetails": {"itemCount": result["trackCount"]},
            }
            for result in results
        ]

        # get the videos in the playlist and
        # start loading video info in the background
        album_tracks = [
            cls.playlist_item_to_video(track, result["thumbnails"][0])
            for result in results
            for track in result["tracks"]
        ]
        videos = [
            Video.get(album_track["snippet"]["resourceId"]["videoId"])
            for album_track in album_tracks
        ]
        [
            video._set_api_data(
                ["title", "channel", "length", "thumbnails"], album_track
            )
            for video, album_track in zip(videos, album_tracks)
        ]

        Video.load_info(
            [x for _, x in zip(range(Playlist.playlist_max_videos), videos)]
        )

        return json.loads(
            json.dumps({"items": items}, sort_keys=False, indent=1)
        )

    @classmethod
    def list_playlistitems(cls, id, page=None, max_results=None):
        result = ytmusic.get_album(browseId=id)
        items = [
            cls.playlist_item_to_video(item, result["thumbnails"][0])
            for item in result["tracks"]
        ]
        ajax = None
        return json.loads(
            json.dumps(
                {"nextPageToken": ajax, "items": items},
                sort_keys=False,
                indent=1,
            )
        )
