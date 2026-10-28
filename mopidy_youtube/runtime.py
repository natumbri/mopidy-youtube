from __future__ import annotations

import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path
    from types import ModuleType

api_enabled: bool = False
channel: str | None = None
cache_location: Path | None = None
musicapi_enabled: bool | None = None
musicapi_cookiefile: str | None = None
youtube_dl: ModuleType | None = None
youtube_dl_package: str = "yt_dlp"
autoplayed: list[str] = []
search_lock = threading.Lock()
search_in_progress: bool = False
search_last_started: float = 0.0
