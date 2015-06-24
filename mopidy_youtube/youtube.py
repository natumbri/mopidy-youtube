# -*- coding: utf-8 -*-

import re
import threading
import traceback

import cachetools

import pafy

import requests

from mopidy_youtube import logger

# Wrapper for loading data of youtube videos/playlists via either the Youtube
# API or pafy. It offers the possibility to load info in the background (using
# threads), and use it later.
#
# eg
#   video = youtube.Video.get('7uj0hOIm2kY')
#   video.load_info()   # non-blocking
#   ... later ...
#   print video.length  # blocks until info arrives, if it hasn't already
#

yt_api_endpoint = 'https://www.googleapis.com/youtube/v3/'
yt_key = 'AIzaSyAl1Xq9DwdE_KD4AtPaE4EJl3WZe2zCqg4'
session = requests.Session()


class API:
    search_results = 15

    # search for both videos and playlists using a single API call. fetches
    # only title, thumbnails, channel (extra queries are needed for length and
    # video_count)
    #
    @classmethod
    def search(self, q):
        query = {
            'part': 'id,snippet',
            'fields': 'items(id,snippet(title,thumbnails,channelTitle))',
            'maxResults': self.search_results,
            'type': 'video,playlist',
            'q': q,
            'key': yt_key
        }
        result = session.get(yt_api_endpoint+'search', params=query)
        data = result.json()

        def f(item):
            if item['id']['kind'] == 'youtube#video':
                obj = Video.get(item['id']['videoId'])
            else:
                obj = Playlist.get(item['id']['playlistId'])

            obj._load_api_data(item)
            return obj

        return map(f, data['items'])


# video or playlist
class Entry(object):
    cache_max_len = 400

    # Use Video.get(id), Playlist.get(id), instead of Video(id), Playlist(id),
    # to fetch a cached object, if available
    #
    @classmethod
    @cachetools.lru_cache(maxsize=cache_max_len)
    def get(self, id):
        return self(id)

    @classmethod
    def make_async_prop(self, prop, method):
        _prop = '_' + prop

        def f(self):
            # if property is not set, call the method and wait on the event
            if self.__dict__[_prop] is None:
                event = getattr(self, method)()
                if event:
                    event.wait()
            return self.__dict__[_prop]

        setattr(self, prop, property(f))

    def __init__(self, id):
        self.id = id
        self._title = None
        self._channel = None
        self._info_event = None

    def _load_api_data(self, item):
        snip = item.get('snippet')
        if not snip:
            return

        if self._title is None:
            self._title = snip.get('title')
        if self._channel is None:
            self._channel = snip.get('channelTitle')


class Video(Entry):

    # loads title, length, channel of multiple videos using one API call for
    # every 50 videos. API calls are split in separate threads.
    #
    @classmethod
    def load_info_mult(self, list):
        list = [x for x in list
                if None in [x._title, x._length, x._channel]
                and x._info_event is None]
        if not list:
            return

        # load snippet/contentDetails only if needed
        part = fields = 'id'
        if [1 for v in list if None in [v._title, v._channel]]:
            part += ',snippet'
            fields += ',snippet(title,channelTitle)'
        if [1 for v in list if v._length is None]:
            part += ',contentDetails'
            fields += ',contentDetails(duration)'

        def job(sublist):
            query = {
                'part': part,
                'fields': 'items(%s)' % fields,
                'id': ','.join([x.id for x in sublist]),
                'key': yt_key
            }
            result = session.get(yt_api_endpoint+'videos', params=query)
            data = result.json()

            dict = {x.id: x for x in sublist}

            for item in data['items']:
                dict[item['id']]._load_api_data(item)

        # 50 items at a time, make sure order is deterministic so that HTTP
        # requests are replayable in tests
        for i in range(0, len(list), 50):
            sublist = list[i:i+50]
            event = ThreadPool.run(job, (sublist,))
            for x in sublist:
                x._info_event = event

    # converts PT1H2M10S to 3730
    @classmethod
    def dur_to_secs(self, dur):
        if not dur:
            return None
        m = re.search('PT((?P<hours>\d+)H)?' +
                      '((?P<minutes>\d+)M)?' +
                      '((?P<seconds>\d+)S)?',
                      dur)
        return(int(m.group('hours') or 0) * 3600 +
               int(m.group('minutes') or 0) * 60 +
               int(m.group('seconds') or 0))

    def __init__(self, id):
        super(Video, self).__init__(id)

        self._pafy = None
        self._length = None
        self._pafy_event = None

    def _load_api_data(self, item):
        super(Video, self)._load_api_data(item)

        det = item.get('contentDetails')
        if det and self._length is None:
            self._length = self.dur_to_secs(det.get('duration'))

    def load_info(self):
        self.load_info_mult([self])
        return self._info_event

    # loads pafy object in a separate thread
    #
    def load_pafy(self):
        if self._pafy is not None or self._pafy_event:
            return self._pafy_event

        def job():
            try:
                self._pafy = pafy.new(self.id)
            except:
                logger.error('youtube: video "%s" deleted/restricted', self.id)

        self._pafy_event = ThreadPool.run(job)
        return self._pafy_event

    @property
    def thumbnails(self):
        return [
            'https://i.ytimg.com/vi/%s/%s.jpg' % (self.id, type)
            for type in ['mqdefault', 'hqdefault']
        ]

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
        uri = self.pafy.getbestaudio('m4a', True)
        if not uri:  # get video url
            uri = self.pafy.getbest('m4a', True)
        return uri.url

    @property
    def is_video(self):
        return True


