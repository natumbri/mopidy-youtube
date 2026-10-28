from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, cast, override

import pykka
from mopidy import backend, httpclient
from mopidy.types import UriScheme

from mopidy_youtube import Extension, logger, youtube
from mopidy_youtube.apis import youtube_api, youtube_japi
from mopidy_youtube.context import context
from mopidy_youtube.library import YouTubeLibraryProvider
from mopidy_youtube.listener import YouTubeAddToHistoryListener
from mopidy_youtube.playback import YouTubePlaybackProvider

if TYPE_CHECKING:
    from mopidy.audio import AudioProxy
    from mopidy.config import Config

    from mopidy_youtube.types import YouTubeConfig

"""
A typical interaction:
1. User searches for a keyword (YouTubeLibraryProvider.search)
2. User adds a track to the queue (YouTubeLibraryProvider.lookup)
3. User plays a track from the queue (YouTubePlaybackProvider.translate_uri)
step 1 requires only 2 API calls. Data for the next steps are loaded in the
background, so steps 2/3 are usually instantaneous.
"""


class YouTubeBackend(
    pykka.ThreadingActor, backend.Backend, YouTubeAddToHistoryListener
):
    uri_schemes: ClassVar[list[UriScheme]] = [UriScheme("youtube"), UriScheme("yt")]

    def __init__(self, config: Config, audio: AudioProxy) -> None:
        super().__init__()
        self.config = config
        self.library = YouTubeLibraryProvider(backend=self)
        self.playback = YouTubePlaybackProvider(audio=audio, backend=self)
        self.user_agent = f"{Extension.dist_name}/{Extension.version}"

        youtube_config = cast("YouTubeConfig", config["youtube"])
        self._api_enabled = bool(youtube_config["api_enabled"])
        self._youtube_api_key = youtube_config["youtube_api_key"]

        context.search_results = max(1, int(youtube_config["search_results"]))
        context.playlist_max_videos = max(1, int(youtube_config["playlist_max_videos"]))
        context.channel = youtube_config["channel_id"]
        context.http_port = config["http"]["port"]
        context.youtube_dl_package = youtube_config["youtube_dl_package"] or "yt_dlp"
        context.musicapi_enabled = bool(youtube_config["musicapi_enabled"])
        if context.musicapi_enabled:
            context.musicapi_browser_authentication_file = youtube_config[
                "musicapi_browser_authentication_file"
            ]
            context.musicapi_cookiefile = youtube_config["musicapi_cookiefile"]

    @override
    def on_start(self) -> None:
        proxy = httpclient.format_proxy(self.config["proxy"])
        context.proxy = proxy
        headers = {
            "user-agent": httpclient.format_user_agent(self.user_agent),
            "Cookie": "PREF=hl=en; CONSENT=YES+20210329;",
            "Accept-Language": "en;q=0.8",
        }

        youtube_config = cast("YouTubeConfig", self.config["youtube"])
        if youtube_config["allow_cache"]:
            context.cache_location = Extension.get_cache_dir(self.config)
            logger.info(f"file caching enabled (at {context.cache_location})")
        else:
            context.cache_location = None
            logger.info("file caching not enabled")

        if self._api_enabled:
            self._start_youtube_api(proxy, headers)
        if not self._api_enabled:
            logger.info("using jAPI")
            context.api = youtube_japi.jAPI(proxy, headers)

        if context.musicapi_enabled:
            self._start_music_api(proxy, headers)

    def _start_youtube_api(self, proxy: str | None, headers: dict[str, str]) -> None:
        try:
            youtube_api.API.youtube_api_key = self._youtube_api_key
        except Exception as e:
            logger.error(f"No YouTube API key provided, disabling API: {e}")
            self._api_enabled = False
            return

        context.api = youtube_api.API(proxy, headers)
        if youtube.Entry.search(q="test") is None:
            logger.error("Failed to verify YouTube API key, disabling API")
            self._api_enabled = False
        else:
            logger.info("YouTube API key verified")

    def _start_music_api(self, proxy: str | None, headers: dict[str, str]) -> None:
        # ytmusicapi is an optional dependency (the `musicapi` extra)
        from mopidy_youtube.apis import youtube_music  # noqa: PLC0415

        logger.info("Using YouTube Music API")

        authentication_file = context.musicapi_browser_authentication_file
        if authentication_file:
            logger.info(f"Reading cookies from {authentication_file}")
            with Path(authentication_file).open(encoding="utf-8") as file:
                headers = json.load(file)

        context.api = youtube_music.Music(proxy, headers)

    def add_track_to_history(self, bId: str) -> None:
        """Best-effort history update for a track already played."""

        logger.debug(f"adding {bId} to history")

        try:
            from mopidy_youtube.apis import youtube_music  # noqa: PLC0415
        except Exception as e:
            logger.debug(
                f"youtube_music import unavailable, skipping history for {bId}: {e}"
            )
            return

        try:
            ytmusic = youtube_music.Music.client()
            if ytmusic is None:
                logger.debug(f"ytmusic client unavailable, skipping history for {bId}")
                return

            song = ytmusic.get_song(bId)  # , signatureTimestamp)
            ytmusic.add_history_item(song)  # may fail if s.youtube.com is blocked
        except Exception as e:
            logger.warning(f"failed to add {bId} to YouTube history: {e}")
