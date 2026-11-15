from __future__ import annotations

import copy
import json
import threading
from concurrent.futures import as_completed
from itertools import repeat
from typing import TYPE_CHECKING, Any, override

import requests
from cachetools import TTLCache
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from ytmusicapi import YTMusic

from mopidy_youtube import logger
from mopidy_youtube.apis.client import Client
from mopidy_youtube.apis.json_paths import YTM_ERROR_THUMBNAIL_PATH, traverse
from mopidy_youtube.apis.ytm_item_to_video import ytm_item_to_video
from mopidy_youtube.context import context

if TYPE_CHECKING:
    from collections.abc import Callable, Collection

    from mopidy_youtube.apis import YouTubeApi


# albums and playlists stay in memory for this long, so that a playlist that has
# been searched for or listed is not fetched again when its videos are loaded
CONTENT_TTL = 3600
CONTENT_MAX = 128


# Access to YouTube Music API through ytmusicapi package
# https://github.com/sigma67/ytmusicapi


class Music(Client):
    def __init__(
        self,
        proxy: str | None,
        headers: dict[str, str],
        fallback: YouTubeApi,
    ) -> None:
        super().__init__(proxy, headers)
        # used when YouTube Music returns too few related videos
        self.fallback = fallback
        self._content: TTLCache[Any, Any] = TTLCache(
            maxsize=CONTENT_MAX, ttl=CONTENT_TTL
        )
        self._content_lock = threading.Lock()
        self._fetching: dict[tuple[str, str], threading.Lock] = {}
        auth = (
            None
            if headers.get("Cookie") == "PREF=hl=en; CONSENT=YES+20210329;"
            else json.dumps(headers)
        )
        # ytmusicapi only works with a requests session
        self.ytmusic_session = self._create_ytmusic_session(proxy, headers)
        try:
            self.ytmusic = YTMusic(auth=auth, requests_session=self.ytmusic_session)
        except Exception as e:
            logger.error("YTMusic init error: %s", str(e))
            self.ytmusic = YTMusic()

    @staticmethod
    def _create_ytmusic_session(
        proxy: str | None, headers: dict[str, str]
    ) -> requests.Session:
        session = requests.Session()
        if proxy:
            session.proxies.update({"http": proxy, "https": proxy})
        session.headers.update(headers)
        adapter = HTTPAdapter(
            max_retries=Retry(
                total=3,
                backoff_factor=0.3,
                status_forcelist=(500, 502, 503, 504),
                respect_retry_after_header=True,
            )
        )
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    @override
    def close(self) -> None:
        super().close()
        self.ytmusic_session.close()

    def search(self, q: str) -> dict[str, Any]:
        """
        search for both songs and albums
        """

        search_functions = [self.search_albums, self.search_songs]
        executor = self.executor

        futures = executor.map(lambda x, y: x(y), search_functions, repeat(q))
        result = [
            item for values in futures for item in values[: context.search_results]
        ]

        return json.loads(json.dumps({"items": result}))

    def list_related_videos(self, video_id: str) -> dict[str, Any]:
        """
        returns related videos for a given video_id
        """

        get_watch_playlist: dict[str, Any] = {}
        related_browse_id = "none"

        try:
            logger.debug(
                f"youtube_music list_related_videos triggered "
                f"ytmusic.get_watch_playlist: {video_id}"
            )

            get_watch_playlist = self.ytmusic.get_watch_playlist(video_id)
            related_browse_id = get_watch_playlist.get("related", "none")

        except Exception as e:
            logger.error(
                f"youtube_music list_related_videos get_watch_playlist "
                f"error:{e}. videoId: {video_id}"
            )

        # The songs are described by what the lists of related songs and of the
        # watch playlist say about them. Neither is complete: the related songs have
        # no length, which is left to be looked up for the few that are used (see
        # `list_videos`), and the watch playlist's tracks have no album.
        tracks: list[dict[str, Any]] = []
        try:
            logger.debug(
                f"youtube_music list_related_videos triggered "
                f"ytmusic.get_song_related ({related_browse_id})"
            )
            related_tracks = self.ytmusic.get_song_related(related_browse_id)[0][
                "contents"
            ]
            tracks = [
                ytm_item_to_video(track, allow_unknown_duration=True)
                for track in related_tracks
                if track.get("videoId") is not None
            ]
        except Exception as e:
            logger.error(
                f"youtube_music list_related_videos error:{e} "
                f"Related_browseId: {related_browse_id}"
            )

        if len(tracks) < 10:
            logger.warning(
                f"get_song_related returned {len(tracks)} tracks. "
                f"Trying get_watch_playlist['tracks'] for more"
            )
            try:
                tracks.extend(
                    self._watch_track_to_video(track)
                    for track in get_watch_playlist["tracks"]
                    if track.get("videoId") is not None
                )
            except Exception as e:
                logger.error(f"youtube_music list_related_videos error:{e}")

        # sometimes, self.ytmusic.get_watch_playlist seems to return very few, or even
        # only one, related video, which may be the original video, itself.  If this
        # happens, get related videos using the jAPI.
        if len(tracks) < 10:
            logger.warning(
                f"get_song_related and get_watch_playlist only returned "
                f"{len(tracks)} tracks. Trying the fallback api's list_related_videos"
            )
            japi_related_videos = self.fallback.list_related_videos(video_id)
            tracks.extend(japi_related_videos["items"])

        logger.debug(
            f"youtube_music list_related_videos returned {len(tracks)} tracks."
        )

        return json.loads(json.dumps({"items": tracks}, sort_keys=False, indent=1))

    @staticmethod
    def _watch_track_to_video(track: dict[str, Any]) -> dict[str, Any]:
        """A track of a watch playlist: it has a length, and thumbnails as a list."""
        track = dict(track)
        if isinstance(track.get("thumbnail"), list):
            track["thumbnails"] = track.pop("thumbnail")
        return ytm_item_to_video(track, allow_unknown_duration=True)

    def list_videos(self, ids: list[str]) -> dict[str, Any]:
        """List videos by fetching each requested item individually."""
        logger.debug(
            f"youtube_music list_videos triggered ytmusic.get_song x {len(ids)}: {ids}"
        )

        executor = self.executor
        futures = executor.map(self.ytmusic.get_song, ids)
        # keep each response together with the id that was asked for
        requested = [
            (video_id, value)
            for video_id, value in zip(ids, futures, strict=True)
            if value is not None
        ]
        results = [value for _, value in requested]

        for video_id, result in requested:
            if result["playabilityStatus"]["status"] == "ERROR":
                result["title"] = result["playabilityStatus"]["reason"]
                result["lengthMs"] = 0
                result["channel"] = result["playabilityStatus"]["reason"]
                # contextParams does not contain the video id
                result["videoId"] = video_id
                result["thumbnail"] = {
                    "thumbnails": [
                        {
                            "url": "https:"
                            + traverse(result, YTM_ERROR_THUMBNAIL_PATH)["url"],
                            "width": traverse(result, YTM_ERROR_THUMBNAIL_PATH)[
                                "width"
                            ],
                            "height": traverse(result, YTM_ERROR_THUMBNAIL_PATH)[
                                "height"
                            ],
                        }
                    ]
                }

        [
            video.update({"thumbnails": video["thumbnail"]["thumbnails"]})
            for video in results
            if "thumbnail" in video
        ]

        try:
            items = [ytm_item_to_video(result) for result in results]
        except Exception as e:
            logger.error(
                f"youtube_music list_videos ytm_item_to_video error {e}: {results}"
            )
            return {"items": []}

        [
            item.update({"id": item["id"]["videoId"]})
            for item in items
            if "videoId" in item["id"]
        ]

        return json.loads(json.dumps({"items": items}, sort_keys=False, indent=1))

    def list_playlists(self, ids: Collection[str]) -> dict[str, Any]:
        """
        list playlists
        """

        results = []

        logger.debug(
            f"youtube_music list_playlists triggered "
            f"_get_playlist_or_album x {len(ids)}: {ids}"
        )

        executor = self.executor
        futures = {
            executor.submit(self._get_playlist_or_album, playlist_id): playlist_id
            for playlist_id in ids
        }
        for future in as_completed(futures):
            try:
                result = future.result()
                if result:
                    # callers look the result up by the id they asked for, which
                    # differs from the resolved id for an OLAK5uy_ audio playlist
                    result["playlistId"] = futures[future]
                results.append(result)
            except Exception as e:
                logger.error(
                    f"youtube_music list_playlists "
                    f"_get_playlist_or_album {e}, {futures[future]}"
                )

        if len(results) == 0:
            logger.debug(f"list_playlists for {ids} returned no results")
            return {"items": []}

        # these the playlists that are returned, each with its tracks so that nobody
        # has to ask for them again
        items = [self.yt_listitem_to_playlist(result) for result in results if result]
        for item in items:
            item["id"] = item["id"]["playlistId"]

        return json.loads(json.dumps({"items": items}, sort_keys=False, indent=1))

    def list_playlistitems(
        self,
        playlist_id: str,
        page: str | None,  # noqa: ARG002 - the whole playlist is returned at once
        max_results: int,
    ) -> dict[str, Any]:
        logger.debug(f"youtube_music list_playlistitems for playlist {playlist_id}")

        result = self._get_playlist_or_album(playlist_id)
        if not result:
            return {"items": []}

        result["playlistId"] = playlist_id
        playlist = self.yt_listitem_to_playlist(result)

        items = [
            track for track in playlist["tracks"] if track["id"]["videoId"] is not None
        ]

        [
            item.update({"id": item["id"]["videoId"]})
            for item in items
            if "videoId" in item["id"]
        ]

        items = items[:max_results]
        # the playlist itself comes with its items: what the caller needs to know
        # about it is not asked for again
        details = {key: value for key, value in playlist.items() if key != "tracks"}
        return json.loads(
            json.dumps(
                {"nextPageToken": None, "playlist": details, "items": items},
                sort_keys=False,
                indent=1,
            )
        )

    def list_channelplaylists(self, channel_id: str | None) -> dict[str, Any]:
        results = []
        channel_title = None
        # first check if the channel is a proper artist channel, in which case, return
        # albums (and playlists?)
        try:
            target_channel_id = channel_id or context.channel
            # None is rejected by ytmusicapi and handled by the except below
            artist = self.ytmusic.get_artist(
                target_channel_id  # pyright: ignore[reportArgumentType]
            )
            browse_id = artist["albums"]["browseId"]
            params = artist["albums"]["params"]
            channel_title = artist["name"]
            results = self.ytmusic.get_artist_albums(browse_id, params)
        except Exception as e:
            logger.debug(f"youtube_music.list_channelplaylists exception {e}")
            # if channel_id is None or own_channel_id then try to retrieve
            # public and private playlists
            if channel_id in (None, context.channel):
                try:
                    logger.debug(
                        f"youtube_music list_channelplaylists triggered "
                        f"ytmusic.get_library_playlists and "
                        f"ytmusic.get_library_albums: {channel_id}"
                    )
                    results = self.ytmusic.get_library_playlists()
                    albums = self.ytmusic.get_library_albums()
                    # their videos are loaded next: fetch the albums in parallel now
                    self.process_albums(albums)
                    results.extend(albums)
                    if channel_id:
                        logger.debug(
                            f"youtube_music list_channelplaylists triggered "
                            f"ytmusic.get_user: {channel_id}"
                        )
                        channel_title = self.ytmusic.get_user(channel_id)["name"]
                    else:
                        channel_title = "unknown"

                except Exception as e:
                    logger.debug(f"youtube_music.list_channelplaylists exception {e}")

                    if channel_id:
                        logger.debug(
                            f"youtube_music list_channelplaylists triggered "
                            f"ytmusic.get_user: {channel_id}"
                        )
                        user = self.ytmusic.get_user(channel_id)
                        results = user["playlists"]["results"]
                        channel_title = user["name"]

            else:
                # if channel_id is not None and not own_channel_id
                # retrieve only public playlists:
                logger.debug(
                    f"youtube_music list_channelplaylists triggered "
                    f"ytmusic.get_user: {channel_id}"
                )
                try:
                    user = self.ytmusic.get_user(channel_id)
                    results = user["playlists"]["results"]
                    channel_title = user["name"]
                except Exception:
                    logger.debug(
                        f"youtube_music list_channelplaylists triggered "
                        f"ytmusic.get_artist: {channel_id}"
                    )
                    user = self.ytmusic.get_artist(channel_id)
                    results = user["albums"]["results"]
                    channel_title = user["name"]

        [
            item.setdefault("playlistId", item["browseId"])
            for item in results
            if "browseId" in item
        ]

        items = [
            self.yt_listitem_to_playlist(item, channel_title)
            for item in results
            if item["playlistId"] != "LM"
        ]
        [item.update({"id": item["id"]["playlistId"]}) for item in items]
        return json.loads(json.dumps({"items": items}, sort_keys=False, indent=1))

    # methods below are mostly internal, for use by the api methods above (which
    # replicate the methods from the youtube API)

    def search_songs(self, q: str) -> list[dict[str, Any]]:
        logger.debug(f"youtube_music search_songs triggered ytmusic.search: {q}")
        results = self.ytmusic.search(
            query=q, filter="songs", limit=context.search_results
        )

        return [
            ytm_item_to_video(track)
            for track in results
            if track["videoId"] is not None
        ]

    def search_albums(self, q: str) -> list[dict[str, Any]]:
        logger.debug(f"youtube_music search_albums triggered ytmusic.search: {q}")

        results = self.ytmusic.search(
            query=q, filter="albums", limit=context.search_results
        )
        return self.process_albums(results)

    def process_albums(self, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        albums = []

        def job(result: dict[str, Any]) -> dict[str, Any]:
            # the album itself is needed to get the number of tracks
            ytmusic_album = self._album(result["browseId"])
            ytmusic_album.update({"playlistId": result["browseId"]})
            return self.yt_listitem_to_playlist(ytmusic_album)

        executor = self.executor
        futures = {executor.submit(job, result): result for result in results}
        for future in as_completed(futures):
            try:
                albums.append(future.result())
            except Exception as e:
                logger.error(
                    "youtube_music process_albums get_album error "
                    f"{e}, {futures[future]}"
                )

        # the albums carry their tracks, which the entities take over from here
        return albums

    @staticmethod
    def yt_listitem_to_playlist(
        item: dict[str, Any], channel_title: str | None = None
    ) -> dict[str, Any]:
        try:
            playlist_id = item["playlistId"]
        except Exception as e:
            logger.error(f"yt_listitem_to_playlist, no playlistId: {item}, {e}")
            playlist_id = None  # or should it just stop and return?

        if "count" in item:
            item_count = int(item["count"].replace(",", ""))
        else:
            item_count = item.get("trackCount", "0")

        if item.get("artists"):
            if isinstance(item["artists"], list):
                channel_title = item["artists"][0]["name"]
            else:
                channel_title = item["artists"]

        playlist = {
            "id": {"kind": "youtube#playlist", "playlistId": playlist_id},
            "snippet": {
                "title": item.get("title", "Unknown"),
                "resourceId": {"playlistId": item["playlistId"]},
                "thumbnails": {"default": item["thumbnails"][-1]},
                "channelTitle": channel_title,
            },
            "contentDetails": {"itemCount": item_count},
            "artists": item.get("artists"),
        }
        if "tracks" in item:
            fields = ["artists", "thumbnails"]
            [
                track.update({field: item[field]})
                for field in fields
                for track in item["tracks"]
                if track[field] is None
            ]

            if (
                item.get("type") == "Album"
            ):  # there may be other "types" for which this works? "EP"? "Single"?
                [
                    track.update({"track_no": (number)})
                    for number, track in enumerate(item["tracks"], 1)
                ]

            if "title" in item and "playlistId" in item:
                [
                    track.update(
                        {
                            "album": {
                                "name": item["title"],
                                "id": item["playlistId"],
                            }
                        }
                    )
                    for track in item["tracks"]
                    if "album" not in track
                    or isinstance(track["album"], str)
                    or track["album"] is None
                ]

            playlist["tracks"] = [
                ytm_item_to_video(track)
                for track in item["tracks"]
                if track["videoId"] is not None
            ]

        return playlist

    def _cached(self, key: tuple[str, str], fetch: Callable[[], Any]) -> Any:
        """Fetch something once: concurrent and later requests share the result.

        Callers get their own copy, because they add to what they are given.
        """
        with self._content_lock:
            if key in self._content:
                return copy.deepcopy(self._content[key])
            fetching = self._fetching.setdefault(key, threading.Lock())
        with fetching:
            with self._content_lock:
                if key in self._content:
                    return copy.deepcopy(self._content[key])
            value = fetch()  # a failure is not remembered
            with self._content_lock:
                self._content[key] = value
                self._fetching.pop(key, None)
        return copy.deepcopy(value)

    def _album(self, browse_id: str) -> dict[str, Any]:
        def fetch() -> dict[str, Any]:
            logger.debug(f"youtube_music triggered ytmusic.get_album: {browse_id}")
            return self.ytmusic.get_album(browse_id)

        return self._cached(("album", browse_id), fetch)

    def _playlist(self, playlist_id: str) -> dict[str, Any]:
        def fetch() -> dict[str, Any]:
            logger.debug(f"youtube_music triggered ytmusic.get_playlist: {playlist_id}")
            return self.ytmusic.get_playlist(playlist_id)

        return self._cached(("playlist", playlist_id), fetch)

    def _album_browse_id(self, audio_playlist_id: str) -> str:
        """The browse id of the album of an `OLAK5uy_` audio playlist."""

        def fetch() -> str:
            logger.debug(
                "youtube_music triggered ytmusic.get_album_browse_id: "
                f"{audio_playlist_id}"
            )
            browse_id = YTMusic.get_album_browse_id(self.ytmusic, audio_playlist_id)
            if browse_id is None:
                msg = f"no album for audio playlist {audio_playlist_id}"
                raise LookupError(msg)
            return browse_id

        return self._cached(("browse_id", audio_playlist_id), fetch)

    def _get_playlist_or_album(self, playlist_id: str) -> dict[str, Any]:
        # OLAK5uy_lUNm1YMm972Rvy0LpDg3ORQFjtN_8oBtc
        if playlist_id.startswith("OLAK5uy_"):
            playlist_id = self._album_browse_id(playlist_id)

        if playlist_id.startswith("PL"):
            result = self._playlist(playlist_id)
            result["playlistId"] = result["id"]
            result["artists"] = [result["author"]]
        else:
            result = self._album(playlist_id)
            if "artists" not in result:
                result["artists"] = result["artist"]
            if "playlistId" not in result:
                result["playlistId"] = playlist_id

        return result
