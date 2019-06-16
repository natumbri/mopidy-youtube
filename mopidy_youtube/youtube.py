# -*- coding: utf-8 -*-

import json
import re
import threading
import traceback
from itertools import islice

from cachetools import LRUCache, cached

import pykka

import requests

import youtube_dl

from mopidy_youtube import logger

api_enabled = False


# decorator for creating async properties using pykka.ThreadingFuture
# A property 'foo' should have a future '_foo'
# On first call we invoke func() which should create the future
# On subsequent calls we just return the future
#
def async_property(func):
    _future_name = '_' + func.__name__

    def wrapper(self):
        if _future_name not in self.__dict__:
            func(self)   # should create the future
        return self.__dict__[_future_name]

    return property(wrapper)


# The Video / Playlist classes can be used to load YouTube data. If
# 'api_enabled' is true (and a valid youtube_api_key supplied), most data are
# loaded using the (very much faster) YouTube Data API. If 'api_enabled' is
# false, most data are loaded using requests and regex. Requests and regex
# is many times slower than using the API.
#
# eg
#   video = youtube.Video.get('7uj0hOIm2kY')
#   video.length   # non-blocking, returns future
#   ... later ...
#   print video.length.get()  # blocks until info arrives, if it hasn't already
#
# Entry is a base class of Video and Playlist
#
class Entry(object):
    cache_max_len = 400

    # Use Video.get(id), Playlist.get(id), instead of Video(id), Playlist(id),
    # to fetch a cached object, if available
    #
    @classmethod
    @cached(cache=LRUCache(maxsize=cache_max_len))
    def get(cls, id):
        obj = cls()
        obj.id = id
        return obj

    # Search for both videos and playlists using a single API call. Fetches
    # only title, thumbnails, channel (extra queries are needed for length and
    # video_count)
    #
    @classmethod
    def search(cls, q):
        def create_object(item):
            if item['id']['kind'] == 'youtube#video':
                obj = Video.get(item['id']['videoId'])
                if 'contentDetails' in item:
                    obj._set_api_data(
                        ['title', 'channel', 'length'],
                        item
                    )
                else:
                    obj._set_api_data(
                        ['title', 'channel'],
                        item
                    )
            elif item['id']['kind'] == 'youtube#playlist':
                obj = Playlist.get(item['id']['playlistId'])
                if 'contentDetails' in item:
                    obj._set_api_data(
                        ['title', 'channel', 'thumbnails', 'video_count'],
                        item
                    )
                else:
                    obj._set_api_data(
                        ['title', 'channel', 'thumbnails'],
                        item
                    )
            elif item['id']['kind'] == 'youtube#radiolist':
                obj = Video.get(item['id']['videoId'])
                obj._set_api_data(
                    ['title', 'video_count'],
                    item
                )
            else:
                obj = []
            return obj

        try:
            data = cls.api.search(q)
        except Exception as e:
            logger.error('search error "%s"', e)
            return None
        try:
            logger.info(data['items'])
            return map(create_object, data['items'])
        except Exception as e:
            logger.error('map error "%s"', e)
            return None

    # Adds futures for the given fields to all objects in list, unless they
    # already exist. Returns objects for which at least one future was added
    #
    @classmethod
    def _add_futures(cls, list, fields):
        def add(obj):
            added = False
            for k in fields:
                if '_' + k not in obj.__dict__:
                    obj.__dict__['_' + k] = pykka.ThreadingFuture()
                    added = True
            return added

        return filter(add, list)

    # common Video/Playlist properties go to the base class
    #
    @async_property
    def title(self):
        self.load_info([self])

    @async_property
    def channel(self):
        self.load_info([self])

    # sets the given 'fields' of 'self', based on the 'item'
    # data retrieved through the API
    #
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
                m = re.search(r'P((?P<weeks>\d+)W)?'
                              + r'((?P<days>\d+)D)?'
                              + r'T((?P<hours>\d+)H)?'
                              + r'((?P<minutes>\d+)M)?'
                              + r'((?P<seconds>\d+)S)?',
                              item['contentDetails']['duration'])
                val = (int(m.group('weeks') or 0) * 604800
                       + int(m.group('days') or 0) * 86400
                       + int(m.group('hours') or 0) * 3600
                       + int(m.group('minutes') or 0) * 60
                       + int(m.group('seconds') or 0))
            elif k == 'video_count':
                val = min(
                    item['contentDetails']['itemCount'],
                    self.playlist_max_videos
                )
            elif k == 'thumbnails':
                val = [
                    val['url']
                    for (key, val) in item['snippet']['thumbnails'].items()
                    if key in ['default', 'medium', 'high']
                ]

            future.set(val)


