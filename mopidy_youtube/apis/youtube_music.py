import json
import re
from concurrent.futures.thread import ThreadPoolExecutor
from itertools import repeat

import pykka
from ytmusicapi import YTMusic

from mopidy_youtube import logger
from mopidy_youtube.apis import youtube_japi
from mopidy_youtube.comms import Client
from mopidy_youtube.youtube import Playlist, Video

ytmusic = None
own_channel_id = None


# Access to YouTube Music API through ytmusicapi package
# https://github.com/sigma67/ytmusicapi


class Music(Client):
    endpoint = None

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
        """
        search for both songs and albums
        """

        result = []
        futures = []

        search_functions = [cls.search_albums, cls.search_songs]

        with ThreadPoolExecutor() as executor:
            # is this the best way to make this deterministic (map + lambda)?
            futures = executor.map(lambda x, y: x(y), search_functions, repeat(q))
            [result.extend(value[: int(Video.search_results)]) for value in futures]

        return json.loads(json.dumps({"items": result}))

    @classmethod
    def list_related_videos(cls, video_id):
        """
        returns related videos for a given video_id
        """

        related_videos = ytmusic.get_watch_playlist(video_id)

        # hack to deal with ytmusic.get_watch_playlist returning 'thumbnail'
        # instead of 'thumbnails' inside 'tracks'
        [
            related_video.update({"thumbnails": related_video["thumbnail"]})
            for related_video in related_videos["tracks"]
            if "thumbnail" in related_video
        ]

        tracks = [
            cls.yt_item_to_video(track)
            for track in related_videos["tracks"]
            if track["videoId"] is not None
        ]

        # sometimes, ytmusic.get_watch_playlist seems to return very few, or even
        # only one, related video, which may be the original video, itself.  If this
        # happens, get related videos using the jAPI.
        if len(tracks) < 10:
            japi_related_videos = youtube_japi.jAPI.list_related_videos(video_id)
            japi_related_videos["items"].extend(tracks)
            return japi_related_videos

        return json.loads(json.dumps({"items": tracks}, sort_keys=False, indent=1))

    @classmethod
    def list_videos(cls, ids):
        """
        list videos - do we need this? When would it be called? Untested.
        """
        # what follows should work, but it loads each item separately.
        # So, if you have 50 items that's 50 trips to the endpoint.
        results = []

        logger.debug(
            f"youtube_music list_videos triggered ytmusic.get_song x {len(ids)}: {ids}"
        )

        with ThreadPoolExecutor() as executor:
            futures = executor.map(ytmusic.get_song, ids)
            [results.append(value) for value in futures if value is not None]

        # hack to deal with ytmusic.get_songs returning ['thumbnail']['thumbnails']
        # instead of ['thumbnails']
        [
            video.update({"thumbnails": video["thumbnail"]["thumbnails"]})
            for video in results
            if "thumbnail" in video
        ]

        # these the videos that are returned
        items = [cls.yt_item_to_video(result) for result in results]

        [
            item.update({"id": item["id"]["videoId"]})
            for item in items
            if "videoId" in item["id"]
        ]

        return json.loads(json.dumps({"items": items}, sort_keys=False, indent=1))

    @classmethod
    def list_playlists(cls, ids):
        """
        list playlists
        """

        # what follows works, but it loads each playlist separately.
        # So, if you have 50 playlists that's 50 trips to the endpoint.
        # On the plus side, each call also takes care of videos in the
        # playlist.
        results = []

        logger.debug(
            f"youtube_music list_playlists triggered _get_playlist_or_album x {len(ids)}: {ids}"
        )

        with ThreadPoolExecutor() as executor:
            futures = executor.map(cls._get_playlist_or_album, ids)
            [results.append(value) for value in futures if value is not None]

        if len(results) == 0:
            # why would this happen?
            logger.debug(f"list_playlists for {ids} returned no results")
            return None

        # these the playlists that are returned
        items = [cls.yt_listitem_to_playlist(result) for result in results]

        # create the playlist objects and video objects for each track in
        # the playlist, and add the videos to the playlist to avoid
        # list_playlistitems calling ytmusic.get_playlist
        cls._create_playlist_objects(items)

        return json.loads(json.dumps({"items": items}, sort_keys=False, indent=1))

    @classmethod
    def list_playlistitems(cls, id, page=None, max_results=None):

        result = cls._get_playlist_or_album(id)
        result["playlistId"] = id
        result = cls.yt_listitem_to_playlist(result)

        # just in case: create the Playlist object and set api data,
        # to avoid list_playlist calling ytmusic.get_playlist if
        # the Playlist object doesn't exist
        pl = Playlist.get(result["id"]["playlistId"])
        pl._set_api_data(["title", "video_count", "thumbnails", "channel"], result)

        items = [
            track for track in result["tracks"] if track["id"]["videoId"] is not None
        ]

        # why do ytplaylist_item_to_video and ytalbum_item_to_video both include
        # {"id": {"kind": "youtube#video", "videoId": item["videoId"],}} instead of
        # {"id": item["videoId"]}?

        # And, given that they do include the longer one, why isn't the following
        # necessary for compatibility with the youtube API?

        [
            item.update({"id": item["id"]["videoId"]})
            for item in items
            if "videoId" in item["id"]
        ]

        # Because Playlist.videos gets the id from {"snippet": {"resourceId":
        # {"videoId": item["videoId"]},}}. But it doesn't hurt to keep them consistent.
        items = items[:max_results]
        ajax = None
        return json.loads(
            json.dumps(
                {"nextPageToken": ajax, "items": items}, sort_keys=False, indent=1,
            )
        )

    @classmethod
    def list_channelplaylists(cls, channel_id):

        # this really should be ytmusic.get_user_playlists(), I think, with channel_id
        # controlling which channel's (user's) playlists are retrieved. get_library_playlists()
        # allows only the playlists of the authenticated user.
        # sigma67 says that ytmusic.get_user_playlists should work without authentication
        # but I can't get it to work.

        results = []
        channelTitle = None
        # first check if the channel is a proper artist channel, in which case, return
        # albums (and playlists?)
        try:
            channelId = channel_id or own_channel_id
            artist = ytmusic.get_artist(channelId)
            browseId = artist["albums"]["browseId"]
            params = artist["albums"]["params"]
            channelTitle = artist["name"]
            results = ytmusic.get_artist_albums(browseId, params)
            # results.append(ytmusic.get_user_playlists(channelId, params))

        except Exception as e:
            logger.debug(f"youtube_music.list_channelplaylists exception {e}")
            # if channel_id is None or own_channel_id then try to retrieve
            # public and private playlists
            if channel_id in (None, own_channel_id):
                try:
                    logger.debug(
                        f"youtube_music list_channelplaylists triggered "
                        f"ytmusic.get_library_playlists: {channel_id}"
                    )
                    results = ytmusic.get_library_playlists()
                    results.extend(ytmusic.get_library_albums())
                    if channel_id:
                        logger.debug(
                            f"youtube_music list_channelplaylists triggered "
                            f"ytmusic.get_user: {channel_id}"
                        )
                        channelTitle = ytmusic.get_user(channel_id)["name"]
                    else:
                        channelTitle = "unknown"

                except Exception as e:
                    logger.debug(f"list_channelplaylists exception {e}")
                    if channel_id:
                        logger.debug(
                            f"youtube_music list_channelplaylists triggered "
                            f"ytmusic.get_user: {channel_id}"
                        )
                        user = ytmusic.get_user(channel_id)
                        results = user["playlists"]["results"]
                        channelTitle = user["name"]

        else:
            # if channel_id is not None and not own_channel_id
            # retrieve only public playlists:
            logger.debug(
                f"youtube_music list_channelplaylists triggered "
                f"ytmusic.get_user: {channel_id}"
            )
            try:
                user = ytmusic.get_user(channel_id)
                results = user["playlists"]["results"]
                channelTitle = user["name"]
            except Exception:
                user = ytmusic.get_artist(channel_id)
                results = user["albums"]["results"]
                channelTitle = user["name"]

        [
            item.setdefault("playlistId", item["browseId"])
            for item in results
            if "browseId" in item
        ]

        items = [
            {
                "id": item["playlistId"],
                "contentDetails": {
                    "itemCount": int(
                        item.get("count", "0").replace(",", "")
                    )  # is it better for this to be zero or one if "count" is missing?
                },
                "snippet": {
                    "title": item.get("title", "Unknown"),
                    "resourceId": {"playlistId": item["playlistId"]},
                    # TODO: full support for thumbnails
                    "thumbnails": {"default": item["thumbnails"][-1]},
                    "channelTitle": (
                        item["artists"][0]["name"]
                        if "artists" in item
                        else channelTitle
                    ),
                },
            }
            for item in results
            if not item["playlistId"] == "LM"
        ]

        return json.loads(json.dumps({"items": items}, sort_keys=False, indent=1))

    # methods below are mostly internal, for use by the api methods above (which replicate
    # the methods from the youtube API)

    @classmethod
    def search_songs(cls, q):
        logger.debug(f"youtube_music search_songs triggered ytmusic.search: {q}")
        results = ytmusic.search(query=q, filter="songs", limit=Video.search_results)

        songs = [
            cls.yt_item_to_video(track)
            for track in results
            if track["videoId"] is not None
        ]

        return songs

    @classmethod
    def search_albums(cls, q):
        albums = []

        logger.debug(f"youtube_music search_albums triggered ytmusic.search: {q}")

        results = ytmusic.search(query=q, filter="albums", limit=Video.search_results)

        def job(result):
            try:
                logger.debug(
                    f"youtube_music search_albums triggered "
                    f"ytmusic.get_album: {result['browseId']}"
                )
                # ytmusic.get_album is necessary to get the number of tracks
                ytmusic_album = ytmusic.get_album(result["browseId"])
                ytmusic_album.update({"playlistId": result["browseId"]})
                album = cls.yt_listitem_to_playlist(ytmusic_album)
                return album

            except Exception as e:
                logger.error(
                    f"youtube_music search_albums get_album error {e}, {result}"
                )

        with ThreadPoolExecutor() as executor:
            futures = executor.map(job, results)
            [albums.append(value) for value in futures]

        # given we're calling ytmusic.get_album, which returns tracks, we might
        # as well create the playlist objects and the related video objects.
        cls._create_playlist_objects(albums)

        return albums

    def yt_listitem_to_playlist(item):
        try:
            playlistId = item["playlistId"]
        except Exception as e:
            logger.error(f"yt_listitem_to_playlist, no playlistId: {item}, {e}")
            playlistId = None  # or should it just stop and return?

        playlist = {
            "id": {"kind": "youtube#playlist", "playlistId": playlistId},
            "snippet": {
                "title": item["title"],
                "thumbnails": {"default": item["thumbnails"][-1]},
                "channelTitle": item["artists"][0]["name"],
            },
            "contentDetails": {"itemCount": item["trackCount"]},
            "artists": item["artists"],
        }

        if "tracks" in item:
            fields = ["artists", "thumbnails"]
            [
                track.update({field: item[field]})
                for field in fields
                for track in item["tracks"]
                if track[field] is None
            ]

            if "title" in item and "playlistId" in item:
                [
                    track.update(
                        {"album": {"name": item["title"], "id": item["playlistId"],}}
                    )
                    for track in item["tracks"]
                    if "album" not in track or track["album"] is None
                ]

            playlist["tracks"] = [
                Music.yt_item_to_video(track)
                for track in item["tracks"]
                if track["videoId"] is not None
            ]

        return playlist

    def yt_item_to_video(item):

        if "videoDetails" in item:
            item = item["videoDetails"]

        def _convertMillis(milliseconds):
            try:
                hours, miliseconds = divmod(int(milliseconds), 3600000)
            except Exception as e:
                logger.error(f"_convertMillis error: {e}, {milliseconds}")
                return "00:00:00"
            minutes, miliseconds = divmod(miliseconds, 60000)
            seconds = int(miliseconds) / 1000
            return "%i:%02i:%02i" % (hours, minutes, seconds)

        if "duration" in item:
            duration = item["duration"]
        elif "length" in item:
            duration = item["length"]
        elif "lengthMs" in item:
            duration = _convertMillis(item["lengthMs"])
        elif "lengthSeconds" in item:
            duration = _convertMillis(int(item["lengthSeconds"]) * 1000)
        else:
            duration = "00:00:00"
            logger.warn(f"duration missing: {item}")

        duration = "PT" + Client.format_duration(re.match(Client.time_regex, duration))

        if "artists" in item and item["artists"] is not None:
            if isinstance(item["artists"], list):
                channelTitle = item["artists"][0]["name"]
            else:
                channelTitle = item["artists"]
        elif "byline" in item:
            logger.debug(f'byline: {item["byline"]}')
            channelTitle = item["byline"]
        else:
            channelTitle = "unknown"

        # TODO: full support for thumbnails
        try:
            thumbnail = item["thumbnails"][-1]
        except Exception:
            thumbnail = item["thumbnail"]["thumbnails"][-1]

        video = {
            "id": {"kind": "youtube#video", "videoId": item["videoId"]},
            "contentDetails": {"duration": duration},
            "snippet": {
                "title": item["title"],
                "resourceId": {"kind": "youtube#video", "videoId": item["videoId"]},
                "thumbnails": {"default": thumbnail},
                "channelTitle": channelTitle,
            },
        }

        if "album" in item and item["album"] is not None:
            video["album"] = {
                "name": item["album"]["name"],
                "uri": f"yt:playlist:{item['album']['id']}",
            }

        if "artists" in item and isinstance(item["artists"], list):
            video["artists"] = [
                {
                    "name": artist["name"],
                    "uri": f"yt:channel:{artist['id']}",
                    # "thumbnail": ytmusic.get_artist(artist["id"])["thumbnails"][-1]
                }
                for artist in item["artists"]
            ]

        return video

    def _get_playlist_or_album(id):
        if id.startswith("PL"):
            logger.debug(
                f"youtube_music _get_playlist_or_album triggered ytmusic.get_playlist: {id}"
            )
            result = ytmusic.get_playlist(id)
            result["playlistId"] = result["id"]
            result["artists"] = [result["author"]]
        else:
            logger.debug(
                f"youtube_music _get_playlist_or_album triggered ytmusic.get_album: {id}"
            )
            result = ytmusic.get_album(id)
            if "artists" not in result:
                result["artists"] = result["artist"]

        if "playlistId" not in result:
            result["playlistId"] = id

        return result

    def _create_playlist_objects(items):
        for item in items:
            plvideos = []
            pl = Playlist.get(item["id"]["playlistId"])
            pl._set_api_data(["title", "video_count", "thumbnails", "channel"], item)

            pl._videos = pykka.ThreadingFuture()

            for track in item["tracks"]:
                if "album" not in track:
                    track.update(
                        {
                            "album": {
                                "name": item["title"],
                                "id": item["id"]["playlistId"],
                            }
                        }
                    )
                video = Video.get(track["snippet"]["resourceId"]["videoId"])
                video._set_api_data(
                    ["title", "channel", "length", "thumbnails", "album"], track
                )
                plvideos.append(video)

            pl._videos.set(
                [x for _, x in zip(range(Playlist.playlist_max_videos), plvideos)]
            )