class Playlist(Entry):
    max_videos = 60     # max number of videos per playlist

    # loads title, thumbnails, video_count, channel of multiple playlists using
    # one API call for every 50 lists. API calls are split in separate threads.
    #
    @classmethod
    def load_info_mult(self, list):
        list = [
            x for x in list
            if None in [x._title, x._video_count, x._thumbnails, x._channel]
            and x._info_event is None
        ]
        if not list:
            return

        # load snippet/contentDetails only if needed
        part = fields = 'id'
        if [1 for v in list if None in [v._title, v._thumbnails, v._channel]]:
            part += ',snippet'
            fields += ',snippet(title,thumbnails,channelTitle)'
        if [1 for v in list if v._video_count is None]:
            part += ',contentDetails'
            fields += ',contentDetails(itemCount)'

        def job(sublist):
            query = {
                'part': part,
                'fields': 'items(%s)' % fields,
                'id': ','.join([x.id for x in sublist]),
                'key': yt_key
            }
            result = session.get(yt_api_endpoint+'playlists', params=query)
            data = result.json()

            dict = {x.id: x for x in sublist}

            for item in data['items']:
                dict[item['id']]._load_api_data(item)

        # 50 items at a time, make sure order is deterministic so that HTTP
        # requests are replayable in tests
        for i in range(0, len(list), 50):
            sublist = list[i:i+50]
            event = ThreadPool.run(job, (sublist,))
            for x in list:
                x._info_event = event

    def _load_api_data(self, item):
        super(Playlist, self)._load_api_data(item)

        snip, det = item.get('snippet'), item.get('contentDetails')

        if det and self._video_count is None:
            self._video_count = min(det['itemCount'], self.max_videos)

        if snip and 'thumbnails' in snip and self._thumbnails is None:
            self._thumbnails = [
                val['url']
                for (key, val) in snip['thumbnails'].items()
                if key in ['medium', 'high']
            ]

    def __init__(self, id):
        super(Playlist, self).__init__(id)

        self._title = None
        self._thumbnails = None
        self._video_count = None
        self._videos = None
        self._videos_event = None
        self._info_event = None

    def load_info(self):
        self.load_info_mult([self])
        return self._info_event

    # loads list of videos of a playlist using one API call for every 50
    # fetched videos. For every page fetched, Video.load_info_mult is called to
    # start loading video info in a separate thread.
    #
    def load_videos(self):
        if self._videos is not None or self._videos_event:
            return self._videos_event

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
                    'key': yt_key,
                    'pageToken': page,
                }
                result = session.get(yt_api_endpoint+'playlistItems',
                                     params=query)
                data = result.json()
                page = data.get('nextPageToken') or None

                videos = []
                for item in data['items']:
                    video = Video.get(item['snippet']['resourceId']['videoId'])
                    video._load_api_data(item)
                    videos.append(video)
                all_videos += videos

                # start loading video info for this batch in the background
                Video.load_info_mult(videos)

            self._videos = all_videos

        self._videos_event = ThreadPool.run(job)
        return self._videos_event

    @property
    def is_video(self):
        return False


# create methods for fetching properties loaded asynchronously
# eg video.pafy, playlist.videos
#
Entry.make_async_prop('title', 'load_info')
Entry.make_async_prop('channel', 'load_info')

Video.make_async_prop('pafy', 'load_pafy')
Video.make_async_prop('length', 'load_info')

Playlist.make_async_prop('videos', 'load_videos')
Playlist.make_async_prop('thumbnails', 'load_info')
Playlist.make_async_prop('video_count', 'load_info')


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
    def worker(self):
        while True:
            self.lock.acquire()
            if len(self.jobs):
                f, args, event = self.jobs.pop()
            else:
                # no more jobs, exit thread
                self.threads_active -= 1
                self.lock.release()
                break
            self.lock.release()

            try:
                apply(f, args)
            except Exception as e:
                logger.error('youtube thread error: %s\n%s',
                             e, traceback.format_exc())
            event.set()

    # returns threding.Event object that we can .wait() on
    @classmethod
    def run(self, f, args=()):
        self.lock.acquire()

        event = threading.Event()
        self.jobs.append((f, args, event))

        if self.threads_active < self.threads_max:
            threading.Thread(target=self.worker).start()
            self.threads_active += 1

        self.lock.release()

        return event