class Video(Entry):

    # loads title, length, channel of multiple videos using one API call for
    # every 50 videos. API calls are split in separate threads.
    #
    @classmethod
    def load_info(cls, list):
        fields = ['title', 'length', 'channel']
        list = cls._add_futures(list, fields)

        def job(sublist):
            try:
                data = cls.api.list_videos([x.id for x in sublist])
                dict = {item['id']: item for item in data['items']}
            except Exception as e:
                logger.error('list_videos error "%s"', e)
                dict = {}

            for video in sublist:
                video._set_api_data(fields, dict.get(video.id))

        # 50 items at a time, make sure order is deterministic so that HTTP
        # requests are replayable in tests
        for i in range(0, len(list), 50):
            sublist = list[i:i + 50]
            ThreadPool.run(job, (sublist,))

    @async_property
    def length(self):
        self.load_info([self])

    @async_property
    def thumbnails(self):
        # make it "async" for uniformity with Playlist.thumbnails
        self._thumbnails = pykka.ThreadingFuture()
        self._thumbnails.set([
            'https://i.ytimg.com/vi/%s/%s.jpg' % (self.id, type)
            for type in ['mqdefault', 'hqdefault']
        ])

    # audio_url is the only property retrived using youtube_dl, it's much more
    # expensive than the rest
    #
    @async_property
    def audio_url(self):
        self._audio_url = pykka.ThreadingFuture()

        def job():
            try:
                info = youtube_dl.YoutubeDL({
                    'format': 'm4a/vorbis/bestaudio/best',
                    'proxy': self.proxy
                }).extract_info(
                    url="https://www.youtube.com/watch?v=%s" % self.id,
                    download=False,
                    ie_key=None,
                    extra_info={},
                    process=True,
                    force_generic_extractor=False
                )
            except Exception as e:
                logger.error('audio_url error "%s"', e)
                self._audio_url.set(None)
                return
            self._audio_url.set(info['url'])

        ThreadPool.run(job)

    @property
    def is_video(self):
        return True


class Playlist(Entry):

    # loads title, thumbnails, video_count, channel of multiple playlists using
    # one API call for every 50 lists. API calls are split in separate threads.
    #
    @classmethod
    def load_info(cls, list):
        fields = ['title', 'video_count', 'thumbnails', 'channel']
        list = cls._add_futures(list, fields)

        def job(sublist):
            try:
                data = cls.api.list_playlists([x.id for x in sublist])
                dict = {item['id']: item for item in data['items']}
            except Exception as e:
                logger.error('list_playlists error "%s"', e)
                dict = {}

            for pl in sublist:
                pl._set_api_data(fields, dict.get(pl.id))

        # 50 items at a time, make sure order is deterministic so that HTTP
        # requests are replayable in tests
        for i in range(0, len(list), 50):
            sublist = list[i:i + 50]
            ThreadPool.run(job, (sublist,))

    # loads the list of videos of a playlist using one API call for every 50
    # fetched videos. For every page fetched, Video.load_info is called to
    # start loading video info in a separate thread.
    #
    @async_property
    def videos(self):
        self._videos = pykka.ThreadingFuture()

        def job():
            all_videos = []
            page = ''
            while page is not None \
                    and len(all_videos) < self.playlist_max_videos:
                try:
                    max_results = min(
                        self.playlist_max_videos - len(all_videos),
                        50
                    )
                    data = self.api.list_playlistitems(
                        self.id,
                        page,
                        max_results
                    )
                except Exception as e:
                    logger.error('list playlist items error "%s"', e)
                    break
                if 'error' in data:
                    logger.error('error in list playlist items data')
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


