import json
import re
from concurrent.futures.thread import ThreadPoolExecutor

from ytmusicapi import YTMusic

from mopidy_youtube import logger
from mopidy_youtube.youtube import Client, Video

ytmusic = None
own_channel_id = None


# Direct access to YouTube Music API
#
class Music(Client):
    endpoint = None
    searchEndpoint = None

    def __init__(self, proxy, headers, *args, **kwargs):
        global ytmusic
        super().__init__(proxy, headers, *args, **kwargs)
        auth = (
            None
            if headers.get("Cookie") == "PREF=hl=en; CONSENT=YES+20210329;"
            else json.dumps(headers)
        )
        try:
            ytmusic = YTMusic(auth=auth)
        except Exception as e:
            logger.error("YTMusic init error: %s", str(e))
            ytmusic = YTMusic()

    @classmethod
    def search(cls, q):
        search_results = []
        album_results = cls.search_albums(q)
        [
            search_results.append(result)
            for result in album_results[: int(Video.search_results)]
        ]
        song_results = cls.search_songs(q)
        [
            search_results.append(result)
            for result in song_results[: int(Video.search_results)]
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
    def list_channelplaylists(cls, channel_id):

        # this really should be ytmusic.get_user_playlists(), I think, with channel_id
        # controlling which channel's (user's) playlists are retrieved. get_library_playlists()
        # allows only the playlists of the authenticated user.
        # sigma67 says that ytmusic.get_user_playlists should work without authentication
        # but I can't get it to work.

        results = []
        # if channel_id is None or own_channel_id then try to retrieve public and private playlists
        if channel_id in (None, own_channel_id):
            try:
                results = ytmusic.get_library_playlists()
            except Exception as e:
                logger.info(f"list_channelplaylists exception {e}")
                if channel_id:
                    results = ytmusic.get_user(channel_id)["playlists"][
                        "results"
                    ]
        else:  # if channel_id is not own channel_id retrieve only public playlists:
            results = ytmusic.get_user(channel_id)["playlists"]["results"]

        if channel_id:
            channelTitle = ytmusic.get_user(channel_id)["name"]
        else:
            channelTitle = "unknown"

        items = [
            {
                "id": item["playlistId"],
                "contentDetails": {
                    "itemCount": int(item.get("count", "1").replace(",", ""))
                },
                "snippet": {
                    "title": item.get("title", "Unknown"),
                    "resourceId": {"playlistId": item["playlistId"]},
                    # TODO: full support for thumbnails
                    "thumbnails": {"default": item["thumbnails"][0]},
                    "channelTitle": channelTitle,
                },
            }
            for item in results
        ]
        return json.loads(
            json.dumps({"items": items}, sort_keys=False, indent=1)
        )

    @classmethod
    def search_songs(cls, q):
        results = ytmusic.search(
            query=q, filter="songs", limit=Video.search_results
        )

        songs = [
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
                    "channelTitle": item["artists"][0]["name"],
                    "album": item["album"],
                    "artists": item["artists"],
                },
            }
            for item in results
        ]
        return songs

    @classmethod
    def ytplaylist_item_to_video(cls, item, thumbnail):
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
                        re.match(cls.time_regex, item["duration"])
                    )
                },
                "snippet": {
                    "title": item["title"],
                    "resourceId": {"videoId": item["videoId"]},
                    # TODO: full support for thumbnails
                    "thumbnails": {"default": thumbnail},
                    "channelTitle": item["artists"][0]["name"],
                },
            }
        )
        return video

    @classmethod
    def ytalbum_item_to_video(cls, item, thumbnail):
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
        albums = []
        results = ytmusic.search(
            query=q, filter="albums", limit=Video.search_results
        )

        def job(item):
            try:
                album = ytmusic.get_album(item["browseId"])
                if album is None:
                    return
                else:
                    albumItem = {
                        "id": {
                            "kind": "youtube#playlist",
                            "playlistId": item["browseId"],
                        },
                        "snippet": {
                            "channelTitle": "YouTube Music Album",  # item["type"],
                            "thumbnails": {"default": album["thumbnails"][0]},
                            "title": album["title"],
                        },
                        "contentDetails": {"itemCount": album["trackCount"]},
                    }
                    albums.append(albumItem)

            except Exception as e:
                logger.error('search_albums error "%s"', e)

        with ThreadPoolExecutor() as executor:
            executor.map(job, results)
        return albums

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

        items = [
            {
                "id": result["playlistId"],
                "snippet": {
                    "title": result["title"],
                    "thumbnails": {"default": result["thumbnails"][0]},
                    # apparently, result["artist"] can be empty
                    "channelTitle": result["artist"][0]["name"],
                },
                "contentDetails": {"itemCount": result["trackCount"]},
            }
            for result in results
        ]

        # get the videos in the playlist and
        # start loading video info in the background
        # this isn't really part of the api - should it be removed? does it
        # speed anything up?

        # album_tracks = [
        #     cls.ytalbum_item_to_video(track, result["thumbnails"][0])
        #     for result in results
        #     for track in result["tracks"]
        # ]
        # videos = [
        #     Video.get(album_track["snippet"]["resourceId"]["videoId"])
        #     for album_track in album_tracks
        # ]
        # [
        #     video._set_api_data(
        #         ["title", "channel", "length", "thumbnails"], album_track
        #     )
        #     for video, album_track in zip(videos, album_tracks)
        # ]

        # Video.load_info(
        #     [x for _, x in zip(range(Playlist.playlist_max_videos), videos)]
        # )

        return json.loads(
            json.dumps({"items": items}, sort_keys=False, indent=1)
        )

    @classmethod
    def list_playlistitems(cls, id, page=None, max_results=None):
        if id.startswith("PL"):
            result = ytmusic.get_playlist(id)
            items = [
                cls.ytplaylist_item_to_video(item, result["thumbnails"][0])
                for item in result["tracks"]
            ]
        else:
            result = ytmusic.get_album(id)
            items = [
                cls.ytalbum_item_to_video(item, result["thumbnails"][0])
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
