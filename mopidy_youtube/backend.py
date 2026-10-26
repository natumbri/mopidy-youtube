import json

import pykka
from mopidy import backend, httpclient

from mopidy_youtube import Extension, logger, youtube
from mopidy_youtube import runtime
from mopidy_youtube.apis import youtube_japi
from mopidy_youtube.listener import YouTubeAddToHistoryListener, YouTubeCoreListener
from mopidy_youtube.library import YouTubeLibraryProvider
from mopidy_youtube.playback import YouTubePlaybackProvider


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
    def __init__(self, config, audio):
        super().__init__()
        self.config = config
        self.library = YouTubeLibraryProvider(backend=self)
        self.playback = YouTubePlaybackProvider(audio=audio, backend=self)

        youtube_config = config["youtube"]
        self._configure_youtube_api(youtube_config)
        self._configure_music_api(youtube_config)
        self._configure_limits(youtube_config)

        runtime.channel = youtube_config["channel_id"]
        youtube.channel = youtube_config["channel_id"]
        youtube.Video.http_port = config["http"]["port"]
        runtime.youtube_dl_package = youtube_config["youtube_dl_package"]
        youtube.youtube_dl_package = youtube_config["youtube_dl_package"]
        self.uri_schemes = ("youtube", "yt")
        self.user_agent = f"{Extension.dist_name}/{Extension.version}"

    def _configure_limits(self, youtube_config):
        youtube.Video.search_results = max(1, int(youtube_config["search_results"]))
        youtube.Playlist.playlist_max_videos = max(
            1, int(youtube_config["playlist_max_videos"])
        )

    def _configure_youtube_api(self, youtube_config):
        runtime.api_enabled = bool(youtube_config["api_enabled"])
        if not runtime.api_enabled:
            return

        global youtube_api
        from mopidy_youtube.apis import youtube_api

        try:
            youtube_api.API.youtube_api_key = youtube_config["youtube_api_key"]
        except Exception as e:
            logger.error(f"No YouTube API key provided, disabling API: {e}")
            runtime.api_enabled = False

    def _configure_music_api(self, youtube_config):
        runtime.musicapi_enabled = bool(youtube_config["musicapi_enabled"])
        if not runtime.musicapi_enabled:
            return

        global youtube_music
        from mopidy_youtube.apis import youtube_music

        youtube.musicapi_browser_authentication_file = youtube_config.get(
            "musicapi_browser_authentication_file"
        )
        runtime.musicapi_cookiefile = youtube_config.get("musicapi_cookiefile")
        youtube_music.own_channel_id = runtime.channel

    def on_start(self):
        youtube_config = self.config["youtube"]
        proxy = httpclient.format_proxy(self.config["proxy"])
        youtube.Video.proxy = proxy
        headers = {
            "user-agent": httpclient.format_user_agent(self.user_agent),
            "Cookie": "PREF=hl=en; CONSENT=YES+20210329;",
            "Accept-Language": "en;q=0.8",
        }

        if youtube_config["allow_cache"]:
            runtime.cache_location = Extension.get_cache_dir(self.config)
            youtube.cache_location = runtime.cache_location
            logger.info(f"file caching enabled (at {runtime.cache_location})")
        else:
            runtime.cache_location = None
            youtube.cache_location = None
            logger.info("file caching not enabled")

        if runtime.api_enabled:
            youtube.Entry.api = youtube_api.API(proxy, headers)
            if youtube.Entry.search(q="test") is None:
                logger.error("Failed to verify YouTube API key, disabling API")
                runtime.api_enabled = False
            else:
                logger.info("YouTube API key verified")

        if not runtime.api_enabled:
            logger.info("using jAPI")
            youtube.Entry.api = youtube_japi.jAPI(proxy, headers)

        if runtime.musicapi_enabled:
            logger.info("Using YouTube Music API")

            if youtube.musicapi_browser_authentication_file:
                logger.info(
                    f"Reading cookies from {youtube.musicapi_browser_authentication_file}"
                )
                with open(
                    youtube.musicapi_browser_authentication_file,
                    encoding="utf-8",
                ) as browser_authentication_file:
                    headers = json.load(browser_authentication_file)

            youtube.Entry.api = youtube_music.Music(proxy, headers)

    def add_track_to_history(self, bId):
        """Best-effort history update for a track already played."""

        logger.debug(f"adding {bId} to history")

        try:
            from mopidy_youtube import youtube_music
        except Exception as e:
            logger.debug(
                f"youtube_music import unavailable, skipping history for {bId}: {e}"
            )
            return

        try:
            ytmusic = getattr(youtube_music, "ytmusic", None)
            if ytmusic is None:
                logger.debug(f"ytmusic client unavailable, skipping history for {bId}")
                return

            song = ytmusic.get_song(bId)  # , signatureTimestamp)
            ytmusic.add_history_item(song)  # may fail if s.youtube.com is blocked
        except Exception as e:
            logger.warning(f"failed to add {bId} to YouTube history: {e}")