class Client:

    session = requests.Session()


# Direct access to YouTube Data API
# https://developers.google.com/youtube/v3/docs/
#
class API(Client):
    endpoint = 'https://www.googleapis.com/youtube/v3/'

    # search for both videos and playlists using a single API call
    # https://developers.google.com/youtube/v3/docs/search
    #
    @classmethod
    def search(cls, q):
        query = {
            'part': 'id,snippet',
            'fields': 'items(id,snippet(title,thumbnails,channelTitle))',
            'maxResults': Video.search_results,
            'type': 'video,playlist',
            'q': q,
            'key': API.youtube_api_key
        }
        result = cls.session.get(API.endpoint + 'search', params=query)
        return result.json()

    # list videos
    # https://developers.google.com/youtube/v3/docs/videos/list
    @classmethod
    def list_videos(cls, ids):
        query = {
            'part': 'id,snippet,contentDetails',
            'fields': 'items(id,snippet(title,channelTitle),'
                      + 'contentDetails(duration))',
            'id': ','.join(ids),
            'key': API.youtube_api_key
        }
        result = cls.session.get(API.endpoint + 'videos', params=query)
        return result.json()

    # list playlists
    # https://developers.google.com/youtube/v3/docs/playlists/list
    @classmethod
    def list_playlists(cls, ids):
        query = {
            'part': 'id,snippet,contentDetails',
            'fields': 'items(id,snippet(title,thumbnails,channelTitle),'
                      + 'contentDetails(itemCount))',
            'id': ','.join(ids),
            'key': API.youtube_api_key
        }
        result = cls.session.get(API.endpoint + 'playlists', params=query)
        return result.json()

    # list playlist items
    # https://developers.google.com/youtube/v3/docs/playlistItems/list
    @classmethod
    def list_playlistitems(cls, id, page, max_results):
        query = {
            'part': 'id,snippet',
            'fields': 'nextPageToken,'
                      + 'items(snippet(title,resourceId(videoId)))',
            'maxResults': max_results,
            'playlistId': id,
            'key': API.youtube_api_key,
            'pageToken': page,
        }
        result = cls.session.get(API.endpoint + 'playlistItems', params=query)
        return result.json()


