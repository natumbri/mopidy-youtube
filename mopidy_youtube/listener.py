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
            tl_tracks = self.core.tracklist.get_tl_tracks().get()
            current = self.core.playback.get_current_tl_track().get()
        except Exception:
            logger.exception("Failed to load tracklist while prefetching YouTube audio")
            return

        start = 0
        if current is not None:
            for i, tl_track in enumerate(tl_tracks):
                if tl_track.tlid == current.tlid:
                    start = i
                    break

        video_ids = [
            extract_video_id(t.track.uri)
            for t in tl_tracks[start : start + self._prefetch_limit]
            if t.track.uri.startswith(("youtube:video:", "yt:video:"))
        ]

        for video_id in video_ids:
            if not video_id:
                continue
            try:
                youtube.Video.get(video_id).audio_url
            except Exception:
                logger.exception(
                    "Failed to prefetch audio for YouTube video %s", video_id
                )

    def track_playback_started(self, tl_track):
        # advance the window as playback moves
        self.get_prefetch_executor().submit(self._prefetch_youtube_audio)

    def tracklist_changed(self):
        # Keep the actor callback lightweight and move the expensive prefetch work
        # to the shared background executor instead of blocking Mopidy's actor loop.
        self.get_prefetch_executor().submit(self._prefetch_youtube_audio)

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
