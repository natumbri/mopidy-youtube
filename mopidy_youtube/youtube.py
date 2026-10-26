import importlib
import json
import os
import threading
import time
from queue import Full
from concurrent.futures.thread import ThreadPoolExecutor

import pykka
from cachetools import TTLCache, cached

from mopidy.models import Image

from mopidy_youtube import logger, runtime
from mopidy_youtube.async_utils import async_property, is_future_set
from mopidy_youtube.converters import convert_video_to_track
from mopidy_youtube.media import extract_audio_url, is_live_info, is_live_item
from mopidy_youtube.data import extract_playlist_id, extract_video_id
from mopidy_youtube.resolver import get_youtube_dl_module, resolve_audio_url
from mopidy_youtube.timeformat import ISO8601_to_seconds

api_enabled = False
channel = None
cache_location = None
musicapi_enabled = None
musicapi_cookiefile = None
youtube_dl = None
youtube_dl_package = "yt_dlp"
search_lock = threading.Lock()
search_in_progress = False
search_last_started = 0.0


def sync_runtime_module_globals():
    global api_enabled, channel, cache_location, musicapi_enabled, musicapi_cookiefile
    global youtube_dl, youtube_dl_package, search_lock, search_in_progress, search_last_started

    api_enabled = runtime.api_enabled
    channel = runtime.channel
    cache_location = runtime.cache_location
    musicapi_enabled = runtime.musicapi_enabled
    musicapi_cookiefile = runtime.musicapi_cookiefile
    youtube_dl = runtime.youtube_dl
    youtube_dl_package = runtime.youtube_dl_package
    search_lock = runtime.search_lock
    search_in_progress = runtime.search_in_progress
    search_last_started = runtime.search_last_started


sync_runtime_module_globals()