# Indirect access to YouTube data, without API
#
class scrAPI(Client):
    endpoint = 'https://www.youtube.com/'

    # search for videos and playlists
    #
    @classmethod
    def search(cls, q):
        query = {
            # # get videos only
            # 'sp': 'EgIQAQ%253D%253D',
            'search_query': q.replace(' ', '+')
        }
        result = scrAPI.session.get(scrAPI.endpoint+'results', params=query)
        regex = (
            r'(?:\<li\>\<div class\=\"yt-lockup yt-lockup-tile yt-lockup-'
            r'(?:playlist|video) vve-check clearfix)'
            r'(?:.|\n)*?(?:\<a href\=\"\/watch\?v\=)(?P<id>.{11})'
            r'(?:\&amp\;list\=(?:(?P<playlist>PL.*?)\")?'
            r'(?:.|\n)'
            # r'(?:(?P<radiolist>RD.*?)\&)?(?:.|\n)'
            r'(?:.|\n)*?span class\=\"formatted-video-count-label\"\>\<b\>'
            r'(?P<itemCount>\d*))?(?:.|\n)*?\"\s*title\=\"(?P<title>.+?)" .+?'
            r'(?:(?:Duration\:\s*(?:(?P<durationHours>[0-9]+)\:)?'
            r'(?P<durationMinutes>[0-9]+)\:'
            r'(?P<durationSeconds>[0-9]{2}).\<\/span\>.*?)?)?\<a href\=\"'
            r'(?:(?:(?P<uploaderUrl>/(?:user|channel)/[^"]+)"[^>]+>)?'
            r'(?P<uploader>.*?)\<\/a\>.*?class\=\"'
            r'(?:yt-lockup-description|yt-uix-sessionlink)[^>]*>'
            r'(?P<description>.*?)\<\/div\>)?'
        )
        items = []

        for match in re.finditer(regex, result.text):
            duration = ''
            if match.group('durationHours') is not None:
                duration += match.group('durationHours')+'H'
            if match.group('durationMinutes') is not None:
                duration += match.group('durationMinutes')+'M'
            if match.group('durationSeconds') is not None:
                duration += match.group('durationSeconds')+'S'
            if match.group('playlist') is not None:
                item = {
                    'id': {
                      'kind': 'youtube#playlist',
                      'playlistId': match.group('playlist')
                    },
                    'contentDetails': {
                        'itemCount': match.group('itemCount')
                    }
                }
            # elif match.group('radiolist') is not None:
            #     item = {
            #         'id': {
            #           'kind': 'youtube#radiolist',
            #           'playlistId': match.group('radiolist'),
            #           'videoId': match.group('id')
            #         },
            #         'contentDetails': {
            #             'itemCount': match.group('itemCount')
            #         }
            #     }
            else:
                item = {
                    'id': {
                      'kind': 'youtube#video',
                      'videoId': match.group('id')
                    },
                }
                if duration != '':
                    item.update ({
                        'contentDetails': {
                            'duration': 'PT'+duration,
                        },
                    })
            item.update({
                'snippet': {
                      'title': match.group('title'),
                      # TODO: full support for thumbnails
                      'thumbnails': {
                          'default': {
                              'url': 'https://i.ytimg.com/vi/'
                                     + match.group('id')
                                     + '/default.jpg',
                              'width': 120,
                              'height': 90,
                          },
                      },
                },
            })
            if match.group('uploader') is not None:
                item['snippet'].update({
                    'channelTitle': match.group('uploader')
                })

            items.append(item)
        return json.loads(json.dumps(
            {'items': items},
            sort_keys=False,
            indent=1
        ))

    # list videos
    #
    @classmethod
    def list_videos(cls, ids):

        regex = (
            r'<div id="watch7-content"(?:.|\n)*?'
            r'<meta itemprop="name" content="'
            r'(?P<title>.*?)(?:">)(?:.|\n)*?'
            r'<meta itemprop="duration" content="'
            r'(?P<duration>.*?)(?:">)(?:.|\n)*?'
            r'<link itemprop="url" href="http://www.youtube.com/'
            r'(?:user|channel)/(?P<channelTitle>.*?)(?:">)(?:.|\n)*?'
            r'</div>'
        )
        items = []

        for id in ids:
            query = {
                'v': id,
            }
            result = scrAPI.session.get(
                scrAPI.endpoint+'watch',
                params=query
            )
            for match in re.finditer(regex, result.text):
                item = {
                    'id': id,
                    'snippet': {
                        'title': match.group('title'),
                        'channelTitle': match.group('channelTitle'),
                    },
                    'contentDetails': {
                        'duration': match.group('duration'),
                    }
                }
                items.append(item)
        return json.loads(json.dumps(
            {'items': items},
            sort_keys=False,
            indent=1
        ))

    # list playlists
    #
    @classmethod
    def list_playlists(cls, ids):

        regex = (
            r'<div id="pl-header"(?:.|\n)*?"'
            r'(?P<thumbnail>https://i\.ytimg\.com\/vi\/.{11}/).*?\.jpg'
            r'(?:(.|\n))*?(?:.|\n)*?class="pl-header-title"'
            r'(?:.|\n)*?\>\s*(?P<title>.*)(?:.|\n)*?<a href="/'
            r'(user|channel)/(?:.|\n)*? >'
            r'(?P<channelTitle>.*?)</a>(?:.|\n)*?'
            r'(?P<itemCount>\d*) videos</li>'
        )
        items = []

        for id in ids:
            query = {
                'list': id,
            }
            result = scrAPI.session.get(
                scrAPI.endpoint+'playlist',
                params=query
            )
            for match in re.finditer(regex, result.text):
                item = {
                    'id': id,
                    'snippet': {
                        'title': match.group('title'),
                        'channelTitle': match.group('channelTitle'),
                        'thumbnails': {
                            'default': {
                                'url': match.group('thumbnail')+'default.jpg',
                                'width': 120,
                                'height': 90,
                            },
                        },
                    },
                    'contentDetails': {
                        'itemCount': match.group('itemCount'),
                    }
                }
                items.append(item)
        return json.loads(json.dumps(
            {'items': items},
            sort_keys=False,
            indent=1
        ))

    # list playlist items
    #
    @classmethod
    def list_playlistitems(cls, id, page, max_results):

        query = {
            'list': id
        }

        result = scrAPI.session.get(scrAPI.endpoint+'playlist', params=query)
        regex = (
            r'" data-title="(?P<title>.+?)".*?'
            r'<a href="/watch\?v=(?P<id>.{11})\&amp;'
        )
        items = []

        for match in islice(re.finditer(regex, result.text), max_results):
            item = {
                'snippet': {
                    'resourceId': {
                        'videoId': match.group('id'),
                        },
                    'title': match.group('title'),
                },
            }
            items.append(item)
        return json.loads(json.dumps(
            {'nextPageToken': None, 'items': items},
            sort_keys=False,
            indent=1
        ))


