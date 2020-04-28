import pykka
from mopidy.core import listener
from mopidy_youtube import backend, logger, youtube

autoplay_enabled = False
strict_autoplay = False
max_autoplay_length = 600
autoplayed = []
max_degrees_of_separation = 3


class YouTubeAutoplayer(pykka.ThreadingActor, listener.CoreListener):
    def __init__(self, config, core):
        super().__init__()
        self.config = config
        self.core = core
        self.autoplay_enabled = config["youtube"]["autoplay_enabled"]
        self.strict_autoplay = config["youtube"]["strict_autoplay"]
        self.max_degrees_of_separation = config["youtube"][
            "max_degrees_of_separation"
        ]
        self.max_autoplay_length = config["youtube"]["max_autoplay_length"]
        self.base_track_id = ""
        self.degrees_of_separation = 0

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

            current_track_id = backend.extract_id(track.uri)

            if current_track_id not in autoplayed:
                self.base_track_id = current_track_id
                logger.info("setting base_track_id to %s", self.base_track_id)
                autoplayed.append(current_track_id)  # avoid replaying track
            else:
                if self.degrees_of_separation < self.max_degrees_of_separation:
                    self.degrees_of_separation += 1
                else:
                    current_track_id = self.base_track_id
                    self.degrees_of_separation = 0
                    logger.info("resetting to base_track_id")

            related_videos = youtube.Video.related_videos(current_track_id)

            # try again, for testing...
            if len(related_videos) == 0:
                related_videos = youtube.Video.related_videos(current_track_id)

            for related_video in related_videos:
                track_length = related_video.length.get()
                if track_length is None:
                    related_videos.remove(related_video)
                    logger.info(
                        "cannot get lenght: %s", related_video.title.get()
                    )
                    continue

                if track_length > self.max_autoplay_length:
                    related_videos.remove(related_video)
                    logger.info("too long: %s", related_video.title.get())
                    continue

                if related_video.id in autoplayed:
                    related_videos.remove(related_video)
                    logger.info(
                        "already autoplayed: %s", related_video.title.get()
                    )

            logger.info("found %d valid related videos" % len(related_videos))

            if len(related_videos) == 0:
                logger.info("could not get related videos: ending autoplay")
                return None
            else:
                next_video = related_videos[0]
                autoplayed.append(next_video.id)
                name = next_video.title.get()
                uri = [
                    "youtube:video/%s.%s"
                    % (backend.safe_url(name), next_video.id)
                ]
                tracklist = tl.add(uris=uri).get()
                playback.play(tlid=tracklist[-1].tlid)
                return None

        except Exception as e:
            logger.error('Autoplayer error "%s"', e)
            return None
