from mopidy import backend

from mopidy_youtube import logger, youtube
from mopidy_youtube.data import extract_video_id


class YouTubePlaybackProvider(backend.PlaybackProvider):
    def should_download(self, uri):
        return True

    def translate_uri(self, uri):
        """
        Called when a track is ready to play, we need to return the actual url of
        the audio. uri must be of the form youtube:video/<title>.<id> or youtube:video:<id>
        (only videos can be played, playlists are expanded into tracks by
        YouTubeLibraryProvider.lookup)

        While a track is still caching this is an http://localhost url served by
        AudioHandler; once caching has finished it is a file:// url.
        """

        logger.debug('youtube PlaybackProvider.translate_uri "%s"', uri)

        try:
            video = youtube.Video.get(extract_video_id(uri))
            url = video.audio_url.get(timeout=120)
            if url is not None and video.cached_file_uri:
                url = video.cached_file_uri
            logger.debug('translate_uri "%s" -> %s', uri, url)
            return url
        except Exception as e:
            logger.error('translate_uri error "%s"', e)
            return None
