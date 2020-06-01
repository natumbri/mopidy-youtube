import re
import threading
import traceback

import pykka
import requests
import youtube_dl
from cachetools import LRUCache, cached
from mopidy.models import Image
from mopidy_youtube import logger
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
from urllib3.util import Timeout

api_enabled = False


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

    cache_max_len = 400

    @classmethod
    @cached(cache=LRUCache(maxsize=cache_max_len))
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
            if "contentDetails" in item:
                set_api_data.append("length")
        elif item["id"]["kind"] == "youtube#playlist":
            obj = Playlist.get(item["id"]["playlistId"])
            if "contentDetails" in item:
                set_api_data.append("video_count")
        else:
            obj = []
            return obj
        if "thumbnails" in item["snippet"]:
            set_api_data.append("thumbnails")
        obj._set_api_data(set_api_data, item)
        return obj


    @classmethod
    def search(cls, q):
        """
        Search for both videos and playlists using a single API call. Fetches
        only title, thumbnails, channel (extra queries are needed for length and
        video_count)
        """
        try:
            data = cls.api.search(q)
            if "error" in data:
                raise Exception(data["error"])
        except Exception as e:
            logger.error('search error "%s"', e)
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
                    val["url"]
                    for (key, val) in item["snippet"]["thumbnails"].items()
                    if key in ["default", "medium", "high"]
                ]

            future.set(val)


class Video(Entry):
    @classmethod
    def load_info(cls, list):
        """
        loads title, length, channel of multiple videos using one API call for
        every 50 videos. API calls are split in separate threads.
        """

        fields = ["title", "length", "channel"]
        list = cls._add_futures(list, fields)

        def job(sublist):
            try:
                data = cls.api.list_videos([x.id for x in sublist])
                dict = {item["id"]: item for item in data["items"]}
            except Exception as e:
                logger.error('list_videos error "%s"', e)
                dict = {}

            for video in sublist:
                video._set_api_data(fields, dict.get(video.id))

        # 50 items at a time, make sure order is deterministic so that HTTP
        # requests are replayable in tests
        for i in range(0, len(list), 50):
            sublist = list[i : i + 50]
            ThreadPool.run(job, (sublist,))

    @classmethod
    def related_videos(cls, video_id):
        data = cls.api.list_related_videos(video_id)
        return list(map(cls.create_object, data["items"]))

    @async_property
    def length(self):
        self.load_info([self])

    @async_property
    def thumbnails(self):
        # make it "async" for uniformity with Playlist.thumbnails
        identifier = self.id.split(".")[-1]
        self._thumbnails = pykka.ThreadingFuture()
        self._thumbnails.set(
            [
                Image(uri=f"https://i.ytimg.com/vi/{identifier}/{type}.jpg")
                for type in ["default", "mqdefault", "hqdefault"]
            ]
        )

    @async_property
    def audio_url(self):
        """
        audio_url is the only property retrived using youtube_dl, it's much more
        expensive than the rest
        """

        self._audio_url = pykka.ThreadingFuture()

        def job():
            try:
                info = youtube_dl.YoutubeDL(
                    {
                        "format": "bestaudio/best",
                        "proxy": self.proxy,
                        "nocheckcertificate": True,
                        "cachedir": False,
                    }
                ).extract_info(
                    url="https://www.youtube.com/watch?v=%s" % self.id,
                    download=False,
                    ie_key=None,
                    extra_info={},
                    process=True,
                    force_generic_extractor=False,
                )
            except Exception as e:
                logger.error('audio_url error "%s"', e)
                self._audio_url.set(None)
                return
            self._audio_url.set(info["url"])

        ThreadPool.run(job)

    @property
    def is_video(self):
        return True


