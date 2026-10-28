from typing import TypedDict


class YouTubeConfig(TypedDict):
    enabled: bool
    allow_cache: bool | None
    youtube_api_key: str | None
    search_results: int
    playlist_max_videos: int
    api_enabled: bool | None
    channel_id: str | None
    musicapi_enabled: bool | None
    musicapi_cookie: str | None
    musicapi_browser_authentication_file: str | None
    musicapi_cookiefile: str | None
    history_enabled: bool | None
    autoplay_enabled: bool | None
    strict_autoplay: bool | None
    max_autoplay_length: int | None
    max_degrees_of_separation: int
    youtube_dl_package: str | None
