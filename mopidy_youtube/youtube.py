import importlib
import json
import os
import re
import shutil
from concurrent.futures.thread import ThreadPoolExecutor

import pykka

from cachetools import TTLCache, cached
from mopidy.models import Image, ModelJSONEncoder

from mopidy_youtube import logger
from mopidy_youtube.converters import convert_video_to_track

api_enabled = False
channel = None
cache_location = None
youtube_dl = None
youtube_dl_package = "youtube_dl"


def async_property(func):
    """
    decorator for creating async properties using pykka.ThreadingFuture

    A property 'foo' should have a future '_foo'
    On first call we invoke func() which should create the future
    On subsequent calls we just return the future
    """

    _future_name = "_" + func.__name__

    def wrapper(self):
        if _future_name not in self.__dict__:
            func(self)  # should create the future
        return self.__dict__[_future_name]

    return property(wrapper)


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

    def create_object(item):
        set_api_data = ["title", "channel"]
        if item["id"]["kind"] == "youtube#video":
            obj = Video.get(item["id"]["videoId"])
        elif item["id"]["kind"] == "youtube#playlist":
            obj = Playlist.get(item["id"]["playlistId"])
        else:
            obj = []
            return obj

        if "contentDetails" in item:
            if "duration" in item["contentDetails"]:
                set_api_data.append("length")
            elif "itemCount" in item["contentDetails"]:
                set_api_data.append("video_count")

        if "thumbnails" in item["snippet"]:
            set_api_data.append("thumbnails")
        if "album" in item:
            set_api_data.append("album")
        if "artists" in item:
            set_api_data.append("artists")
        if "channelId" in item["snippet"]:
            set_api_data.append("channelId")
        obj._set_api_data(set_api_data, item)
        return obj

    @classmethod
    def search(cls, q):
        """
        Search for both videos and playlists using a single API call. Fetches
        title, thumbnails, channel. Depending on the API, may also fetch
        length and video_count. The official youtube API will require an
        additional API call to fetch length and video_count (taken care of
        at Video.load_info and Playlist.load_info).
        """
        try:
            data = cls.api.search(q)
            if "error" in data:
                raise Exception(data["error"])
        except Exception as e:
            logger.error('youtube search error "%s"', e)
            return None
        try:
            return list(map(cls.create_object, data["items"]))
        except Exception as e:
            logger.error('map error "%s"', e)
            return None

    @classmethod
    def _add_futures(cls, futures_list, fields):
        """
        Adds futures for the given fields to all objects in list, unless they
        already exist. Returns objects for which at least one future was added
        """

        def add(obj):
            added = False
            for k in fields:
                if "_" + k not in obj.__dict__:
                    obj.__dict__["_" + k] = pykka.ThreadingFuture()
                    added = True
            return added

        return list(filter(add, futures_list))

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
        """
        sets the given 'fields' of 'self', based on the 'item'
        data retrieved through the API
        """

        for k in fields:
            _k = "_" + k
            future = self.__dict__.get(_k)
            if not future:
                future = self.__dict__[_k] = pykka.ThreadingFuture()

            if not future._queue.empty():  # hack, no public is_set()
                continue

            if not item:
                val = None
            elif k == "title":
                val = item["snippet"]["title"]
            elif k == "channel":
                val = item["snippet"]["channelTitle"]
            elif k == "owner_channel":
                val = item["snippet"]["videoOwnerChannelTitle"]
            elif k == "album":
                val = item["album"]
            elif k == "artists":
                val = item["artists"]
            elif k == "length":
                # convert PT1H2M10S to 3730
                m = re.search(
                    r"P((?P<weeks>\d+)W)?"
                    + r"((?P<days>\d+)D)?"
                    + r"T((?P<hours>\d+)H)?"
                    + r"((?P<minutes>\d+)M)?"
                    + r"((?P<seconds>\d+)S)?",
                    item["contentDetails"]["duration"],
                )
                if m:
                    val = (
                        int(m.group("weeks") or 0) * 604800
                        + int(m.group("days") or 0) * 86400
                        + int(m.group("hours") or 0) * 3600
                        + int(m.group("minutes") or 0) * 60
                        + int(m.group("seconds") or 0)
                    )
                else:
                    val = 0
            elif k == "video_count":
                val = min(
                    int(item["contentDetails"]["itemCount"]),
                    int(self.playlist_max_videos),
                )
            elif k == "thumbnails":
                val = [
                    Image(uri=val["url"], width=val["width"], height=val["height"])
                    for (key, val) in item["snippet"]["thumbnails"].items()
                    if key in ["default", "medium", "high"]
                ] or None  # is this "or None" necessary?
            elif k == "channelId":
                val = item["snippet"]["channelId"]
            future.set(val)


