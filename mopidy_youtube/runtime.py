from __future__ import annotations

import threading

api_enabled = False
channel = None
cache_location = None
musicapi_enabled = None
musicapi_cookiefile = None
youtube_dl = None
youtube_dl_package = "yt_dlp"
autoplayed = []
search_lock = threading.Lock()
search_in_progress = False
search_last_started = 0.0
