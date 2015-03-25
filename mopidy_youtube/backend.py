# -*- coding: utf-8 -*-

from __future__ import unicode_literals
import re
import string
from multiprocessing.pool import ThreadPool
from urlparse import urlparse, parse_qs
import unicodedata

import pafy

from mopidy import backend
from mopidy.models import SearchResult, Track, Album
import pykka
import requests
from mopidy_youtube import logger


yt_api_endpoint = 'https://www.googleapis.com/youtube/v3/'
yt_key = 'AIzaSyAl1Xq9DwdE_KD4AtPaE4EJl3WZe2zCqg4'
session = requests.Session()


def resolve_track(track, stream=False):
    logger.debug("Resolving Youtube for track '%s'", track)
    if hasattr(track, 'uri'):
        return resolve_url(track.comment, stream)
    else:
        return resolve_url(track.split('.')[-1], stream)


def safe_url(uri):
    valid_chars = "-_.() %s%s" % (string.ascii_letters, string.digits)
    safe_uri = unicodedata.normalize(
        'NFKD',
        unicode(uri)
    ).encode('ASCII', 'ignore')
    return re.sub(
        '\s+',
        ' ',
        ''.join(c for c in safe_uri if c in valid_chars)
    ).strip()


def resolve_url(url, stream=False):
    try:
        video = pafy.new(url)
        if not stream:
            uri = 'youtube:video/%s.%s' % (
                safe_url(video.title), video.videoid
            )
        else:
            uri = video.getbestaudio()
            if not uri:  # get video url
                uri = video.getbest()
            logger.debug('%s - %s %s %s' % (
                video.title, uri.bitrate, uri.mediatype, uri.extension))
            uri = uri.url
        if not uri:
            return
    except Exception as e:
        # Video is private or doesn't exist
        logger.info(e.message)
        return

    track = Track(
        name=video.title,
        comment=video.videoid,
        length=video.length * 1000,
        album=Album(
            name='Youtube',
            images=[video.bigthumb, video.bigthumbhd]
        ),
        uri=uri
    )
    return track


def search_youtube(q):
    query = {
        'part': 'id',
        'maxResults': 15,
        'type': 'video',
        'q': q,
        'key': yt_key
    }
    result = session.get(yt_api_endpoint+'search', params=query)
    data = result.json()

    resolve_pool = ThreadPool(processes=16)
    playlist = [item['id']['videoId'] for item in data['items']]

    playlist = resolve_pool.map(resolve_url, playlist)
    resolve_pool.close()
    return [item for item in playlist if item]


def resolve_playlist(url):
    resolve_pool = ThreadPool(processes=16)
    logger.info("Resolving Youtube-Playlist '%s'", url)
    playlist = []

    page = 'first'
    while page:
        params = {
            'playlistId': url,
            'maxResults': 50,
            'key': yt_key,
            'part': 'contentDetails'
        }
        if page and page != "first":
            logger.debug("Get Youtube-Playlist '%s' page %s", url, page)
            params['pageToken'] = page

        result = session.get(yt_api_endpoint+'playlistItems', params=params)
        data = result.json()
        page = data.get('nextPageToken')

        for item in data["items"]:
            video_id = item['contentDetails']['videoId']
            playlist.append(video_id)

    playlist = resolve_pool.map(resolve_url, playlist)
    resolve_pool.close()
    return [item for item in playlist if item]


class YoutubeBackend(pykka.ThreadingActor, backend.Backend):
    def __init__(self, config, audio):
        super(YoutubeBackend, self).__init__()
        self.config = config
        self.library = YoutubeLibraryProvider(backend=self)
        self.playback = YoutubePlaybackProvider(audio=audio, backend=self)

        self.uri_schemes = ['youtube', 'yt']


class YoutubeLibraryProvider(backend.LibraryProvider):
    def lookup(self, track):
        if 'yt:' in track:
            track = track.replace('yt:', '')

        if 'youtube.com' in track:
            url = urlparse(track)
            req = parse_qs(url.query)
            if 'list' in req:
                return resolve_playlist(req.get('list')[0])
            else:
                return [resolve_url(track)]
        else:
            return [resolve_url(track)]

    def search(self, query=None, uris=None, exact=False):
        # TODO Support exact search

        if not query:
            return

        if 'uri' in query:
            search_query = ''.join(query['uri'])
            url = urlparse(search_query)
            if 'youtube.com' in url.netloc:
                req = parse_qs(url.query)
                if 'list' in req:
                    return SearchResult(
                        uri='youtube:search',
                        tracks=resolve_playlist(req.get('list')[0])
                    )
                else:
                    logger.info(
                        "Resolving Youtube for track '%s'", search_query)
                    return SearchResult(
                        uri='youtube:search',
                        tracks=[resolve_url(search_query)]
                    )
        else:
            search_query = ' '.join(query.values()[0])
            logger.info("Searching Youtube for query '%s'", search_query)
            return SearchResult(
                uri='youtube:search',
                tracks=search_youtube(search_query)
            )


class YoutubePlaybackProvider(backend.PlaybackProvider):

    def translate_uri(self, uri):
        track = resolve_track(uri, True)
        if track is not None:
            return track.uri
        else:
            return None