class Video(Entry):

    total_bytes = 0

    @classmethod
    def load_info(cls, listOfVideos):
        """
        loads title, length, channel of multiple videos using one API call for
        every 50 videos. API calls are split in separate threads.
        """
        fields = ["title", "length", "channel"]
        listOfVideos = cls._add_futures(listOfVideos, fields)

        def job(sublist):
            try:
                data = cls.api.list_videos([x.id for x in sublist])
                dict = {item["id"]: item for item in data["items"]}
            except Exception as e:
                logger.error('list_videos error "%s"', e)
                dict = {}

            for video in sublist:
                video._set_api_data(fields, dict.get(video.id))

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
            relatedvideos = []
            data = self.api.list_related_videos(self.id)

            for item in data["items"]:
                # why are some results returned without a 'snippet'?
                if "snippet" in item:
                    set_api_data = ["title", "channel"]
                    if "contentDetails" in item:
                        set_api_data.append("length")
                    if "thumbnails" in item["snippet"]:
                        set_api_data.append("thumbnails")
                    video = Video.get(item["id"]["videoId"])
                    video._set_api_data(set_api_data, item)
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
                        uri=f"https://i.ytimg.com/vi/{self.id.split(':')[-1]}/default.jpg"
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
    def artists(self):
        # make it "async" for uniformity with Playlist.thumbnails
        requiresArtists = self._add_futures([self], ["artists"])

        if requiresArtists:
            # ultimate fallback
            self._artists.set(
                [{"name": self.channel.get(), "uri": None, "thumbnail": None}]
            )

    @async_property
    def audio_url(self):
        """
        audio_url is the only property retrived using youtube_dl, it's much more
        expensive than the rest. If caching is turned on and the track is cached,
        return a (file) url pointing to the cached file. If caching is turned on, and
        the track isn't cached, start caching it, and - once 2 percent has been
        cached - return a (http) url pointing to the cached file. If caching is not
        turned on, return a url obtained with youtube_dl.
        """

        global youtube_dl
        if youtube_dl is None:
            logger.debug(f"using {youtube_dl_package} package for youtube_dl")
            youtube_dl = importlib.import_module(youtube_dl_package)

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
                self.total_bytes = d["total_bytes"]
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
                    self.total_bytes = d["total_bytes"]
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
                }

                ytdl_extract_info_options = {
                    "url": f"https://www.youtube.com/watch?v={self.id}",
                    "ie_key": None,
                    "extra_info": {},
                    "process": True,
                    "force_generic_extractor": False,
                }

                if cache_location:
                    cached = [
                        cached_file
                        for cached_file in os.listdir(cache_location)
                        if cached_file
                        in [
                            f"{self.id}.{format}"
                            for format in ["webm", "m4a", "mp3", "ogg"]
                        ]
                    ]
                    if cached:
                        fileUri = f"file://{(os.path.join(cache_location, cached[0]))}"
                        self._audio_url.set(fileUri)
                        return
                    else:

                        logger.debug(f"caching metadata {self.id}")
                        with open(
                            os.path.join(cache_location, f"{self.id}.json"), "w"
                        ) as outfile:
                            json.dump(
                                convert_video_to_track(self),
                                cls=ModelJSONEncoder,
                                fp=outfile,
                            )

                        logger.debug(f"caching image {self.id}")
                        imageFile = f"{self.id}.jpg"
                        if imageFile not in os.listdir(cache_location):
                            imageUri = self.thumbnails.get()[0].uri
                            response = self.api.session.get(imageUri, stream=True)
                            if response.status_code == 200:
                                logger.debug(f"caching image {self.id}")
                                with open(
                                    os.path.join(cache_location, imageFile), "wb",
                                ) as out_file:
                                    shutil.copyfileobj(response.raw, out_file)
                            del response

                        logger.debug(f"caching track {self.id}")
                        ytdl_options["outtmpl"] = os.path.join(
                            cache_location, "%(id)s.%(ext)s"
                        )

                        ytdl_options["progress_hooks"] = [my_hook]

                        with youtube_dl.YoutubeDL(ytdl_options) as ydl:
                            info = ydl.extract_info(
                                **ytdl_extract_info_options, download=True,
                            )

                        # # this is now done by the progress_hooks
                        # fileUri = f"file://{ydl.prepare_filename(info)}"
                        # self._audio_url.set(fileUri)

                else:
                    with youtube_dl.YoutubeDL(ytdl_options) as ydl:
                        info = ydl.extract_info(
                            **ytdl_extract_info_options, download=False,
                        )

                        self._audio_url.set(info["url"])

            except Exception as e:
                logger.error(f"audio_url error {e} (videoId: {self.id})")
                self._audio_url.set(None)
                return

    @property
    def is_video(self):
        return True


