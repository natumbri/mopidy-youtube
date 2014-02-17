from urllib import quote
from urlparse import urlparse
from mopidy import backend
from mopidy.models import SearchResult, Track, Album
import pykka
import pafy
from mopidy_youtube import logger


def resolve_track(track, stream=False):
    if hasattr(track, 'uri'):
        return resolve_url(track.comment, stream)
    else:
        return resolve_url(track.split('.')[-1], stream)


def resolve_url(url, stream=False):
    video = pafy.new(url)
    if not stream:
        uri = 'youtube:video/%s.%s' % (
            quote(video.title, safe="-"), video.videoid
        )
    else:
        uri = video.getbestaudio()
        if not uri:  # get video url
            uri = video.getbest()
        uri = uri.url
    track = Track(
        name=video.title,
        comment=url,
        album=Album(
            name='Youtube',
            images=[video.bigthumb, video.bigthumbhd]
        ),
        uri=uri
    )
    return track


class YoutubeBackend(pykka.ThreadingActor, backend.Backend):

    def __init__(self, config, audio):
        super(YoutubeBackend, self).__init__()
        self.config = config
        self.library = YoutubeLibraryProvider(backend=self)
        self.playback = YoutubePlaybackProvider(audio=audio, backend=self)

        self.uri_schemes = ['youtube']


class YoutubeLibraryProvider(backend.LibraryProvider):

    def lookup(self, track):
        return [resolve_track(track)]

    def search(self, query=None, uris=None):
        if not query:
            return

        if 'uri' in query:
            search_query = ''.join(query['uri'])
            url = urlparse(search_query)
            if 'youtube.com' in url.netloc:
                logger.info("Resolving Youtube for '%s'", search_query)
                return SearchResult(
                    uri='youtube:search',
                    tracks=[resolve_url(search_query)]
                )


class YoutubePlaybackProvider(backend.PlaybackProvider):

    def play(self, track):
        track = resolve_track(track, True)
        return super(YoutubePlaybackProvider, self).play(track)