class Entry:
    """
    Entry is a base class of Video and Playlist.

    The Video / Playlist classes can be used to load YouTube data. If
    'api_enabled' is true (and a valid youtube_api_key supplied), most data are
    loaded using the (very much faster) YouTube Data API. If 'api_enabled' is
    false, most data are loaded using requests and regex. Requests and regex
    is many times slower than using the API.

    eg
      video = youtube.Video.get('7uj0hOIm2kY')
      video.length   # non-blocking, returns future
      ... later ...
      print video.length.get()  # blocks until info arrives, if it hasn't already

    Entry is a base class of Video and Playlist
    """

    cache_max_len = 4000
    cache_ttl = 21600
    search_results = 15
    playlist_max_videos = 50

    cache = TTLCache(maxsize=cache_max_len, ttl=cache_ttl)

    @classmethod
    @cached(cache=cache)
    def get(cls, id):
        """
        Use Video.get(id), Playlist.get(id), instead of Video(id), Playlist(id),
        to fetch a cached object, if available
        """

        obj = cls()
        obj.id = id
        return obj

    @classmethod
    def create_object(cls, item):
        if not item or "id" not in item or not isinstance(item["id"], dict):
            return None

        if is_live_item(item):
            logger.info("Skipping live/upcoming YouTube search result: %s", item)
            return None

        kind = item["id"].get("kind")
        if kind == "youtube#video":
            video_id = item["id"].get("videoId")
            if not video_id:
                return None
            obj = Video.get(video_id)
        elif kind == "youtube#playlist":
            playlist_id = item["id"].get("playlistId")
            if not playlist_id:
                return None
            obj = Playlist.get(playlist_id)
        else:
            return None

        minimum_fields = ["title", "channel"]
        item, extended_fields = cls.extend_fields(item, minimum_fields)
        obj._set_api_data(extended_fields, item)
        return obj

    @classmethod
    def search(cls, q):
        """Search for both videos and playlists using a single API call."""

        q = (q or "").strip()
        if not q:
            logger.warning("youtube search skipped: empty query")
            return []

        with runtime.search_lock:
            if runtime.search_in_progress:
                logger.warning(
                    'youtube search skipped while previous search is still running: "%s"',
                    q,
                )
                return []

            runtime.search_in_progress = True
            runtime.search_last_started = time.monotonic()

        try:
            try:
                data = cls.api.search(q)
                if "error" in data:
                    raise Exception(data["error"])
            except Exception as e:
                logger.exception('youtube search error for query "%s"', q)
                return []

            items = data.get("items", [])

            def map_item(item):
                try:
                    return cls.create_object(item)
                except Exception:
                    logger.exception("map error while processing item: %r", item)
                    return None

            return [obj for obj in (map_item(item) for item in items) if obj is not None]

        finally:
            with runtime.search_lock:
                runtime.search_in_progress = False

    def _ensure_future(self, field_name):
        future_name = "_" + field_name
        future = self.__dict__.get(future_name)
        if future is None:
            future = self.__dict__[future_name] = pykka.ThreadingFuture()
        return future

    @staticmethod
    def _is_future_set(future):
        return is_future_set(future)

    @classmethod
    def _add_futures(cls, futures_list, fields):
        """Create missing future slots for each field on every object.

        An existing future that has not yet been populated is still considered
        pending, so async properties re-enter their loader instead of silently
        treating themselves as already resolved.
        """

        def add(obj):
            if obj is None:
                return False

            added = False
            for field in fields:
                future_name = "_" + field
                future = obj.__dict__.get(future_name)
                if future is None:
                    obj.__dict__[future_name] = pykka.ThreadingFuture()
                    added = True
                elif not cls._is_future_set(future):
                    added = True
            return added

        return [obj for obj in futures_list if add(obj)]

    @async_property
    def title(self):
        self.load_info([self])

    @async_property
    def channel(self):
        self.load_info([self])

    @async_property
    def channelId(self):
        self.load_info([self])

    def _set_api_data(self, fields, item):
        """Populate the async property futures for the given API fields."""

        for field in fields:
            future = self._ensure_future(field)

            if not item:
                value = None
            elif field == "title":
                value = item["snippet"]["title"]
            elif field == "channel":
                value = item["snippet"]["channelTitle"]
            elif field == "owner_channel":
                value = item["snippet"]["videoOwnerChannelTitle"]
            elif field == "album":
                value = item["album"]
            elif field == "artists":
                value = item["artists"]
            elif field == "length":
                value = ISO8601_to_seconds(item["contentDetails"]["duration"])
            elif field == "video_count":
                value = min(
                    int(item["contentDetails"]["itemCount"]),
                    int(self.playlist_max_videos),
                )
            elif field == "thumbnails":
                value = [
                    Image(
                        uri=details["url"],
                        width=details["width"],
                        height=details["height"],
                    )
                    for (quality, details) in item["snippet"]["thumbnails"].items()
                    if quality in ["default", "medium", "high"]
                ] or None
            elif field == "channelId":
                value = item["snippet"]["channelId"]
            elif field == "track_no":
                value = item["track_no"]
            else:
                continue

            try:
                future.set(value)
            except Full:
                logger.debug(
                    "Future already set for field %s on object %s, skipping",
                    field,
                    getattr(self, "id", None),
                )

    @classmethod
    def extend_fields(self, item, fields):
        if not item:
            return (None, list(set(fields)))

        extended_fields = set(fields)

        if "snippet" not in item or not isinstance(item["snippet"], dict):
            item["snippet"] = {}

        if "channelId" in item["snippet"]:
            extended_fields.add("channelId")

        if "videoOwnerChannelTitle" in item["snippet"]:
            extended_fields.add("owner_channel")
        elif "channelTitle" in item["snippet"]:
            extended_fields.add("channel")
        else:
            logger.warning("no channel or owner_channel for item: %r", item)
            item["snippet"]["channelTitle"] = "unknown"

        if "thumbnails" in item["snippet"]:
            extended_fields.add("thumbnails")

        if "artists" in item:
            extended_fields.add("artists")
        elif "channelTitle" in item["snippet"] and "channelId" in item["snippet"]:
            item["artists"] = [
                {
                    "name": f'{item["snippet"]["channelTitle"]} (Channel)',
                    "uri": f'yt:channel:{item["snippet"]["channelId"]}',
                }
            ]
            extended_fields.add("artists")

        if "album" in item:
            extended_fields.add("album")

        if "track_no" in item:
            extended_fields.add("track_no")

        if "contentDetails" in item and isinstance(item["contentDetails"], dict):
            if "duration" in item["contentDetails"]:
                extended_fields.add("length")
            elif "itemCount" in item["contentDetails"]:
                extended_fields.add("video_count")

        return (item, list(extended_fields))


