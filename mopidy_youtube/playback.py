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
        """

        logger.debug('youtube PlaybackProvider.translate_uri "%s"', uri)

        video_id = extract_video_id(uri)

        try:
            return youtube.Video.get(video_id).audio_url.get()
        except Exception as e:
            logger.error('translate_uri error "%s"', e)
            return None
