# -*- coding: utf-8 -*-

from __future__ import unicode_literals
import re
import string
from urlparse import urlparse, parse_qs
from mopidy import backend
from mopidy.models import SearchResult, Track, Album, Artist
import pykka
import pafy
import requests
import unicodedata
from mopidy_youtube import logger

yt_api_endpoint = 'https://www.googleapis.com/youtube/v3/'
yt_key = 'AIzaSyAl1Xq9DwdE_KD4AtPaE4EJl3WZe2zCqg4'


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

    track = Track(
        name=video.title,
        comment=video.videoid,
        length=video.length*1000,
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
    pl = requests.get(yt_api_endpoint+'search', params=query)
    playlist = []
    for yt_id in pl.json().get('items'):
        try:
            track = resolve_url(yt_id.get('id').get('videoId'))
            playlist.append(track)
        except Exception as e:
            logger.info(e.message)
    return playlist


def resolve_playlist(url):
    logger.info("Resolving Youtube for playlist '%s'", url)
    query = {
        'part': 'snippet',
        'maxResults': 50,
        'playlistId': url,
        'fields': 'items/snippet/resourceId',
        'key': yt_key
    }
    pl = requests.get(yt_api_endpoint+'playlistItem', params=query)
    playlist = []
    for yt_id in pl.json().get('items'):
        try:
            yt_id = yt_id.get('snippet').get('resourceId').get('videoId')
            playlist.append(resolve_url(yt_id))
        except Exception as e:
            logger.info(e.message)
    return playlist


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

    def search(self, query=None, uris=None):
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

    def play(self, track):
        track = resolve_track(track, True)
        return super(YoutubePlaybackProvider, self).play(track)
