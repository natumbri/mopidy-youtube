import pykka
from mopidy.core import listener, TracklistController, PlaybackController
from mopidy.models import TlTrack, Track

from mopidy_youtube import Extension, logger, youtube, backend
from mopidy_youtube.apis import youtube_api

autoplay_enabled = False
strict_autoplay = False

class YoutubeAutoplayer(pykka.ThreadingActor, listener.CoreListener):
    def __init__(self, config, core):
        super().__init__()
        self.config = config
        self.core = core
        self.autoplay_enabled = config["youtube"]["autoplay_enabled"]
        self.strict_autoplay = config["youtube"]["strict_autoplay"]

    def track_playback_ended(self, tl_track, time_position):
        if not self.autoplay_enabled:
            return None

        if not youtube.api_enabled:
            logger.warning('Autoplayer: will not work with disabled youtube api, disabling Autoplayer.')
            self.autoplay_enabled = False
            return None

        [tlTrackId, track] = tl_track
        if "youtube:video/" not in track.uri:
            return None

        try:
            playback = self.core.playback
            tl = self.core.tracklist

            if tl.get_repeat().get() is True:
                logger.info('Autoplayer: will not add tracks when repeat is enabled.')
                return None

            if tl.get_random().get() is True:
                logger.info('Autoplayer: shuffle will not work when autoplay is enabled.')

            if time_position < (track.length-1000):
                logger.debug('Autoplayer: called not at end of track.')
                return None

            if self.strict_autoplay is False:
                tlTracks = tl.get_tl_tracks().get()
                if len(tlTracks) is not 0:
                    if tlTrackId is not tlTracks[-1].tlid:
                        logger.debug('Autoplayer: called not at end of track list.')
                        return None
                    elif tl.get_consume().get() is True:
                        logger.warning('Autoplayer: when having consume track enabled, try with "strict_autoplay" option enabled for better results')
                        return None

            id = backend.extract_id(track.uri)
            nextVideo = youtube.Entry.get_next_video(id)
            name = nextVideo.title.get()
            uri="youtube:video/%s.%s" % (backend.safe_url(name), nextVideo.id)
            nextUriList = list()
            nextUriList.append(uri)
            tracklist = tl.add(uris=nextUriList).get()
            playback.play(tlid=tracklist[-1].tlid)
            return None

        except Exception as e:
            logger.error('Autoplayer error "%s"', e)
            return None
