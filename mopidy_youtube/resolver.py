from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import yt_dlp

from mopidy_youtube import logger
from mopidy_youtube.cache import cache_image, cache_metadata, find_cached_audio_path
from mopidy_youtube.media import is_live_info

if TYPE_CHECKING:
    from mopidy_youtube.youtube import Video


def _youtube_dl(options: dict[str, Any]) -> yt_dlp.YoutubeDL:
    # yt-dlp types its options as a private TypedDict; ours are built dynamically
    return yt_dlp.YoutubeDL(cast("Any", options))


def resolve_audio_url(
    video: Video,
    *,
    ytdl_options: dict[str, Any],
    ytdl_extract_info_options: dict[str, Any],
    cache_location: Path | str | None,
) -> str | None:
    if cache_location:
        cached_audio = find_cached_audio_path(cache_location, video.id)
        if cached_audio:
            return cached_audio

        options = {
            **ytdl_options,
            "outtmpl": str(Path(cache_location) / "%(id)s.%(ext)s"),
        }
        with _youtube_dl(options) as ydl:
            info = ydl.extract_info(**ytdl_extract_info_options, download=False)

            if is_live_info(info):
                logger.info(
                    "Skipping YouTube live/upcoming playback resolution: %s",
                    video.id,
                )
                return None

            # Extracting is most of what it costs to find out about a video: download
            # what was extracted instead of extracting it all over again.
            logger.debug(f"caching track {video.id}")
            downloaded = ydl.process_ie_result(info, download=True)

        cache_image(video, cache_location)
        cache_metadata(
            video, cache_location, cast("dict[str, Any]", downloaded or info)
        )
        return None

    with _youtube_dl(ytdl_options) as ydl:
        info = ydl.extract_info(
            **ytdl_extract_info_options,
            download=False,
        )

    audio_url = video._extract_audio_url(info)
    if not audio_url:
        logger.warning(
            "yt-dlp did not provide a direct audio URL for %s; info keys: %s",
            video.id,
            sorted(info.keys()) if isinstance(info, dict) else type(info).__name__,
        )
        return None

    return audio_url
