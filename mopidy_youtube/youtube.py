# -*- coding: utf-8 -*-

import re
import threading
import traceback

import cachetools

import pafy

import pykka

import requests

from mopidy_youtube import logger

# Wrapper for loading data of youtube videos/playlists via either the YouTube
# API or pafy. It offers the possibility to load info in the background (using
# threads), and use it later.
#
# eg
#   video = youtube.Video.get('7uj0hOIm2kY')
#   video.length   # non-blocking, returns future
#   ... later ...
#   print video.length.get()  # blocks until info arrives, if it hasn't already
#


class API:
    endpoint = 'https://www.googleapis.com/youtube/v3/'
    session = requests.Session()

    # overridable by config
    search_results = 15
    key = 'AIzaSyAl1Xq9DwdE_KD4AtPaE4EJl3WZe2zCqg4'

    # search for both videos and playlists using a single API call. fetches
    # only title, thumbnails, channel (extra queries are needed for length and
    # video_count)
    #
    @classmethod
    def search(cls, q):
        query = {
            'part': 'id,snippet',
            'fields': 'items(id,snippet(title,thumbnails,channelTitle))',
            'maxResults': cls.search_results,
            'type': 'video,playlist',
            'q': q,
            'key': API.key
        }
        result = API.session.get(API.endpoint+'search', params=query)
        data = result.json()

        def f(item):
            if item['id']['kind'] == 'youtube#video':
                obj = Video.get(item['id']['videoId'])
                obj._set_api_data(['title', 'channel'], item)
            else:
                obj = Playlist.get(item['id']['playlistId'])
                obj._set_api_data(['title', 'channel', 'thumbnails'], item)
            return obj

        return map(f, data['items'])


# decorator for creating async properties using pykka.ThreadingFuture
# the method of property foo should create future _foo
# on first call we invoke the method, then we just return the future
#
def async_property(f):
    _name = '_' + f.__name__

    def inner(self):
        if _name not in self.__dict__:
            apply(f, (self,))   # should create the future
        return self.__dict__[_name]

    return property(inner)


# video or playlist
class Entry(object):
    cache_max_len = 400

    # Use Video.get(id), Playlist.get(id), instead of Video(id), Playlist(id),
    # to fetch a cached object, if available
    #
    @classmethod
    @cachetools.lru_cache(maxsize=cache_max_len)
    def get(cls, id):
        obj = cls()
        obj.id = id
        return obj

    @async_property
    def title(self):
        self.load_info([self])

    @async_property
    def channel(self):
        self.load_info([self])

    def _set_api_data(self, fields, item):
        for k in fields:
            _k = '_' + k
            future = self.__dict__.get(_k)
            if not future:
                future = self.__dict__[_k] = pykka.ThreadingFuture()

            if not future._queue.empty():  # hack, no public is_set()
                continue

            if not item:
                val = None
            elif k == 'title':
                val = item['snippet']['title']
            elif k == 'channel':
                val = item['snippet']['channelTitle']
            elif k == 'length':
                # convert PT1H2M10S to 3730
                m = re.search('PT((?P<hours>\d+)H)?' +
                              '((?P<minutes>\d+)M)?' +
                              '((?P<seconds>\d+)S)?',
                              item['contentDetails']['duration'])
                val = (int(m.group('hours') or 0) * 3600 +
                       int(m.group('minutes') or 0) * 60 +
                       int(m.group('seconds') or 0))
            elif k == 'video_count':
                val = min(item['contentDetails']['itemCount'], self.max_videos)
            elif k == 'thumbnails':
                val = [
                    val['url']
                    for (key, val) in item['snippet']['thumbnails'].items()
                    if key in ['medium', 'high']
                ]

            future.set(val)


