import pykka
from mopidy.core import PlaybackController, TracklistController, listener
from mopidy.models import TlTrack, Track

from mopidy_youtube import Extension, backend, logger, youtube
from mopidy_youtube.apis import youtube_api

autoplay_enabled = False
strict_autoplay = False


class YouTubeAutoplayer(pykka.ThreadingActor, listener.CoreListener):
    def __init__(self, config, core):
        super().__init__()
        self.config = config
        self.core = core
        self.autoplay_enabled = config["youtube"]["autoplay_enabled"]
        self.strict_autoplay = config["youtube"]["strict_autoplay"]

    # Called by mopidy on end of playback of a URI
    # This function emulates the youtube autoplay functionality by retrieving the most
    # most related video to a video just played by a youtube API call, adding this new
    # video URI to the tracklist and triggering it's playback
    #
    # With the option "strict_autoplay" enabled, the next played URI will be the newly
    # added video.
    # Without the option "strict_autoplay" enabled [default], the autoplay functionality
    # will only be executed if the end of the current tracklist is reached
    #
    # The autoplay functionality will not work correctly in combination with the repeat
    # option and is therefore disabled if repeat is enabled
    def track_playback_ended(self, tl_track, time_position):
        if not self.autoplay_enabled:
            return None

        [tlTrackId, track] = tl_track
        if "youtube:video/" not in track.uri:
            return None

        try:
            playback = self.core.playback
            tl = self.core.tracklist

            if tl.get_repeat().get() is True:
                logger.info(
                    "Autoplayer: will not add tracks when repeat is enabled."
                )
                return None

            if tl.get_random().get() is True:
                logger.info(
                    "Autoplayer: shuffle will not work when autoplay is enabled."
                )

            if time_position < (track.length - 1000):
                logger.debug("Autoplayer: called not at end of track.")
                return None

            if self.strict_autoplay is False:
                tlTracks = tl.get_tl_tracks().get()
                if len(tlTracks) != 0:
                    if tlTrackId is not tlTracks[-1].tlid:
                        logger.debug(
                            "Autoplayer: called not at end of track list."
                        )
                        return None
                    elif tl.get_consume().get() is True:
                        logger.warning(
                            "Autoplayer: when having consume track enabled, "
                            'try with "strict_autoplay" option enabled for '
                            "better results"
                        )
                        return None

            id = backend.extract_id(track.uri)
            nextVideo = youtube.Entry.get_next_video(id)
            name = nextVideo.title.get()
            uri = "youtube:video/%s.%s" % (backend.safe_url(name), nextVideo.id)
            nextUriList = list()
            nextUriList.append(uri)
            tracklist = tl.add(uris=nextUriList).get()
            playback.play(tlid=tracklist[-1].tlid)
            return None

        except Exception as e:
            logger.error('Autoplayer error "%s"', e)
            return None
