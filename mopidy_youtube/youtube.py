from __future__ import annotations

import os
import threading
from concurrent.futures.thread import ThreadPoolExecutor
from pathlib import Path
from typing import Any, ClassVar, Self

import pykka
from cachetools import TTLCache
from cachetools.keys import hashkey
from mopidy.models import Image
from mopidy.types import Uri

from mopidy_youtube import logger
from mopidy_youtube.async_utils import async_property, is_future_set, set_once
from mopidy_youtube.context import context
from mopidy_youtube.data import extract_playlist_id
from mopidy_youtube.media import extract_audio_url, is_live_item
from mopidy_youtube.resolver import resolve_audio_url
from mopidy_youtube.timeformat import ISO8601_to_seconds


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

    cache: ClassVar[TTLCache[Any, Any]] = TTLCache(maxsize=cache_max_len, ttl=cache_ttl)
    _cache_lock: ClassVar[threading.Lock] = threading.Lock()

    id: str

    @classmethod
    def get(cls, id: str) -> Self:
        """
        Use Video.get(id), Playlist.get(id), instead of Video(id), Playlist(id),
        to fetch a cached object, if available
        """

        key = hashkey(cls, id)
        with cls._cache_lock:
            obj = cls.cache.get(key)
            if obj is None:
                obj = cls()
                obj.id = id
                cls.cache[key] = obj
        return obj

    @classmethod
    def load_info(cls, entries: list[Any]) -> None:
        raise NotImplementedError

    @classmethod
    def create_object(cls, item: dict[str, Any] | None) -> Video | Playlist | None:
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
    def search(cls, q: str | None) -> list[Video | Playlist]:
        """Search for both videos and playlists using a single API call."""

        q = (q or "").strip()
        if not q:
            logger.warning("youtube search skipped: empty query")
            return []

        if not context.begin_search():
            logger.warning(
                'youtube search skipped while previous search is still running: "%s"',
                q,
            )
            return []

        try:
            try:
                data = context.api.search(q)
            except Exception:
                logger.exception('youtube search error for query "%s"', q)
                return []
            if "error" in data:
                logger.error(
                    'youtube search error for query "%s": %s', q, data["error"]
                )
                return []

            items = data.get("items", [])

            def map_item(item: dict[str, Any]) -> Video | Playlist | None:
                try:
                    return cls.create_object(item)
                except Exception:
                    logger.exception("map error while processing item: %r", item)
                    return None

            return [
                obj for obj in (map_item(item) for item in items) if obj is not None
            ]

        finally:
            context.end_search()

    def _ensure_future(self, field_name: str) -> pykka.ThreadingFuture[Any]:
        future_name = "_" + field_name
        future = self.__dict__.get(future_name)
        if future is None:
            future = self.__dict__[future_name] = pykka.ThreadingFuture()
        return future

    @staticmethod
    def _is_future_set(future: pykka.ThreadingFuture[Any] | None) -> bool:
        return is_future_set(future)

    @classmethod
    def _add_futures(cls, futures_list: list[Any], fields: list[str]) -> list[Any]:
        """Create missing future slots for each field on every object.

        An existing future that has not yet been populated is still considered
        pending, so async properties re-enter their loader instead of silently
        treating themselves as already resolved.
        """

        def add(obj: Any) -> bool:
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
    def title(self) -> None:
        self.load_info([self])

    @async_property
    def channel(self) -> None:
        self.load_info([self])

    @async_property
    def channelId(self) -> None:
        self.load_info([self])

    def _set_api_data(self, fields: list[str], item: dict[str, Any] | None) -> None:
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
                    context.playlist_max_videos,
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

            set_once(future, value)

    @classmethod
    def extend_fields(
        cls, item: dict[str, Any] | None, fields: list[str]
    ) -> tuple[dict[str, Any] | None, list[str]]:
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
                    "name": f"{item['snippet']['channelTitle']} (Channel)",
                    "uri": f"yt:channel:{item['snippet']['channelId']}",
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
    total_bytes: int = 0
    cached_file_uri: str | None = None
    _load_executor: ClassVar[ThreadPoolExecutor | None] = None
    _audio_executor: ClassVar[ThreadPoolExecutor | None] = None

    _audio_url: pykka.ThreadingFuture[str | None]
    _related_videos: pykka.ThreadingFuture[list[Video]]
    _thumbnails: pykka.ThreadingFuture[list[Image]]
    _album: pykka.ThreadingFuture[dict[str, Any]]
    _track_no: pykka.ThreadingFuture[int | None]
    _artists: pykka.ThreadingFuture[list[dict[str, Any]]]

    @classmethod
    def get_load_executor(cls) -> ThreadPoolExecutor:
        if cls._load_executor is None:
            cls._load_executor = ThreadPoolExecutor(
                max_workers=max(2, min(8, (os.cpu_count() or 1) + 2))
            )
        return cls._load_executor

    @classmethod
    def load_info(cls, entries: list[Video]) -> None:
        """
        loads title, length, channel of multiple videos using one API call for
        every 50 videos. API calls are split across a shared executor.
        """
        minimum_fields = ["title", "length", "channel"]
        videos = cls._add_futures(entries, minimum_fields)

        def job(sublist: list[Video]) -> None:
            try:
                data = context.api.list_videos([x.id for x in sublist])
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

        executor = cls.get_load_executor()
        executor.map(
            job,
            [videos[i : i + 50] for i in range(0, len(videos), 50)],
        )

    @async_property
    def related_videos(self) -> None:
        """
        loads title, thumbnails, channel (and, optionally, length) of videos
        that are related to a video.  Number of related videos returned is
        uncertain. Usually between 1 and 19.  Does not return related
        playlists.
        """

        requires_related_videos = self._add_futures([self], ["related_videos"])

        if requires_related_videos:
            data = context.api.list_related_videos(self.id)
            related_videos = []

            for item in data.get("items", []):
                if "snippet" not in item:
                    continue

                minimum_fields = ["title", "channel"]
                extended_item, extended_fields = self.extend_fields(
                    item, minimum_fields
                )
                if extended_item is None:
                    continue
                video = Video.get(extended_item["id"]["videoId"])
                video._set_api_data(extended_fields, extended_item)
                related_videos.append(video)

            # start loading video info in the background
            Video.load_info(related_videos)
            self._related_videos.set(related_videos)

    @async_property
    def length(self) -> None:
        self.load_info([self])

    @async_property
    def thumbnails(self) -> None:
        requires_thumbnail = self._add_futures([self], ["thumbnails"])

        if requires_thumbnail:
            self._thumbnails.set(
                [
                    Image(
                        uri=Uri(
                            f"https://i.ytimg.com/vi_webp/{self.id.split(':')[-1]}"
                            "/maxresdefault.webp"
                        )
                    )
                ]
            )

    @async_property
    def album(self) -> None:
        requires_album_name = self._add_futures([self], ["album"])

        if requires_album_name:
            self._album.set({"name": "YouTube Playlist", "uri": None})

    @async_property
    def track_no(self) -> None:
        requires_track_no = self._add_futures([self], ["track_no"])

        if requires_track_no:
            album = self.album.get()
            album_uri = album.get("uri") if isinstance(album, dict) else None
            playlist_id = extract_playlist_id(album_uri) if album_uri else ""

            if playlist_id:
                album_response = context.api.list_playlistitems(playlist_id, "", 50)
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
                            else (
                                track.get("id")
                                if isinstance(track.get("id"), str)
                                else None
                            )
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
                self._track_no.set(None)

    @async_property
    def artists(self) -> None:
        requires_artists = self._add_futures([self], ["artists"])

        if requires_artists:
            self._artists.set(
                [{"name": self.channel.get(), "uri": None, "thumbnail": None}]
            )

    @staticmethod
    def _extract_audio_url(info: Any) -> str | None:
        return extract_audio_url(info)

    @classmethod
    def get_audio_executor(cls) -> ThreadPoolExecutor:
        # separate from get_load_executor: long downloads must not starve API calls
        if cls._audio_executor is None:
            cls._audio_executor = ThreadPoolExecutor(max_workers=4)
        return cls._audio_executor

    @async_property
    def audio_url(self) -> None:
        Video.get_audio_executor().submit(self._load_audio_url)

    def _load_audio_url(self) -> None:
        """
        audio_url is the only property retrieved using yt-dlp, and it's much more
        expensive than the rest. If caching is turned on and the track is cached,
        return a (file) URL pointing to the cached file. If caching is turned on and
        the track isn't cached, start caching it and, once 2 percent has been
        cached, return an (http) URL pointing to the cached file. If caching is not
        turned on, return a URL obtained with yt-dlp.
        """

        # from @blacklight (https://github.com/blacklight/mopidy-youtube)
        try:
            ytdl_module = context.youtube_dl()
            logger.debug(f"using {context.youtube_dl_package} package for youtube_dl")

            # When caching, is it possible to set the audio_url part-way through
            # a download so audio can start playing quicker?

            def my_hook(d: dict[str, Any]) -> None:
                filename = Path(d["filename"])
                if d["status"] == "finished":
                    # caching is complete: later translate_uri calls get the file
                    # directly, no need to serve it up with tornado
                    file_uri = f"file://{d['filename']}"
                    self.cached_file_uri = file_uri

                    if not self.total_bytes:
                        logger.debug(
                            f"audio_url not set during downloading; setting audio_url now:"
                            f" {file_uri}, {filename.name}"
                        )
                        self.total_bytes = (
                            d.get("total_bytes") or d["info_dict"].get("filesize") or 0
                        )
                        set_once(self._audio_url, file_uri)

                if d["status"] == "downloading":
                    p = d["_percent_str"]
                    p = float(p.replace("%", ""))
                    logger.debug(f"percent cached: {p}%, {filename.name}")

                    # get 2% before setting audio_url; once self.total_bytes has a value,
                    # audio_url is set, so no need to do again; there seems to be problems
                    # with some formats that do not support seeking - limit to .webm
                    if p > 2 and not self.total_bytes and filename.suffix == ".webm":
                        http_uri = f"http://localhost:{context.http_port}/youtube/{filename.name}"
                        logger.debug(
                            f"setting cached audio_url: {http_uri}, {filename.name}"
                        )
                        self.total_bytes = (
                            d.get("total_bytes") or d["info_dict"].get("filesize") or 0
                        )
                        logger.debug(
                            f"expected length of {filename.name}: {self.total_bytes}"
                        )
                        set_once(self._audio_url, http_uri)

            ytdl_options: dict[str, Any] = {
                "format": "bestaudio/ogg/mp3/m4a/best",
                "proxy": context.proxy,
                "cachedir": False,
                "nopart": True,
                "retries": 10,
            }
            if context.musicapi_cookiefile:
                ytdl_options["cookiefile"] = context.musicapi_cookiefile
            base_url = "https://www.youtube.com"
            if context.musicapi_enabled:
                # High quality music streams are only available to YouTube
                # Premium users when using YouTube Music.
                base_url = "https://music.youtube.com"

            ytdl_extract_info_options: dict[str, Any] = {
                "url": f"{base_url}/watch?v={self.id}",
                "ie_key": None,
                "extra_info": {},
                "process": True,
                "force_generic_extractor": False,
            }

            if context.youtube_dl_package == "yt_dlp":
                ytdl_options["no_color"] = True

            if context.cache_location:
                resolved = resolve_audio_url(
                    self,
                    ytdl_options={**ytdl_options, "progress_hooks": [my_hook]},
                    ytdl_extract_info_options=ytdl_extract_info_options,
                    cache_location=context.cache_location,
                    youtube_dl=ytdl_module,
                    youtube_dl_package=context.youtube_dl_package,
                )
                set_once(self._audio_url, resolved)
                return

            with ytdl_module.YoutubeDL(ytdl_options) as ydl:
                info = ydl.extract_info(
                    **ytdl_extract_info_options,
                    download=False,
                )

            audio_url = self._extract_audio_url(info)
            if not audio_url:
                logger.warning(
                    "yt-dlp did not provide a direct audio URL for %s; info keys: %s",
                    self.id,
                    (
                        sorted(info.keys())
                        if isinstance(info, dict)
                        else type(info).__name__
                    ),
                )
                set_once(self._audio_url, None)
                return

            set_once(self._audio_url, audio_url)

        except Exception:
            logger.exception("audio_url error (videoId: %s)", self.id)
        finally:
            # no-op if already set; releases any waiter if nothing set the future
            set_once(self._audio_url, None)

    @property
    def is_video(self) -> bool:
        return True