class Video(Entry):

    # loads title, length, channel of multiple videos using one API call for
    # every 50 videos. API calls are split in separate threads.
    #
    @classmethod
    def load_info(cls, list):
        # determine which fields we need to load and add futures for these
        # fields. if a video has all fields loaded then no need to process it
        # then no need to process it
        fields = {}

        def add_futures(vid):
            added = False
            for k in ['title', 'length', 'channel']:
                _k = '_' + k
                if _k not in vid.__dict__:
                    vid.__dict__[_k] = pykka.ThreadingFuture()
                    fields[k] = added = True
            return added

        list = [x for x in list if add_futures(x)]
        if not list:
            return

        # load snippet/contentDetails only if needed
        qpart = qfields = 'id'
        if 'title' in fields or 'channel' in fields:
            qpart += ',snippet'
            qfields += ',snippet(title,channelTitle)'
        if 'length' in fields:
            qpart += ',contentDetails'
            qfields += ',contentDetails(duration)'

        def job(sublist):
            query = {
                'part': qpart,
                'fields': 'items(%s)' % qfields,
                'id': ','.join([x.id for x in sublist]),
                'key': API.key
            }
            try:
                result = API.session.get(API.endpoint+'videos', params=query)
                data = result.json()
                dict = {item['id']: item for item in data['items']}
            except:
                dict = {}

            for video in sublist:
                video._set_api_data(fields.keys(), dict.get(video.id))

        # 50 items at a time, make sure order is deterministic so that HTTP
        # requests are replayable in tests
        for i in range(0, len(list), 50):
            sublist = list[i:i+50]
            ThreadPool.run(job, (sublist,))

    @async_property
    def title(self):
        self.load_info([self])

    @async_property
    def length(self):
        self.load_info([self])

    @async_property
    def pafy(self):
        self._pafy = pykka.ThreadingFuture()

        def job():
            try:
                self._pafy.set(pafy.new(self.id))
            except:
                logger.error('youtube: video "%s" deleted/restricted', self.id)
                self._pafy.set(None)
        ThreadPool.run(job)

    @async_property
    def thumbnails(self):
        # make it "async" for uniformity with Playlist.thumbnails
        self._thumbnails = pykka.ThreadingFuture()
        self._thumbnails.set([
            'https://i.ytimg.com/vi/%s/%s.jpg' % (self.id, type)
            for type in ['mqdefault', 'hqdefault']
        ])

    @property
    def audio_url(self):
        # get aac stream (.m4a) cause gstreamer 0.10 has issues with ogg
        # containing opus format!
        #  test id: cF9z1b5HL7M, playback gives error:
        #   Could not find a audio/x-unknown decoder to handle media. You might
        #   be able to fix this by running: gst-installer
        #   "gstreamer|0.10|mopidy|audio/x-unknown
        #   decoder|decoder-audio/x-unknown, codec-id=(string)A_OPUS"
        #
        uri = self.pafy.get().getbestaudio('m4a', True)
        if not uri:  # get video url
            uri = self.pafy.get().getbest('m4a', True)
        return uri.url

    @property
    def is_video(self):
        return True


class Playlist(Entry):
    # overridable by config
    max_videos = 60     # max number of videos per playlist

    # loads title, thumbnails, video_count, channel of multiple playlists using
    # one API call for every 50 lists. API calls are split in separate threads.
    #
    @classmethod
    def load_info(cls, list):
        # determine which fields we need to load and add futures for these
        # fields. if a video has all fields loaded then no need to process it
        # then no need to process it
        fields = {}

        def add_futures(vid):
            added = False
            for k in ['title', 'video_count', 'thumbnails', 'channel']:
                _k = '_' + k
                if _k not in vid.__dict__:
                    vid.__dict__[_k] = pykka.ThreadingFuture()
                    fields[k] = added = True
            return added

        list = [x for x in list if add_futures(x)]
        if not list:
            return

        # load snippet/contentDetails only if needed
        qpart = qfields = 'id'
        if [1 for k in ['title', 'thumbnails', 'channel'] if k in fields]:
            qpart += ',snippet'
            qfields += ',snippet(title,thumbnails,channelTitle)'
        if 'video_count' in fields:
            qpart += ',contentDetails'
            qfields += ',contentDetails(itemCount)'

        def job(sublist):
            query = {
                'part': qpart,
                'fields': 'items(%s)' % qfields,
                'id': ','.join([x.id for x in sublist]),
                'key': API.key
            }
            try:
                result = API.session.get(API.endpoint+'playlists',
                                         params=query)
                data = result.json()
                dict = {item['id']: item for item in data['items']}
            except:
                dict = {}

            for pl in sublist:
                pl._set_api_data(fields.keys(), dict.get(pl.id))

        # 50 items at a time, make sure order is deterministic so that HTTP
        # requests are replayable in tests
        for i in range(0, len(list), 50):
            sublist = list[i:i+50]
            ThreadPool.run(job, (sublist,))

    # loads list of videos of a playlist using one API call for every 50
    # fetched videos. For every page fetched, Video.load_info_mult is called to
    # start loading video info in a separate thread.
    #
    @async_property
    def videos(self):
        self._videos = pykka.ThreadingFuture()

        def job():
            all_videos = []
            page = ''
            while page is not None and len(all_videos) < self.max_videos:
                query = {
                    'part': 'id,snippet',
                    'fields': 'nextPageToken,' +
                              'items(snippet(title,resourceId(videoId)))',
                    'maxResults': min(self.max_videos - len(all_videos), 50),
                    'playlistId': self.id,
                    'key': API.key,
                    'pageToken': page,
                }
                try:
                    result = API.session.get(API.endpoint+'playlistItems',
                                             params=query)
                    data = result.json()
                except:
                    break
                page = data.get('nextPageToken') or None

                myvideos = []
                for item in data['items']:
                    video = Video.get(item['snippet']['resourceId']['videoId'])
                    video._set_api_data(['title'], item)
                    myvideos.append(video)
                all_videos += myvideos

                # start loading video info for this batch in the background
                Video.load_info(myvideos)

            self._videos.set(all_videos)

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


# simple 'dynamic' thread pool. Threads are created when new jobs arrive, stay
# active for as long as there are active jobs, and get destroyed afterwards
# (so that there are no long-term threads staying active)
#
class ThreadPool:
    threads_max = 15
    threads_active = 0
    jobs = []
    lock = threading.Lock()     # controls access to threads_active and jobs

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
                apply(f, args)
            except Exception as e:
                logger.error('youtube thread error: %s\n%s',
                             e, traceback.format_exc())

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
