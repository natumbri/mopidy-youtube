from __future__ import annotations

import random
from typing import TYPE_CHECKING, override

import pykka
from mopidy.core import CoreListener

from mopidy_youtube import logger, youtube
from mopidy_youtube.context import context
from mopidy_youtube.data import extract_video_id, format_video_uri

if TYPE_CHECKING:
    from mopidy.config import Config
    from mopidy.core import CoreProxy
    from mopidy.models import TlTrack


class YouTubeAutoplayer(pykka.ThreadingActor, CoreListener):
    def __init__(self, config: Config, core: CoreProxy) -> None:
        super().__init__()
        self.config = config
        self.core = core
        context.autoplayed.clear()
        self.autoplayed = context.autoplayed
        self.autoplay_enabled = config["youtube"]["autoplay_enabled"]
        self.strict_autoplay = config["youtube"]["strict_autoplay"]
        self.max_degrees_of_separation = config["youtube"]["max_degrees_of_separation"]
        max_autoplay_length = config["youtube"]["max_autoplay_length"]
        if max_autoplay_length is not None and max_autoplay_length < 60_000:
            max_autoplay_length *= 1000
        self.max_autoplay_length = max_autoplay_length
        self.base_track_id = ""
        self.degrees_of_separation = 0

    """Autoplay the next related YouTube video when the queue is exhausted."""

    def _is_fit_to_autoplay(self, video: youtube.Video) -> bool:
        length = video.length.get()
        if not length:  # 0 is probably a live video, None is unknown
            return False
        # lengths are in seconds, the limit is kept in milliseconds
        return not self.max_autoplay_length or length * 1000 < self.max_autoplay_length

    @override
    def track_playback_started(self, tl_track: TlTrack) -> None:  # noqa: PLR0911 - early exits keep the autoplay checks flat
        if not self.autoplay_enabled:
            return

        track = tl_track.track
        tl_track_id = tl_track.tlid

        if not track.uri.startswith(("youtube:", "yt:")):
            return
        try:
            tl = self.core.tracklist

            if tl.get_repeat().get() is True:
                logger.warning(
                    "Autoplayer: will not add tracks when repeat is enabled."
                )
                return

            if tl.get_random().get() is True:
                logger.warning(
                    "Autoplayer: shuffle will not work when autoplay is enabled."
                )

            if not self.strict_autoplay:
                tl_tracks = tl.get_tl_tracks().get()
                if tl_tracks:
                    if tl_track_id != tl_tracks[-1].tlid:
                        logger.debug("Autoplayer: called not at end of track list.")
                        return
                    if tl.get_consume().get() is True:
                        logger.warning(
                            "Autoplayer: when having consume track enabled, "
                            'try with "strict_autoplay" option enabled for '
                            "better results"
                        )
                        return
            logger.debug(f"getting current track id for {track.uri}")
            current_track_id = extract_video_id(track.uri)
            logger.debug(f"track id {current_track_id}")
            if self.max_degrees_of_separation:
                if self.degrees_of_separation < self.max_degrees_of_separation:
                    self.degrees_of_separation += 1
                    logger.debug("incrementing autoplay degrees of separation")
                else:
                    current_track_id = self.base_track_id
                    self.degrees_of_separation = 0
                    logger.debug("resetting to autoplay base track id")
                logger.debug(f"degrees of sep {self.degrees_of_separation}")

            if current_track_id not in self.autoplayed:
                self.base_track_id = current_track_id
                self.degrees_of_separation = 0
                logger.debug("setting new autoplay base id")
                logger.debug(f"base track id {self.base_track_id}")

            current_track = youtube.Video.get(current_track_id)
            logger.debug(f"triggered related videos for {current_track.id}")
            current_track.related_videos  # noqa: B018 - starts the background load
            logger.debug("getting related videos")
            related_videos = current_track.related_videos.get()
            logger.debug(f"autoplayer is adding a track related to {current_track.id}")
            logger.debug(f"related videos {related_videos}")
            # not already autoplayed, in a random order
            candidates = [
                related_video
                for related_video in related_videos
                if related_video.id not in (*self.autoplayed, self.base_track_id)
            ]
            random.shuffle(candidates)
            logger.debug(f"related videos edit 1 {candidates}")

            # The first one that is a fit is as good a pick as any other, and a
            # length may cost a request: ask for them one at a time, not all at once.
            next_video = next(
                (video for video in candidates if self._is_fit_to_autoplay(video)),
                None,
            )
            if next_video is None:
                logger.warning(
                    f"could not get videos related to {current_track.id}: "
                    "ending autoplay"
                )
                return

            logger.debug(f"next video {next_video.id}")
            self.autoplayed.append(next_video.id)
            uri = [format_video_uri(next_video.id)]
            tl.add(uris=uri).get()
        except Exception as e:
            logger.error("Autoplayer error %r", e)
            return