class Playlist(Entry):
    @classmethod
    def load_info(cls, list):
        """
        loads title, thumbnails, video_count, channel of multiple playlists using
        one API call for every 50 lists. API calls are split in separate threads.
        """

        fields = ["title", "video_count", "thumbnails", "channel"]
        list = cls._add_futures(list, fields)

        def job(sublist):
            try:
                data = cls.api.list_playlists([x.id for x in sublist])
                dict = {item["id"]: item for item in data["items"]}
            except Exception as e:
                logger.error('list_playlists error "%s"', e)
                dict = {}

            for pl in sublist:
                pl._set_api_data(fields, dict.get(pl.id))

        # 50 items at a time, make sure order is deterministic so that HTTP
        # requests are replayable in tests
        for i in range(0, len(list), 50):
            sublist = list[i : i + 50]
            ThreadPool.run(job, (sublist,))

    @async_property
    def videos(self):
        """
        loads the list of videos of a playlist using one API call for every 50
        fetched videos. For every page fetched, Video.load_info is called to
        start loading video info in a separate thread.
        """

        self._videos = pykka.ThreadingFuture()

        def job():
            data = {"items": []}
            page = ""
            while (
                page is not None
                and len(data["items"]) < self.playlist_max_videos
            ):
                try:
                    max_results = min(
                        int(self.playlist_max_videos) - len(data["items"]), 50
                    )
                    result = self.api.list_playlistitems(
                        self.id, page, max_results
                    )
                except Exception as e:
                    logger.error('list playlist items error "%s"', e)
                    break
                if "error" in result:
                    logger.error(
                        "error in list playlist items data for",
                        "playlist {}, page {}".format(self.id, page),
                    )
                    break
                page = result.get("nextPageToken") or None
                data["items"].extend(result["items"])

            del data["items"][int(self.playlist_max_videos) :]

            myvideos = []

            for item in data["items"]:
                set_api_data = ["title", "channel"]
                if "contentDetails" in item:
                    set_api_data.append("length")
                if "thumbnails" in item["snippet"]:
                    set_api_data.append("thumbnails")
                video = Video.get(item["snippet"]["resourceId"]["videoId"])
                video._set_api_data(set_api_data, item)
                myvideos.append(video)

            # start loading video info in the background
            Video.load_info(
                [x for _, x in zip(range(self.playlist_max_videos), myvideos)]
            )  # noqa: E501

            self._videos.set(
                [x for _, x in zip(range(self.playlist_max_videos), myvideos)]
            )  # noqa: E501

        ThreadPool.run(job)

    @async_property
    def video_count(self):
        self.load_info([self])

    @async_property
    def thumbnails(self):
        self.load_info([self])

    @property
    def is_video(self):
        return False


class MyHTTPAdapter(HTTPAdapter):
    def get(self, *args, **kwargs):
        kwargs["timeout"] = (6.05, 27)
        return super(MyHTTPAdapter, self).get(*args, **kwargs)

    def init_poolmanager(self, *args, **kwargs):
        kwargs["timeout"] = Timeout(connect=6.05, read=27.0)
        return super(MyHTTPAdapter, self).init_poolmanager(*args, **kwargs)


class Client:
    def __init__(self, proxy, headers):
        if not hasattr(type(self), "session"):
            self._create_session(proxy, headers)

    @classmethod
    def _create_session(
        cls,
        proxy,
        headers,
        retries=3,
        backoff_factor=0.3,
        status_forcelist=(500, 502, 504),
        session=None,
    ):
        cls.session = session or requests.Session()
        retry = Retry(
            total=retries,
            read=retries,
            connect=retries,
            backoff_factor=backoff_factor,
            status_forcelist=status_forcelist,
        )
        adapter = MyHTTPAdapter(
            max_retries=retry, pool_maxsize=ThreadPool.threads_max
        )
        cls.session.mount("http://", adapter)
        cls.session.mount("https://", adapter)
        cls.session.proxies = {"http": proxy, "https": proxy}
        cls.session.headers = headers

    @classmethod
    def format_duration(cls, match):
        duration = ""
        if match.group("durationHours") is not None:
            duration += match.group("durationHours") + "H"
        if match.group("durationMinutes") is not None:
            duration += match.group("durationMinutes") + "M"
        if match.group("durationSeconds") is not None:
            duration += match.group("durationSeconds") + "S"
        return duration


class ThreadPool:
    """
    simple 'dynamic' thread pool. Threads are created when new jobs arrive, stay
    active for as long as there are active jobs, and get destroyed afterwards
    (so that there are no long-term threads staying active)
    """

    threads_active = 0
    jobs = []
    lock = threading.Lock()  # controls access to threads_active and jobs

    @classmethod
    def worker(cls):
        while True:
            cls.lock.acquire()
            if len(cls.jobs):
                f, args = cls.jobs.pop()
            else:
                # no more jobs, exit thread
                cls.threads_active -= 1
                cls.lock.release()
                break
            cls.lock.release()

            try:
                f(*args)
            except Exception as e:
                logger.error(
                    "youtube thread error: %s\n%s", e, traceback.format_exc()
                )

    @classmethod
    def run(cls, f, args=()):
        cls.lock.acquire()

        cls.jobs.append((f, args))
        if cls.threads_active < cls.threads_max:
            thread = threading.Thread(target=cls.worker)
            thread.daemon = True
            thread.start()
            cls.threads_active += 1

        cls.lock.release()
