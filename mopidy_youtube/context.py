"""Process-wide settings and clients shared by the whole extension.

The backend owns this state and fills it in when Mopidy starts it. It has to be
reachable from outside the backend actor too: the frontends and the tornado
handlers are separate Mopidy components that only receive `config` and `core`.
Keep everything that is shared here, rather than on the entity classes or in
module globals, so that there is exactly one place to look and to reset in tests.
"""

from __future__ import annotations

import importlib
import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from mopidy_youtube.apis import UnconfiguredApi, YouTubeApi

if TYPE_CHECKING:
    from pathlib import Path
    from types import ModuleType


def get_youtube_dl_module(package_name: str) -> tuple[ModuleType, str]:
    """Import yt-dlp (youtube-dl is an alias for it); return it and its name."""
    normalized_name = "yt_dlp" if package_name == "youtube_dl" else package_name
    return importlib.import_module(normalized_name), normalized_name


@dataclass
class Context:
    """Settings and clients shared by the backend, frontends and web handlers."""

    # the data api (jAPI, YouTube Data API or YouTube Music)
    api: YouTubeApi = field(default_factory=UnconfiguredApi)
    search_results: int = 15
    playlist_max_videos: int = 50
    http_port: int = 6680
    proxy: str | None = None
    channel: str | None = None
    cache_location: Path | None = None
    musicapi_enabled: bool = False
    musicapi_cookiefile: str | None = None
    musicapi_browser_authentication_file: str | None = None
    youtube_dl_package: str = "yt_dlp"
    # ids of videos added by the autoplayer, shared with the history listener
    autoplayed: list[str] = field(default_factory=list)

    _youtube_dl: ModuleType | None = field(default=None, repr=False)
    _youtube_dl_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _search_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _search_in_progress: bool = field(default=False, repr=False)

    def reset(self) -> None:
        """Restore the defaults (for tests)."""
        self.__dict__.update(Context().__dict__)

    def youtube_dl(self) -> ModuleType:
        """Return the yt-dlp (or youtube-dl) module, importing it on first use."""
        with self._youtube_dl_lock:
            if self._youtube_dl is None:
                self._youtube_dl, self.youtube_dl_package = get_youtube_dl_module(
                    self.youtube_dl_package
                )
            return self._youtube_dl

    def begin_search(self) -> bool:
        """Claim the (single) search slot; return False if a search is running."""
        with self._search_lock:
            if self._search_in_progress:
                return False
            self._search_in_progress = True
            return True

    def end_search(self) -> None:
        with self._search_lock:
            self._search_in_progress = False


context = Context()