class Video(Entry):
    total_bytes = 0

    @classmethod
    def load_info(cls, listOfVideos):
        """
        loads title, length, channel of multiple videos using one API call for
        every 50 videos. API calls are split in separate threads.
        """
        minimum_fields = ["title", "length", "channel"]
        listOfVideos = cls._add_futures(listOfVideos, minimum_fields)

        def job(sublist):
            try:
                data = cls.api.list_videos([x.id for x in sublist])
                item_dict = {item["id"]: item for item in data["items"]}
            except Exception as e:
                logger.error('list_videos error "%s"', e)
                item_dict = {}

            for video in sublist:
                try:
                    extended_item = cls.extend_fields(
                        item_dict.get(video.id), minimum_fields
                    )
                    video._set_api_data(extended_item[1], extended_item[0])
                except Exception as e:
                    logger.warning(
                        f"Error {e} setting api data for {video.id}; "
                        f"probably private or deleted"
                    )
                    error_dict = {
                        "contentDetails": {"duration": "PT0S"},
                        "id": video.id,
                        "snippet": {
                            "channelTitle": "Video unplayable",
                            "title": "Video unplayable",
                        },
                    }
                    video._set_api_data(minimum_fields, error_dict)

        with ThreadPoolExecutor() as executor:
            # make sure order is deterministic so that HTTP requests are replayable in tests
            executor.map(
                job,
                [listOfVideos[i : i + 50] for i in range(0, len(listOfVideos), 50)],
            )

    @async_property
    def related_videos(self):
        """
        loads title, thumbnails, channel (and, optionally, length) of videos
        that are related to a video.  Number of related videos returned is
        uncertain. Usually between 1 and 19.  Does not return related
        playlists.
        """

        requiresRelatedVideos = self._add_futures([self], ["related_videos"])

        if requiresRelatedVideos:
            data = self.api.list_related_videos(self.id)
            relatedvideos = []

            for item in data.get("items", []):
                if "snippet" not in item:
                    continue

                minimum_fields = ["title", "channel"]
                item, extended_fields = self.extend_fields(item, minimum_fields)
                video = Video.get(item["id"]["videoId"])
                video._set_api_data(extended_fields, item)
                relatedvideos.append(video)

            # start loading video info in the background
            Video.load_info(relatedvideos)
            self._related_videos.set(relatedvideos)

    @async_property
    def length(self):
        self.load_info([self])

    @async_property
    def thumbnails(self):
        # make it "async" for uniformity with Playlist.thumbnails
        requiresThumbnail = self._add_futures([self], ["thumbnails"])

        if requiresThumbnail:
            self._thumbnails.set(
                [
                    Image(
                        uri=f"https://i.ytimg.com/vi_webp/{self.id.split(':')[-1]}/maxresdefault.webp"
                    )
                ]
            )

    @async_property
    def album(self):
        # make it "async" for uniformity with Playlist.thumbnails
        requiresAlbumName = self._add_futures([self], ["album"])

        if requiresAlbumName:
            # ultimate fallback
            self._album.set({"name": "YouTube Playlist", "uri": None})

    @async_property
    def track_no(self):
        requiresTrack_No = self._add_futures([self], ["track_no"])

        if requiresTrack_No:
            album = self.album.get()
            album_uri = album.get("uri") if isinstance(album, dict) else None
            playlist_id = extract_playlist_id(album_uri) if album_uri else ""

            if playlist_id:
                album_response = self.api.list_playlistitems(playlist_id, "", 50)
                album_tracks = (
                    album_response.get("items", [])
                    if isinstance(album_response, dict)
                    else album_response or []
                )
                video_ids = [
                    track_id
                    for track in album_tracks
                    for track_id in [
                        (
                            track["id"].get("videoId")
                            if isinstance(track.get("id"), dict)
                            else track.get("id")
                            if isinstance(track.get("id"), str)
                            else None
                        )
                    ]
                    if track_id
                ]
                if not video_ids:
                    video_ids = [
                        resource_id.get("videoId")
                        for track in album_tracks
                        for resource_id in [
                            (track.get("snippet") or {}).get("resourceId") or {}
                        ]
                        if resource_id.get("videoId")
                    ]

                video_id = self.id
                try:
                    track_no = video_ids.index(video_id)
                except ValueError:
                    track_no = None
                self._track_no.set(track_no)
                logger.debug("track no %s for %s in %s", track_no, self.id, playlist_id)
            else:
                # ultimate fallback to None? Does this work?
                self._track_no.set(None)

    @async_property
    def artists(self):
        # make it "async" for uniformity with Playlist.thumbnails
        requiresArtists = self._add_futures([self], ["artists"])

        if requiresArtists:
            # ultimate fallback
            self._artists.set(
                [{"name": self.channel.get(), "uri": None, "thumbnail": None}]
            )

    @staticmethod
    def _extract_audio_url(info):
        return extract_audio_url(info)

    @async_property
    def audio_url(self):
        """
        audio_url is the only property retrieved using yt-dlp, and it's much more
        expensive than the rest. If caching is turned on and the track is cached,
        return a (file) URL pointing to the cached file. If caching is turned on and
        the track isn't cached, start caching it and, once 2 percent has been
        cached, return an (http) URL pointing to the cached file. If caching is not
        turned on, return a URL obtained with yt-dlp.
        """

        # from @blacklight (https://github.com/blacklight/mopidy-youtube)
        global youtube_dl, youtube_dl_package

        if runtime.youtube_dl is not None:
            youtube_dl = runtime.youtube_dl
            youtube_dl_package = runtime.youtube_dl_package
        elif youtube_dl is None:
            youtube_dl, youtube_dl_package = get_youtube_dl_module(youtube_dl_package)
            runtime.youtube_dl = youtube_dl
            runtime.youtube_dl_package = youtube_dl_package
        logger.debug(f"using {youtube_dl_package} package for youtube_dl")

        # When caching, is it possible to set the audio_url part-way through
        # a download so audio can start playing quicker?

        def my_hook(d):
            if d["status"] == "finished" and not self.total_bytes:
                fileUri = (
                    # if it is finished, don't need to serve it up with tornado...
                    f"file://{d['filename']}"
                )
                logger.debug(
                    f"audio_url not set during downloading; setting audio_url now:"
                    f" {fileUri}, {os.path.basename(d['filename'])}"
                )

                self.total_bytes = d.get("total_bytes", d["info_dict"].get("filesize"))

                logger.debug(
                    f"expected length of {os.path.basename(d['filename'])}: "
                    f"{self.total_bytes}"
                )
                self._audio_url.set(fileUri)

            if d["status"] == "downloading":
                p = d["_percent_str"]
                p = float(p.replace("%", ""))
                logger.debug(f"percent cached: {p}%, {os.path.basename(d['filename'])}")

                # get 2% before setting audio_url; once self.total_bytes has a value,
                # audio_url is set, so no need to do again; there seems to be problems
                # with some formats that do not support seeking - limit to .webm
                if (
                    p > 2
                    and not self.total_bytes
                    and os.path.splitext(d["filename"])[1] == ".webm"
                ):
                    httpUri = (
                        f"http://localhost:{self.http_port}/youtube/"
                        f"{os.path.basename(d['filename'])}"
                    )
                    logger.debug(
                        f"setting cached audio_url: {httpUri}, "
                        f"{os.path.basename(d['filename'])}"
                    )
                    self.total_bytes = d.get(
                        "total_bytes", d["info_dict"].get("filesize")
                    )
                    logger.debug(
                        f"expected length of {os.path.basename(d['filename'])}: "
                        f"{self.total_bytes}"
                    )
                    self._audio_url.set(httpUri)

        requiresUrl = self._add_futures([self], ["audio_url"])
        if requiresUrl:
            try:
                ytdl_options = {
                    "format": "bestaudio/ogg/mp3/m4a/best",
                    "proxy": self.proxy,
                    "cachedir": False,
                    "nopart": True,
                    "retries": 10,
                }
                if runtime.musicapi_cookiefile:
                    ytdl_options["cookiefile"] = runtime.musicapi_cookiefile
                base_url = "https://www.youtube.com"
                if runtime.musicapi_enabled:
                    # High quality music streams are only available to YouTube
                    # Premium users when using YouTube Music.
                    base_url = "https://music.youtube.com"

                ytdl_extract_info_options = {
                    "url": f"{base_url}/watch?v={self.id}",
                    "ie_key": None,
                    "extra_info": {},
                    "process": True,
                    "force_generic_extractor": False,
                }

                if runtime.youtube_dl_package == "yt_dlp":
                    ytdl_options["no_color"] = True

                if runtime.cache_location:
                    resolved = resolve_audio_url(
                        self,
                        ytdl_options={**ytdl_options, "progress_hooks": [my_hook]},
                        ytdl_extract_info_options=ytdl_extract_info_options,
                        cache_location=runtime.cache_location,
                        youtube_dl=runtime.youtube_dl,
                        youtube_dl_package=runtime.youtube_dl_package,
                    )
                    if resolved is not None:
                        self._audio_url.set(resolved)
                    else:
                        self._audio_url.set(None)
                    return

                with runtime.youtube_dl.YoutubeDL(ytdl_options) as ydl:
                    info = ydl.extract_info(
                        **ytdl_extract_info_options,
                        download=False,
                    )

                audio_url = self._extract_audio_url(info)
                if not audio_url:
                    logger.warning(
                        "yt-dlp did not provide a direct audio URL for %s; info keys: %s",
                        self.id,
                        sorted(info.keys()) if isinstance(info, dict) else type(info).__name__,
                    )
                    self._audio_url.set(None)
                    return

                self._audio_url.set(audio_url)

            except Exception as e:
                logger.exception(f"audio_url error {e} (videoId: {self.id})")
                self._audio_url.set(None)
                return

    @property
    def is_video(self):
        return True


