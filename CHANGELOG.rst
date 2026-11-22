*********
Changelog
*********

Unreleased
========================================

- make failures say what failed: a missing step in a page is named (it was a bare ``KeyError``, which logged as ``error \"\"``), and caught exceptions are logged with their type
- download a track from the extraction that found it instead of extracting it a second time: caching an uncached track takes 8 requests and about 6 s instead of 13 and 9 s, so playback starts sooner
- stop a jAPI search loading the videos of every playlist it finds (15 requests that are mostly never used); a playlist loads its videos when it is opened
- look a jAPI playlist up with one request: its page also says what the playlist is
- fetch no more albums in a YouTube Music search than are shown (ytmusicapi answers in pages of 20) and keep them in the order of the search instead of the order in which the requests finished
- make autoplay with YouTube Music cost 4 requests instead of 24: the related songs are described by what the related-songs and watch-playlist lists already say (watch playlist tracks keep the length they come with), a length is only looked up for a video that is asked about, and the autoplayer tries its candidates in random order and stops at the first that fits instead of loading all of them
- fix the autoplay length limit, which never applied: lengths are in seconds but the limit was compared in milliseconds
- stop autoplay's log messages from loading the title of the current track
- stop ``Music`` reaching into ``Video`` and ``Playlist``: it returns data (playlists carry their tracks, and the answer to ``list_playlistitems`` describes the playlist), and the entities take it over; ``Music`` keeps the albums and playlists it fetched for an hour, so each is requested once, and no longer fetches the albums of related tracks that nobody opened
- number tracks from 1 everywhere (``Video.track_no`` used to count from 0 when it had to work the number out)
- deprecate the ``youtube_dl_package`` option: yt-dlp is a dependency and is imported directly (a configured value is ignored with a warning)
- write durations as canonical ISO 8601 (``PT3M45S``) straight from seconds instead of converting through several string forms
- use httpx instead of requests for all HTTP requests, with the same retries; ``requests`` is now only needed by the optional ``musicapi`` extra, because ytmusicapi requires it


v4.0.4 (2026-11-03)
========================================

- serve a track over http while it is caching and as a ``file://`` URI once caching is complete
- add Range/HEAD support to the cached audio handler and abort cleanly when a download stalls
- move packaging to ``pyproject.toml`` only; replace black/flake8/CircleCI with ruff, tox and GitHub Actions
- add type annotations throughout and check them with pyright; enable all ruff rules except a short list of deferred ones
- fix YouTube Music history updates, which never ran because of a wrong import path
- replace ``runtime.py``, the module-level mirrors and the class-level settings on ``Entry``/``Video``/``Playlist`` with one typed ``Context``
- give the api clients (``API``, ``jAPI``, ``Music``) their own session and executors instead of class-level state, declare the interface they share as the ``YouTubeApi`` protocol, and close them when the backend stops
- fix jAPI against the current YouTube site: related videos (and so autoplay), playlist items, channel playlists and playlist search results use the new ``lockupViewModel`` layout; also fix ``list_playlists`` failing for a missing playlist, ``run_search`` never ending on an empty response, page data containing ``};`` and the watch-page fallback breaking on a leading shelf
- fix several YouTube Music results: related tracks without an album, unavailable videos, audio playlists (``OLAK5uy_``) being returned under the wrong id, tracks without an album and artists without an id
- fix the cached track metadata, which could never be read back (the file used the key ``model`` where Mopidy expects ``__model__``); metadata cached by earlier versions is now read too, so cached tracks are looked up without asking the api
- make sure the data of a video or playlist always resolves: loaders that fail, an error response for a playlist, a thumbnail without a width, or a listing without a ``channelId`` no longer leave a caller waiting forever, and ``Video.artists`` no longer raises when the listing arrives first
- make every api return ``{"items": [...]}`` (never ``None`` or a list) when it has nothing to return, which also stops a failed ``jAPI`` playlist request from leaving ``Playlist.videos`` unresolved
- verify a configured YouTube Data API key properly (the old check could never fail) and fall back to jAPI when it is missing or rejected
- resolve audio in ``audio.py``: prefetching no longer delays a track that is about to be played, and a failed or interrupted resolution is retried instead of being remembered
- download to yt-dlp's ``.part`` file and serve it while it grows, so a truncated file is never mistaken for a complete one and an interrupted download resumes
- fix ``list_related_videos`` raising from its own error handler, and playlists in jAPI results reusing the previous playlist's thumbnail and channel title
- make ``Video.get`` / ``Playlist.get`` thread-safe and fix a crash in ``Playlist.load_info`` when the API call fails
- declare ``yt-dlp`` as a dependency, make ``ytmusicapi`` the ``musicapi`` extra and drop the unused ``beautifulsoup4`` and ``setuptools`` dependencies


v4.0.3 (2026-10-26)
========================================

- modernize the extension for Mopidy 4 and Python 3.13 only
- fix runtime queue/autoplay semantics and reduce blocking during track switching
- tighten actor and background-thread behavior around prefetch and media resolution
- harden API session handling and remove unnecessary executor churn
- streamline stale comments and ambiguous helper naming while keeping the code light


v4.0.2 (2024-05-04)
========================================

- fix Pydantic v2 model serialization keyword in cache metadata (use by_alias)
- fix compatibility with Mopidy 4.0
- improve compatibility with yt-dlp
- improve jAPI 
- improve detection of live tracks


v4.0.1
========================================


v4.0
========================================


v3.7 (2023-05-15)
========================================

- fix up various things that have gone to seed 
- remove tornado.gen.Task
- solve problem with caching while playing


v3.6 (2022-07-09)
========================================

- preload support for mopidy-tubeify


v3.5 (2021-12-20)
========================================

- changes


v3.4 (2021-04-11)
========================================

- youtube channel support
- tidy up autoplay
- fix some thumbnail stuff
- deprecate scrAPI and bs4API in favour of jAPI
- try to reduce trips to end points
- add caching (and related web client)


v3.3 (2021-04-11)
========================================

- revised backend and other fixes

v3.2 (2020-12-22)
========================================

- release to fix breaking changes and other minor bugs

v3.1 (2020-07-24)
========================================

- first python3 revision

v3.0 (2020-03-06)
========================================

- Initial python3 release.

v2.1.0 (TBA)
-------------------

- Last version that supports Mopidy 2.

- Last version in Python 2.7

- Major overhaul.

- Improved performance.

- Works with or without YouTube API key.

- Fixes many issues.

v2.0.2 (2016-01-19)
-------------------

- Fix resolving of ``youtube:video`` URIs when looking up tracks. (Fixes: #21,
  PR: #50)

- Ensure ``None`` doesn't get includes in track image lists. (PR: #48)

v2.0.1 (2015-08-19)
-------------------

- Update links to GitHub repository.

- Don't return ``None`` values to Mopidy when lookup or search returns invalid
  data. In Mopidy 1.0, this caused a crash. In Mopidy 1.1, this caused warnings
  about the YouTube backend returning invalid data. (Fixes: #28, PR: #35)
v2.0.0 (2015-04-01)
-------------------

- Require Mopidy >= 1.0.

- Update to work with the new playback API in Mopidy 1.0.

- Update to work with the new search API in Mopidy 1.0.

v1.0.2 (2015-01-02)
-------------------

- Changelog missing.

v1.0.1 (2014-05-28)
-------------------

- Changelog missing.

v0.1.0 (2014-03-06)
-------------------

- Initial release.