## JSON based scrAPI
class jAPI(scrAPI):

    # search for videos and playlists
    #
    @classmethod
    def search(cls, q):
        query = {
            # get videos only
            # 'sp': 'EgIQAQ%253D%253D',
            'search_query': q.replace(' ','+')
        }

        jAPI.session.headers = {
            'user-agent': "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:66.0) Gecko/20100101 Firefox/66.0",
            'Cookie': 'PREF=hl=en;',
            'Accept-Language': 'en;q=0.5',
            'content_type': 'application/json'
        }

        result = jAPI.session.get(jAPI.endpoint+'results', params=query)

        json_regex = r'window\["ytInitialData"] = (.*?);'
        extracted_json = re.search(json_regex, result.text).group(1)
        result_json = json.loads(extracted_json)['contents']['twoColumnSearchResultsRenderer']['primaryContents']['sectionListRenderer']['contents'][0]['itemSectionRenderer']['contents']
        
        items = []
        for content in result_json:
            item = {}
            if 'videoRenderer' in content:
                item.update({
                    'id': {
                        'kind': 'youtube#video',
                        'videoId': content['videoRenderer']['videoId']
                    },
                    # 'contentDetails': {
                    #     'duration': 'PT'+duration
                    # }
                    'snippet': {
                        'title': content['videoRenderer']['title']['simpleText'],
                        # TODO: full support for thumbnails
                        'thumbnails': {
                            'default': {
                                'url': 'https://i.ytimg.com/vi/'
                                       + content['videoRenderer']['videoId']
                                       + '/default.jpg',
                                'width': 120,
                                'height': 90,
                            },
                        },
                        'channelTitle': content['videoRenderer']['longBylineText']['runs'][0]['text'],
                    },
                })
            elif 'radioRenderer' in content:
               pass
            elif 'playlistRenderer' in content:
                item.update({
                    'id': {
                        'kind': 'youtube#playlist',
                        'playlistId': content['playlistRenderer']['playlistId']
                    },
                    'contentDetails': {
                        'itemCount': content['playlistRenderer']['videoCount']
                    },
                    'snippet': {
                        'title': content['playlistRenderer']['title']['simpleText'],
                        # TODO: full support for thumbnails
                       'thumbnails': {
                            'default': {
                                'url': 'https://i.ytimg.com/vi/'
                                       + content['playlistRenderer']['navigationEndpoint']['watchEndpoint']['videoId']
                                       + '/default.jpg',
                                'width': 120,
                                'height': 90,
                            },
                        'channelTitle': content['playlistRenderer']['longBylineText']['runs'][0]['text'],
                        }
                    },
                }) 
            items.append(item)
        return json.loads(json.dumps(
            {'items': [i for i in items if i]},
            sort_keys=False,
            indent=1
        ))


# simple 'dynamic' thread pool. Threads are created when new jobs arrive, stay
# active for as long as there are active jobs, and get destroyed afterwards
# (so that there are no long-term threads staying active)
#
class ThreadPool:
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
                f(*args)
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
