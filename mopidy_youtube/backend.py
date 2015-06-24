# -*- coding: utf-8 -*-

from __future__ import unicode_literals

import re
import string
import unicodedata
from urlparse import parse_qs, urlparse

from mopidy import backend
from mopidy.models import Album, Artist, SearchResult, Track

import pykka

from mopidy_youtube import logger, youtube


# youtube:video/<title>.<id> ==> <id>
def extract_id(uri):
    return uri.split('.')[-1]


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


class YoutubeBackend(pykka.ThreadingActor, backend.Backend):
    def __init__(self, config, audio):
        super(YoutubeBackend, self).__init__()
        self.config = config
        self.library = YoutubeLibraryProvider(backend=self)
        self.playback = YoutubePlaybackProvider(audio=audio, backend=self)

        self.uri_schemes = ['youtube', 'yt']


class YoutubeLibraryProvider(backend.LibraryProvider):

    # Called when the user adds a track to the playing queue, either from the
    # search results, or directly by adding a yt:http://youtube.com/.... uri.
    # uri can be of the form
    #   [yt|youtube]:<url to youtube video>
    #   [yt|youtube]:<url to youtube playlist>
    #   youtube:video/<title>.<id>
    #   youtube:playlist/<title>.<id>
    #
    # If uri is a video then a single track is returned. If it's a playlist the
    # list of all videos in the playlist is returned.
    #
    # We also start loading the pafy object of all videos in the background, to
    # be ready for playback.
    #
    def lookup(self, uri):
        logger.info("youtube LibraryProvider.lookup '%s'", uri)

        video_id = playlist_id = None

        if 'youtube.com' in uri:
            url = urlparse(uri.replace('yt:', '').replace('youtube:', ''))
            req = parse_qs(url.query)
            if 'list' in req:
                playlist_id = req.get('list')[0]
            else:
                video_id = req.get('v')[0]

        elif 'video/' in uri:
            video_id = extract_id(uri)
        else:
            playlist_id = extract_id(uri)

        if video_id:
            video = youtube.Video.get(video_id)
            video.load_pafy()

            return [Track(
                name=video.title,
                comment=video.id,
                length=video.length * 1000,
                artists=[Artist(name=video.channel)],
                album=Album(
                    name='Youtube Video',
                    images=video.thumbnails,
                ),
                uri='youtube:video/%s.%s' % (safe_url(video.title), video.id)
            )]
        else:
            playlist = youtube.Playlist.get(playlist_id)
            if not playlist.videos:
                logger.info("cannot load playlist: %s" % uri)
                return []

            # ignore videos for which no info was found (removed, etc)
            videos = [v for v in playlist.videos if v.length is not None]

            # load pafy in the background to be ready for playback
            for video in videos:
                video.load_pafy()

            return [Track(
                name=video.title,
                comment=video.id,
                length=video.length * 1000,
                track_no=count,
                artists=[Artist(name=video.channel)],
                album=Album(
                    name=playlist.title,
                    images=playlist.thumbnails,
                ),
                uri='youtube:video/%s.%s' % (safe_url(video.title), video.id)
            ) for count, video in enumerate(videos, 1)]

    # Called when browsing or searching the library. To avoid horrible browsing
    # performance, and since only search makes sense for youtube anyway, we we
    # only answer queries for the 'any' field (for instance a {'artist': 'U2'}
    # query is ignored.
    #
    # For performance we only do 2 API calls before we reply, one for search
    # (youtube.API.search) and one to fetch video_count of all playlists
    # (youtube.Playlist.load_info_mult).
    #
    # We also start loading 2 things in the background: info for all videos and
    # video list for all playlists. Hence, adding search results to the playing
    # queue will most likely be instantaneous, since all info will be ready by
    # that time.
    #
    def search(self, query=None, uris=None, exact=False):
        # TODO Support exact search
        logger.info("youtube LibraryProvider.search '%s'", query)

        if not (query and 'any' in query):
            return None

        search_query = ' '.join(query['any'])
        logger.info("Searching Youtube for query '%s'", search_query)

        try:
            entries = youtube.API.search(search_query)
        except Exception:
            return None

        # load playlist info (to get video_count) of all playlists together
        playlists = [e for e in entries if not e.is_video]
        youtube.Playlist.load_info_mult(playlists)

        tracks = []
        for entry in entries:
            if entry.is_video:
                uri_base = 'youtube:video'
                album = 'Youtube Video'
            else:
                uri_base = 'youtube:playlist'
                album = 'Youtube Playlist (%s videos)' % entry.video_count

            tracks.append(Track(
                name=entry.title,
                comment=entry.id,
                length=0,
                artists=[Artist(name=entry.channel)],
                album=Album(
                    name=album,
                    images=entry.thumbnails,
                ),
                uri='%s/%s.%s' % (uri_base, safe_url(entry.title), entry.id)
            ))

        # load video info/playlist videos in the background. they should be
        # ready by the time the user adds search results to the playing queue
        videos = [e for e in entries if e.is_video]
        youtube.Video.load_info_mult(videos)

        for pl in playlists:
            pl.load_videos()

        return SearchResult(
            uri='youtube:search',
            tracks=tracks
        )


class YoutubePlaybackProvider(backend.PlaybackProvider):

    # Called when a track us ready to play, we need to return the actual url of
    # the audio. uri must be of the form youtube:video/<title>.<id>
    # (only videos can be played, playlists are expended into tracks by
    # YoutubeLibraryProvider.lookup)
    #
    def translate_uri(self, uri):
        logger.info("youtube PlaybackProvider.translate_uri %s", uri)

        if 'youtube:video/' not in uri:
            return None

        try:
            return youtube.Video.get(extract_id(uri)).audio_url
        except Exception as e:
            logger.error("translate_uri error: %s", e)
            return None