class Playlist(Entry):
    _videos_executor = None

    @classmethod
    def get_videos_executor(cls):
        if cls._videos_executor is None:
            cls._videos_executor = ThreadPoolExecutor(max_workers=1)
        return cls._videos_executor

    @classmethod
    def load_info(cls, listOfPlaylists):
        """
        loads title, thumbnails, video_count, channel of multiple playlists using
        one API call for every 50 lists. API calls are split in separate threads.
        """
        minimum_fields = ["title", "video_count", "thumbnails", "channel"]
        listOfPlaylists = cls._add_futures(listOfPlaylists, minimum_fields)

        def job(sublist):
            item_dict = {}

            try:
                data = cls.api.list_playlists([x.id for x in sublist])
            except Exception as e:
                logger.error(
                    f"Playlist.load_info list_playlists error {e}, {[x.id for x in sublist]}"
                )

            if data:
                item_dict = {item["id"]: item for item in data["items"]}
            for pl in sublist:
                item_dict[pl.id], extended_fields = cls.extend_fields(
                    item_dict.get(pl.id), minimum_fields
                )
                pl._set_api_data(extended_fields, item_dict.get(pl.id))

        with ThreadPoolExecutor() as executor:
            # make sure order is deterministic so that HTTP requests are replayable in tests
            executor.map(
                job,
                [
                    listOfPlaylists[i : i + 50]
                    for i in range(0, len(listOfPlaylists), 50)
                ],
            )

    @async_property
    def videos(self):
        """
        loads the list of videos of a playlist using one API call for every 50
        fetched videos. For every page fetched, Video.load_info is called to
        start loading video info in a separate thread.
        """
        requiresVideos = self._add_futures([self], ["videos"])

        def load_items():
            data = {"items": []}
            page = ""
            while page is not None and len(data["items"]) < self.playlist_max_videos:
                try:
                    max_results = min(
                        int(self.playlist_max_videos) - len(data["items"]), 50
                    )
                    result = self.api.list_playlistitems(self.id, page, max_results)
                except Exception as e:
                    logger.error('Playlist.videos list_playlistitems error "%s"', e)
                    break
                if "error" in result:
                    logger.error(
                        "error in list playlist items data for "
                        "playlist {}, page {}".format(self.id, page),
                    )
                    break
                page = result.get("nextPageToken") or None

                # remove private and deleted videos from items
                filtered_result = [
                    item
                    for item in result["items"]
                    if not (
                        item["snippet"]["title"] in ["Deleted video", "Private video"]
                    )
                ]

                data["items"].extend(filtered_result)

            del data["items"][int(self.playlist_max_videos) :]

            myvideos = []
            for item in data["items"]:
                minimum_fields = ["title"]
                item, extended_fields = self.extend_fields(item, minimum_fields)
                # extended_fields = minimum_fields
                if item["snippet"]["resourceId"]["videoId"] is not None:
                    video = Video.get(item["snippet"]["resourceId"]["videoId"])
                    video._set_api_data(extended_fields, item)
                    myvideos.append(video)

            # start loading video info in the background
            Video.load_info(
                [x for _, x in zip(range(self.playlist_max_videos), myvideos)]
            )

            self._videos.set(
                [x for _, x in zip(range(self.playlist_max_videos), myvideos)]
            )

        if requiresVideos:
            self.get_videos_executor().submit(load_items)
            # load_items()

    @async_property
    def video_count(self):
        self.load_info([self])

    @async_property
    def thumbnails(self):
        self.load_info([self])

    @property
    def is_video(self):
        return False


class Channel(Entry):
    @classmethod
    def playlists(cls, channel_id=None):
        """
        Get all public playlists from the channel.
        """
        minimum_fields = ["title", "video_count"]
        try:
            if channel_id == "root":
                channel_id = channel
            if channel_id is None:
                return None
            data = cls.api.list_channelplaylists(channel_id)
            if "error" in data:
                raise Exception(data["error"])
        except Exception as e:
            logger.error('Channel.playlists list_channelplaylists error "%s"', e)
            print('Channel.playlists list_channelplaylists error "%s"', e)
            return None
        try:
            channel_playlists = []
            for item in data["items"]:
                pl = Playlist.get(item["id"])
                # this doesn't work. adding 'channel' here breaks something
                # item, extended_fields = cls.extend_fields(item, minimum_fields)
                extended_fields = minimum_fields
                pl._set_api_data(extended_fields, item)
                pl.videos  # should we start loading the videos here?
                channel_playlists.append(pl)
            # Playlist.load_info(channel_playlists)  # what does this do, here?
            return channel_playlists
        except Exception as e:
            logger.error('map error "%s"', e)
            return None
