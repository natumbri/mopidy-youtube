# -*- coding: utf-8 -*-

from __future__ import unicode_literals

import re
import string
import unicodedata
from urlparse import parse_qs, urlparse

from mopidy import backend, exceptions
from mopidy.models import Album, Artist, SearchResult, Track

import pykka

from mopidy_youtube import logger, youtube

# A typical interaction:
# 1. User searches for a keyword (YouTubeLibraryProvider.search)
# 2. User adds a track to the queue (YouTubeLibraryProvider.lookup)
# 3. User plays a track from the queue (YouTubePlaybackProvider.translate_uri)
#
# step 1 requires only 2 API calls. Data for the next steps are loaded in the
# background, so steps 2/3 are usually instantaneous.


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


class YouTubeBackend(pykka.ThreadingActor, backend.Backend):
    def __init__(self, config, audio):
        super(YouTubeBackend, self).__init__()
        self.config = config
        self.library = YouTubeLibraryProvider(backend=self)
        self.playback = YouTubePlaybackProvider(audio=audio, backend=self)
        youtube.API.youtube_api_key = config['youtube']['youtube_api_key']
        youtube.ThreadPool.threads_max = config['youtube']['threads_max'] 
        youtube.Video.search_results = config['youtube']['search_results']
        youtube.Playlist.playlist_max_videos = config['youtube']['playlist_max_videos']
        self.uri_schemes = ['youtube', 'yt']
        if youtube.API.test_api_key() is False:
            raise exceptions.BackendError('Failed to verify YouTube API key')


class YouTubeLibraryProvider(backend.LibraryProvider):

    # Called when browsing or searching the library. To avoid horrible browsing
    # performance, and since only search makes sense for youtube anyway, we we
    # only answer queries for the 'any' field (for instance a {'artist': 'U2'}
    # query is ignored).
    #
    # For performance we only do 2 API calls before we reply, one for search
    # (youtube.Entry.search) and one to fetch video_count of all playlists
    # (youtube.Playlist.load_info).
    #
    # We also start loading 2 things in the background:
    #  - info for all videos
    #  - video list for all playlists
    # Hence, adding search results to the playing queue (see
    # YouTubeLibraryProvider.lookup) will most likely be instantaneous, since
    # all info will be ready by that time.
    #
    def search(self, query=None, uris=None, exact=False):
        # TODO Support exact search
        logger.info('youtube LibraryProvider.search "%s"', query)

        # handle only searching (queries with 'any') not browsing!
        if not (query and 'any' in query):
            return None

        search_query = ' '.join(query['any'])
        logger.info('Searching YouTube for query "%s"', search_query)

        try:
            entries = youtube.Entry.search(search_query)
        except Exception:
            return None

        # load playlist info (to get video_count) of all playlists together
        playlists = [e for e in entries if not e.is_video]
        youtube.Playlist.load_info(playlists)

        tracks = []
        for entry in entries:
            if entry.is_video:
                uri_base = 'youtube:video'
                album = 'YouTube Video'
            else:
                uri_base = 'youtube:playlist'
                album = 'YouTube Playlist (%s videos)' % \
                        entry.video_count.get()

            tracks.append(Track(
                name=entry.title.get().replace(';', ''),
                comment=entry.id,
                length=0,
                artists=[Artist(name=entry.channel.get())],
                album=Album(
                    name=album,
                    images=entry.thumbnails.get(),
                ),
                uri='%s/%s.%s' %
                    (uri_base, safe_url(entry.title.get()), entry.id)
            ))

        # load video info and playlist videos in the background. they should be
        # ready by the time the user adds search results to the playing queue
        videos = [e for e in entries if e.is_video]
        youtube.Video.load_info(videos)

        for pl in playlists:
            pl.videos  # start loading

        return SearchResult(
            uri='youtube:search',
            tracks=tracks
        )

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
    # We also start loading the audio_url of all videos in the background, to
    # be ready for playback (see YouTubePlaybackProvider.translate_uri).
    #
    def lookup(self, uri):
        logger.info('youtube LibraryProvider.lookup "%s"', uri)

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
            video.audio_url  # start loading

            return [Track(
                name=video.title.get().replace(';', ''),
                comment=video.id,
                length=video.length.get() * 1000,
                artists=[Artist(name=video.channel.get())],
                album=Album(
                    name='YouTube Video',
                    images=video.thumbnails.get(),
                ),
                uri='youtube:video/%s.%s' %
                    (safe_url(video.title.get()), video.id)
            )]
        else:
            playlist = youtube.Playlist.get(playlist_id)
            if not playlist.videos.get():
                logger.error('Cannot load "%s"', uri)
                return []

            # ignore videos for which no info was found (removed, etc)
            videos = [v for v in playlist.videos.get()
                      if v.length.get() is not None]

            # load audio_url in the background to be ready for playback
            for video in videos:
                video.audio_url  # start loading

            return [Track(
                name=video.title.get().replace(';', ''),
                comment=video.id,
                length=video.length.get() * 1000,
                track_no=count,
                artists=[Artist(name=video.channel.get())],
                album=Album(
                    name=playlist.title.get(),
                    images=playlist.thumbnails.get(),
                ),
                uri='youtube:video/%s.%s' %
                    (safe_url(video.title.get()), video.id)
            ) for count, video in enumerate(videos, 1)]


class YouTubePlaybackProvider(backend.PlaybackProvider):

    # Called when a track us ready to play, we need to return the actual url of
    # the audio. uri must be of the form youtube:video/<title>.<id>
    # (only videos can be played, playlists are expended into tracks by
    # YouTubeLibraryProvider.lookup)
    #
    def translate_uri(self, uri):
        logger.info('youtube PlaybackProvider.translate_uri "%s"', uri)

        if 'youtube:video/' not in uri:
            return None

        try:
            id = extract_id(uri)
            return youtube.Video.get(id).audio_url.get()
        except Exception as e:
            logger.error('translate_uri error "%s"', e)
            return None

