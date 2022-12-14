import json
from concurrent.futures import as_completed
from concurrent.futures.thread import ThreadPoolExecutor
from itertools import repeat

import pykka
from ytmusicapi import YTMusic

from mopidy_youtube import logger
from mopidy_youtube.apis import youtube_japi
from mopidy_youtube.apis.json_paths import traverse, ytmErrorThumbnailPath
from mopidy_youtube.apis.ytm_item_to_video import ytm_item_to_video
from mopidy_youtube.comms import Client
from mopidy_youtube.youtube import Playlist, Video
from mopidy_youtube.data import extract_playlist_id

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
            ytmusic = YTMusic(auth=auth, requests_session=self.session)
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

        # this is untested - try to add artist and channel to related
        # videos by calling get_song for each related song
        # this would be faster with threading, but it all happens in the
        # background, so who cares?

        # What is better: get_watch_playlist or get_song_related?  Are they different?

        get_watch_playlist = {}

        try:
            logger.debug(
                f"youtube_music list_related_videos triggered "
                f"ytmusic.get_watch_playlist: {video_id}"
            )

            get_watch_playlist = ytmusic.get_watch_playlist(video_id)
            related_browseId = get_watch_playlist.get("related", "none")

        except Exception as e:
            logger.error(
                f"youtube_music list_related_videos get_watch_playlist "
                f"error:{e}. videoId: {video_id}"
            )

        related_videos = []
        get_song_related_tracks = []
        try:
            logger.debug(
                f"youtube_music list_related_videos triggered "
                f"ytmusic.get_song_related ({related_browseId})"
            )
            get_song_related_tracks = ytmusic.get_song_related(related_browseId)[0][
                "contents"
            ]

            logger.debug(
                f"youtube_music list_related_videos triggered "
                f"ytmusic.get_song for {len(related_videos)} tracks."
            )
            related_videos = [
                ytmusic.get_song(track["videoId"])["videoDetails"]
                for track in get_song_related_tracks
            ]

        except Exception as e:
            logger.error(
                f"youtube_music list_related_videos error:{e} "
                f"Related_browseId: {related_browseId}"
            )

        if len(related_videos) < 10:
            logger.warn(
                f"get_song_related returned {len(related_videos)} tracks. "
                f"Trying get_watch_playlist['tracks'] for more"
            )
            try:
                logger.debug(
                    f"youtube_music list_related_videos triggered "
                    f"ytmusic.get_song for {len(get_watch_playlist['tracks'])} tracks"
                )

                related_videos.extend(
                    [
                        ytmusic.get_song(track["videoId"])["videoDetails"]
                        for track in get_watch_playlist["tracks"]
                    ]
                )
            except Exception as e:
                logger.error(f"youtube_music list_related_videos error:{e}")

        related_albums = set()
        for item in related_videos:
            for related_track in get_song_related_tracks:
                if item["videoId"] == related_track["videoId"]:
                    if "album" in related_track:
                        item["album"] = related_track["album"]
                        if "id" in related_track["album"]:
                            related_albums.add(related_track["album"]["id"])
                    if "artists" in related_track:
                        item["artists"] = related_track["artists"]

        with ThreadPoolExecutor() as executor:
            executor.submit(cls.list_playlists(related_albums))
            executor.shutdown(wait=False)

        tracks = [
            ytm_item_to_video(track)
            for track in related_videos
            if track["videoId"] is not None
        ]

        # sometimes, ytmusic.get_watch_playlist seems to return very few, or even
        # only one, related video, which may be the original video, itself.  If this
        # happens, get related videos using the jAPI.
        if len(tracks) < 10:
            logger.warn(
                f"get_song_related and get_watch_playlist only returned "
                f"{len(tracks)} tracks. Trying youtube_japi.jAPI.list_related_videos"
            )
            japi_related_videos = youtube_japi.jAPI.list_related_videos(video_id)
            tracks.extend(japi_related_videos["items"])

        logger.debug(
            f"youtube_music list_related_videos returned {len(tracks)} tracks."
        )

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

        # deal with errors
        for result in results:
            if result["playabilityStatus"]["status"] == "ERROR":
                result["title"] = result["playabilityStatus"]["reason"]
                result["lengthMs"] = 0
                result["channel"] = result["playabilityStatus"]["reason"]
                result["videoId"] = result["playabilityStatus"]["contextParams"][:11]
                result["thumbnail"] = {
                    "thumbnails": [
                        {
                            "url": f"https:{traverse(result, ytmErrorThumbnailPath)['url']}",
                            "width": traverse(result, ytmErrorThumbnailPath)["width"],
                            "height": traverse(result, ytmErrorThumbnailPath)["height"],
                        }
                    ]
                }

        # hack to deal with ytmusic.get_songs returning ['thumbnail']['thumbnails']
        # instead of ['thumbnails']
        [
            video.update({"thumbnails": video["thumbnail"]["thumbnails"]})
            for video in results
            if "thumbnail" in video
        ]

        try:
            items = [ytm_item_to_video(result) for result in results]
        except Exception as e:
            logger.error(
                f"youtube_music list_videos ytm_item_to_video error {e}: {results}"
            )
            return

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
            f"youtube_music list_playlists triggered "
            f"_get_playlist_or_album x {len(ids)}: {ids}"
        )

        with ThreadPoolExecutor() as executor:
            futures = {
                executor.submit(cls._get_playlist_or_album, id): id for id in ids
            }
            for future in as_completed(futures):
                try:
                    results.append(future.result())
                except Exception as e:
                    logger.error(
                        f"youtube_music list_playlists "
                        f"_get_playlist_or_album {e}, {futures[future]}"
                    )

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

        logger.debug(f"youtube_music list_playlistitems for playlist {id}")

        result = cls._get_playlist_or_album(id)
        result["playlistId"] = id
        playlist = cls.yt_listitem_to_playlist(result)

        # just in case: create the Playlist object and set api data,
        # to avoid list_playlist calling ytmusic.get_playlist if
        # the Playlist object doesn't exist

        pl = Playlist.get(playlist["id"]["playlistId"])
        pl._set_api_data(["title", "video_count", "thumbnails", "channel"], playlist)

        # why isn't the following line a good substitute for the two lines above?
        # cls._create_playlist_objects([playlist])

        items = [
            track for track in playlist["tracks"] if track["id"]["videoId"] is not None
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
                {"nextPageToken": ajax, "items": items},
                sort_keys=False,
                indent=1,
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
                        f"ytmusic.get_library_playlists and "
                        f"ytmusic.get_library_albums: {channel_id}"
                    )
                    results = ytmusic.get_library_playlists()
                    albums = ytmusic.get_library_albums()
                    cls.process_albums(albums)
                    results.extend(albums)
                    if channel_id:
                        logger.debug(
                            f"youtube_music list_channelplaylists triggered "
                            f"ytmusic.get_user: {channel_id}"
                        )
                        channelTitle = ytmusic.get_user(channel_id)["name"]
                    else:
                        channelTitle = "unknown"

                except Exception as e:
                    logger.debug(f"youtube_music.list_channelplaylists exception {e}")

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
                    logger.debug(
                        f"youtube_music list_channelplaylists triggered "
                        f"ytmusic.get_artist: {channel_id}"
                    )
                    user = ytmusic.get_artist(channel_id)
                    results = user["albums"]["results"]
                    channelTitle = user["name"]

        [
            item.setdefault("playlistId", item["browseId"])
            for item in results
            if "browseId" in item
        ]

        items = [
            cls.yt_listitem_to_playlist(item, channelTitle)
            for item in results
            if not item["playlistId"] == "LM"
        ]
        [item.update({"id": item["id"]["playlistId"]}) for item in items]
        return json.loads(json.dumps({"items": items}, sort_keys=False, indent=1))

    # methods below are mostly internal, for use by the api methods above (which replicate
    # the methods from the youtube API)

    @classmethod
    def search_songs(cls, q):
        logger.debug(f"youtube_music search_songs triggered ytmusic.search: {q}")
        results = ytmusic.search(query=q, filter="songs", limit=Video.search_results)

        songs = [
            ytm_item_to_video(track)
            for track in results
            if track["videoId"] is not None
        ]

        # listplids = cls.list_playlists([extract_playlist_id(song["album"]["uri"]) for song in songs if song["track_no"] == None and "album" in song and not song["album"]["uri"].startswith("PL")])
        # logger.info(listplids)
        # cls.process_albums(listplids)
        # for song in songs:
        #     if song["track_no"] == None and "album" in song and not song["album"]["uri"].startswith("PL"):
        #         album_id = extract_playlist_id(song["album"]["uri"])
        #         logger.info(album_id)
        #         album_tracks = cls.list_playlistitems(album_id)
        #         # logger.info(album_tracks)
        #         logger.info([track["id"] for track in album_tracks["items"]].index(song["id"]["videoId"])+1)
        #         song["track_no"] = [track["id"] for track in album_tracks["items"]].index(song["id"]["videoId"])
        #         # logger.info(f"track no {[track['id']['videoId'] for track in album_tracks].index[song['id']['videoId']]}")

        return songs

    @classmethod
    def search_albums(cls, q):

        logger.debug(f"youtube_music search_albums triggered ytmusic.search: {q}")

        results = ytmusic.search(query=q, filter="albums", limit=Video.search_results)
        return cls.process_albums(results)

    @classmethod
    def process_albums(cls, results):
        albums = []

        def job(result):
            logger.debug(
                f"youtube_music process_albums triggered "
                f"ytmusic.get_album: {result['browseId']}"
            )
            # ytmusic.get_album is necessary to get the number of tracks
            ytmusic_album = ytmusic.get_album(result["browseId"])
            ytmusic_album.update({"playlistId": result["browseId"]})
            album = cls.yt_listitem_to_playlist(ytmusic_album)
            return album

        with ThreadPoolExecutor() as executor:
            futures = {executor.submit(job, result): result for result in results}
            for future in as_completed(futures):
                try:
                    albums.append(future.result())
                except Exception as e:
                    logger.error(
                        f"youtube_music process_albums get_album error {e}, {futures[future]}"
                    )

        # given we're calling ytmusic.get_album, which returns tracks, we might
        # as well create the playlist objects and the related video objects.
        cls._create_playlist_objects(albums)

        return albums

    def yt_listitem_to_playlist(item, channelTitle=None):
        try:
            playlistId = item["playlistId"]
        except Exception as e:
            logger.error(f"yt_listitem_to_playlist, no playlistId: {item}, {e}")
            playlistId = None  # or should it just stop and return?

        if "count" in item:
            itemCount = int(item["count"].replace(",", ""))
        else:
            itemCount = item.get("trackCount", "0")

        if "artists" in item and item["artists"]:
            if isinstance(item["artists"], list):
                channelTitle = item["artists"][0]["name"]
            else:
                channelTitle = item["artists"]

        playlist = {
            "id": {"kind": "youtube#playlist", "playlistId": playlistId},
            "snippet": {
                "title": item.get("title", "Unknown"),
                "resourceId": {"playlistId": item["playlistId"]},
                "thumbnails": {"default": item["thumbnails"][-1]},
                "channelTitle": channelTitle,
            },
            "contentDetails": {"itemCount": itemCount},
            "artists": item.get("artists", None),
        }
        if "tracks" in item:
            fields = ["artists", "thumbnails"]
            [
                track.update({field: item[field]})
                for field in fields
                for track in item["tracks"]
                if track[field] is None
            ]

            if (
                item.get("type") == "Album"
            ):  # there may be other "types" for which this works? "EP"? "Single"?
                [
                    track.update({"track_no": (number)})
                    for number, track in enumerate(item["tracks"], 1)
                ]

            if "title" in item and "playlistId" in item:
                [
                    track.update(
                        {
                            "album": {
                                "name": item["title"],
                                "id": item["playlistId"],
                            }
                        }
                    )
                    for track in item["tracks"]
                    if "album" not in track
                    or isinstance(track["album"], str)
                    or track["album"] is None
                ]

            playlist["tracks"] = [
                ytm_item_to_video(track)
                for track in item["tracks"]
                if track["videoId"] is not None
            ]

        return playlist

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
                fields = [
                    "title",
                    "channel",
                    "length",
                    "thumbnails",
                    "album",
                    "artists",
                ]
                if "track_no" in track:
                    fields.append("track_no")
                video._set_api_data(fields, track)
                plvideos.append(video)

            pl._videos.set(
                [x for _, x in zip(range(Playlist.playlist_max_videos), plvideos)]
            )