class Playlist(Entry):
    _playlist_videos_executor: ClassVar[ThreadPoolExecutor | None] = None

    _videos: pykka.ThreadingFuture[list[Video]]

    @classmethod
    def get_playlist_videos_executor(cls) -> ThreadPoolExecutor:
        if cls._playlist_videos_executor is None:
            cls._playlist_videos_executor = ThreadPoolExecutor(max_workers=1)
        return cls._playlist_videos_executor

    @classmethod
    def load_info(cls, entries: list[Playlist]) -> None:
        """
        loads title, thumbnails, video_count, channel of multiple playlists using
        one API call for every 50 lists. API calls are split in separate threads.
        """
        minimum_fields = ["title", "video_count", "thumbnails", "channel"]
        playlists = cls._add_futures(entries, minimum_fields)

        def job(sublist: list[Playlist]) -> None:
            item_dict: dict[str, Any] = {}
            data = None

            try:
                data = context.api.list_playlists([x.id for x in sublist])
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

        executor = cls.get_playlist_videos_executor()
        executor.map(
            job,
            [playlists[i : i + 50] for i in range(0, len(playlists), 50)],
        )

    @async_property
    def videos(self) -> None:
        """
        loads the list of videos of a playlist using one API call for every 50
        fetched videos. For every page fetched, Video.load_info is called to
        start loading video info in a separate thread.
        """
        requires_videos = self._add_futures([self], ["videos"])

        def load_items() -> None:
            data: dict[str, Any] = {"items": []}
            page = ""
            while page is not None and len(data["items"]) < context.playlist_max_videos:
                try:
                    max_results = min(
                        context.playlist_max_videos - len(data["items"]), 50
                    )
                    result = context.api.list_playlistitems(self.id, page, max_results)
                except Exception as e:
                    logger.error('Playlist.videos list_playlistitems error "%s"', e)
                    break
                if "error" in result:
                    logger.error(
                        "error in list playlist items data for "
                        f"playlist {self.id}, page {page}",
                    )
                    break
                page = result.get("nextPageToken") or None

                # remove private and deleted videos from items
                filtered_result = [
                    item
                    for item in result["items"]
                    if item["snippet"]["title"]
                    not in ["Deleted video", "Private video"]
                ]

                data["items"].extend(filtered_result)

            del data["items"][context.playlist_max_videos :]

            playlist_videos = []
            for item in data["items"]:
                minimum_fields = ["title"]
                extended_item, extended_fields = self.extend_fields(
                    item, minimum_fields
                )
                if extended_item is None:
                    continue
                video_id = extended_item["snippet"]["resourceId"]["videoId"]
                if video_id is not None:
                    video = Video.get(video_id)
                    video._set_api_data(extended_fields, extended_item)
                    playlist_videos.append(video)

            videos = playlist_videos[: context.playlist_max_videos]

            # start loading video info in the background
            Video.load_info(videos)

            self._videos.set(videos)

        if requires_videos:
            self.get_playlist_videos_executor().submit(load_items)

    @async_property
    def video_count(self) -> None:
        self.load_info([self])

    @async_property
    def thumbnails(self) -> None:
        self.load_info([self])

    @property
    def is_video(self) -> bool:
        return False


class Channel(Entry):
    @classmethod
    def playlists(cls, channel_id: str | None = None) -> list[Playlist] | None:
        """
        Get all public playlists from the channel.
        """
        minimum_fields = ["title", "video_count"]
        if channel_id == "root":
            channel_id = context.channel
        if channel_id is None:
            return None
        try:
            data = context.api.list_channelplaylists(channel_id)
        except Exception as e:
            logger.error('Channel.playlists list_channelplaylists error "%s"', e)
            return None
        if "error" in data:
            logger.error(
                'Channel.playlists list_channelplaylists error "%s"', data["error"]
            )
            return None
        channel_playlists: list[Playlist] = []
        try:
            for item in data["items"]:
                pl = Playlist.get(item["id"])
                pl._set_api_data(minimum_fields, item)
                pl.videos  # noqa: B018 - starts the background load
                channel_playlists.append(pl)
        except Exception as e:
            logger.error('map error "%s"', e)
            return None
        return channel_playlists
