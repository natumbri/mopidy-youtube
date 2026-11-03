"""Resolve the audio of a video: a cached file, a growing download or a direct url."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from mopidy_youtube import logger
from mopidy_youtube.async_utils import set_once
from mopidy_youtube.context import context
from mopidy_youtube.resolver import resolve_audio_url

if TYPE_CHECKING:
    from mopidy_youtube.youtube import Video

# Start serving a download once this much of it has been cached.
EARLY_START_PERCENT = 2
# Only webm is served while it is still being written: other containers (m4a, mp4)
# need the end of the file before they can start, so they wait for the download.
STREAMABLE_SUFFIXES = frozenset({".webm"})


class AudioResolver:
    """Resolve the audio url of one video and publish it on its `audio_url` future.

    If caching is on and the track is cached, the url points at the cached file. If
    it isn't cached, the track is downloaded and, once `EARLY_START_PERCENT` of it
    has been written, an http url served by `web.AudioHandler` is published so
    playback can start. If caching is off, the url comes straight from yt-dlp.
    """

    def __init__(self, video: Video) -> None:
        self.video = video
        self._published = False

    def run(self) -> None:
        ytdl = context.youtube_dl()
        logger.debug(f"using {context.youtube_dl_package} package for youtube_dl")

        options: dict[str, Any] = {
            "format": "bestaudio/ogg/mp3/m4a/best",
            "proxy": context.proxy,
            "cachedir": False,
            "retries": 10,
            "progress_hooks": [self.on_progress],
        }
        if context.musicapi_cookiefile:
            options["cookiefile"] = context.musicapi_cookiefile
        if context.youtube_dl_package == "yt_dlp":
            options["no_color"] = True

        # High quality music streams are only available to YouTube Premium users
        # when using YouTube Music.
        base_url = (
            "https://music.youtube.com"
            if context.musicapi_enabled
            else "https://www.youtube.com"
        )
        extract_options: dict[str, Any] = {
            "url": f"{base_url}/watch?v={self.video.id}",
            "ie_key": None,
            "extra_info": {},
            "process": True,
            "force_generic_extractor": False,
        }

        resolved = resolve_audio_url(
            self.video,
            ytdl_options=options,
            ytdl_extract_info_options=extract_options,
            cache_location=context.cache_location,
            youtube_dl=ytdl,
        )
        self._publish(resolved)

    def on_progress(self, d: dict[str, Any]) -> None:
        """yt-dlp progress hook: publish the url as early as it is playable."""
        filename = Path(d["filename"])

        if d["status"] == "finished":
            # The file is complete (yt-dlp only renames it from `.part` now), so
            # later requests can use it directly instead of going through tornado.
            self.video.cached_file_uri = f"file://{filename}"
            self.video.total_bytes = filename.stat().st_size
            self._publish(self.video.cached_file_uri)
            return

        if d["status"] != "downloading" or self._published:
            return

        total = d.get("total_bytes") or d["info_dict"].get("filesize") or 0
        percent = d.get("downloaded_bytes", 0) * 100 / total if total else 0
        logger.debug(f"percent cached: {percent:.1f}%, {filename.name}")

        # An exact size is needed for the Content-Length of the http response.
        if percent > EARLY_START_PERCENT and filename.suffix in STREAMABLE_SUFFIXES:
            self.video.total_bytes = total
            http_uri = f"http://localhost:{context.http_port}/youtube/{filename.name}"
            logger.debug(f"setting cached audio_url: {http_uri} ({total} bytes)")
            self._publish(http_uri)

    def _publish(self, url: str | None) -> None:
        if url is not None and set_once(self.video._audio_url, url):
            self._published = True