class Playlist(Entry):
    @classmethod
    def load_info(cls, listOfPlaylists):
        """
        loads title, thumbnails, video_count, channel of multiple playlists using
        one API call for every 50 lists. API calls are split in separate threads.
        """
        fields = ["title", "video_count", "thumbnails", "channel"]
        listOfPlaylists = cls._add_futures(listOfPlaylists, fields)

        def job(sublist):
            dict = {}

            try:
                data = cls.api.list_playlists([x.id for x in sublist])
            except Exception as e:
                logger.error(
                    f"Playlist.load_info list_playlists error {e}, {[x.id for x in sublist]}"
                )

            if data:
                dict = {item["id"]: item for item in data["items"]}

            for pl in sublist:
                pl._set_api_data(fields, dict.get(pl.id))

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
                if "videoOwnerChannelTitle" in item["snippet"]:
                    set_api_data = ["title", "owner_channel"]
                elif "channelTitle" in item["snippet"]:
                    set_api_data = ["title", "channel"]
                else:
                    logger.warn(f"no channel or owner_channel; skipping {item}")
                    continue
                if "contentDetails" in item:
                    set_api_data.append("length")
                if "thumbnails" in item["snippet"]:
                    set_api_data.append("thumbnails")
                if item["snippet"]["resourceId"]["videoId"] is not None:
                    video = Video.get(item["snippet"]["resourceId"]["videoId"])
                    video._set_api_data(set_api_data, item)
                    myvideos.append(video)

            # start loading video info in the background
            Video.load_info(
                [x for _, x in zip(range(self.playlist_max_videos), myvideos)]
            )

            self._videos.set(
                [x for _, x in zip(range(self.playlist_max_videos), myvideos)]
            )

        if requiresVideos:
            executor = ThreadPoolExecutor(max_workers=1)
            executor.submit(load_items)
            executor.shutdown(wait=False)
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
        set_api_data = ["title", "video_count"]
        try:
            if channel_id == "root":
                channel_id = channel
            data = cls.api.list_channelplaylists(channel_id)
            if "error" in data:
                raise Exception(data["error"])
        except Exception as e:
            logger.error('Channel.playlists list_channelplaylists error "%s"', e)
            return None
        try:
            channel_playlists = []
            for item in data["items"]:
                pl = Playlist.get(item["id"])
                pl._set_api_data(set_api_data, item)
                channel_playlists.append(pl)
            Playlist.load_info(channel_playlists)
            return channel_playlists
        except Exception as e:
            logger.error('map error "%s"', e)
            return None
