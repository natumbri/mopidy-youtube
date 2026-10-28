from __future__ import annotations

import importlib
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mopidy_youtube import logger
from mopidy_youtube.cache import cache_image, cache_metadata, find_cached_audio_path
from mopidy_youtube.media import is_live_info

if TYPE_CHECKING:
    from types import ModuleType

    from mopidy_youtube.youtube import Video


def resolve_audio_url(  # noqa: PLR0913 - keyword-only API used by youtube.Video
    video: Video,
    *,
    ytdl_options: dict[str, Any],
    ytdl_extract_info_options: dict[str, Any],
    cache_location: Path | str | None,
    youtube_dl: ModuleType,
    youtube_dl_package: str,  # noqa: ARG001 - kept for the caller's keyword API
) -> str | None:
    if cache_location:
        cached_audio = find_cached_audio_path(cache_location, video.id)
        if cached_audio:
            return cached_audio

        with youtube_dl.YoutubeDL(ytdl_options) as ydl:
            probe_info = ydl.extract_info(
                **ytdl_extract_info_options,
                download=False,
            )

        if is_live_info(probe_info):
            logger.info(
                "Skipping YouTube live/upcoming playback resolution: %s",
                video.id,
            )
            return None

        logger.debug(f"caching track {video.id}")
        ytdl_options["outtmpl"] = str(Path(cache_location) / "%(id)s.%(ext)s")

        with youtube_dl.YoutubeDL(ytdl_options) as ydl:
            info = ydl.extract_info(
                **ytdl_extract_info_options,
                download=True,
            )

        if is_live_info(info):
            logger.info(
                "Skipping YouTube live/upcoming playback resolution: %s",
                video.id,
            )
            return None

        cache_image(video, cache_location)
        cache_metadata(video, cache_location, info)
        return None

    with youtube_dl.YoutubeDL(ytdl_options) as ydl:
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


def get_youtube_dl_module(package_name: str) -> tuple[ModuleType, str]:
    normalized_name = "yt_dlp" if package_name == "youtube_dl" else package_name
    module = importlib.import_module(normalized_name)
    return module, normalized_name
