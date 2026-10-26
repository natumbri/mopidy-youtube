from concurrent.futures.thread import ThreadPoolExecutor

import pykka
from mopidy import listener
from mopidy.core import CoreListener

from mopidy_youtube import logger, runtime, youtube
from mopidy_youtube.data import extract_video_id


class YouTubeCoreListener(pykka.ThreadingActor, CoreListener):
    _prefetch_executor = None
    _prefetch_limit = 3

    def __init__(self, config, core):
        super().__init__()
        self.config = config
        self.core = core
        self.autoplayed = runtime.autoplayed

    @classmethod
    def get_prefetch_executor(cls):
        if cls._prefetch_executor is None:
            cls._prefetch_executor = ThreadPoolExecutor(max_workers=1)
        return cls._prefetch_executor

    @classmethod
    def shutdown_prefetch_executor(cls):
        executor = cls._prefetch_executor
        cls._prefetch_executor = None
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)

    def on_stop(self):
        self.shutdown_prefetch_executor()

    def _prefetch_youtube_audio(self):
        try:
            tracks = self.core.tracklist.get_tracks().get()
        except Exception:
            logger.exception("Failed to load tracklist while prefetching YouTube audio")
            return

        video_ids = [
            extract_video_id(track.uri)
            for track in tracks[: self._prefetch_limit]
            if track.uri.startswith(("youtube:video:", "yt:video:"))
        ]

        for video_id in video_ids:
            if not video_id:
                continue
            try:
                youtube.Video.get(video_id).audio_url
            except Exception:
                logger.exception("Failed to prefetch audio for YouTube video %s", video_id)

    def tracklist_changed(self):
        # Keep the Mopidy actor callback itself lightweight. We only enqueue the
        # work in a shared background thread so we do not block the actor on
        # tracklist resolution or network/media fetches.
        self.get_prefetch_executor().submit(self._prefetch_youtube_audio)

    # used for add to playback history function
    # stolen from mopidy-ytmusic (https://github.com/OzymandiasTheGreat/mopidy-ytmusic/blob/master/mopidy_ytmusic/scrobble_fe.py)
    # who stole it from mopidy-gmusic
    def track_playback_ended(self, tl_track, time_position):
        if not self.config.get("youtube", {}).get("history_enabled", False):
            return

        track = tl_track.track
        if track.uri.startswith(("youtube:video:", "yt:video:")):
            duration = track.length // 1000 if track.length else 0
            time_position = time_position // 1000

            if time_position < duration // 2 and time_position < 120:
                logger.debug(
                    "Track not played long enough to add to history. (50% or 120s)"
                )
                return

            b_id = track.uri.split(":")[2]
            logger.debug(f"track playback ended {b_id}")

            # probably should add a config option for adding autoplayed to history
            # for now, autoplayed tracks are not added to history
            if b_id not in self.autoplayed:
                logger.debug(f"adding {b_id} to history")
                listener.send(
                    YouTubeAddToHistoryListener,
                    "add_track_to_history",
                    bId=b_id,
                )
            else:
                logger.debug(f"not adding {b_id} to history: autoplayed")


class YouTubeAddToHistoryListener(listener.Listener):
    def add_track_to_history(self, bId):
        return
