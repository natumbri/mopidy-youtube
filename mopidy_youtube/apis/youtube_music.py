from __future__ import annotations

import json
from concurrent.futures import as_completed
from concurrent.futures.thread import ThreadPoolExecutor
from itertools import repeat
from typing import TYPE_CHECKING, Any, override

import pykka
from ytmusicapi import YTMusic

from mopidy_youtube import logger
from mopidy_youtube.apis.client import Client
from mopidy_youtube.apis.json_paths import YTM_ERROR_THUMBNAIL_PATH, traverse
from mopidy_youtube.apis.ytm_item_to_video import ytm_item_to_video
from mopidy_youtube.context import context
from mopidy_youtube.youtube import Playlist, Video

if TYPE_CHECKING:
    from collections.abc import Collection

    from mopidy_youtube.apis import YouTubeApi


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
        self._lookup_executor = ThreadPoolExecutor(max_workers=1)
        auth = (
            None
            if headers.get("Cookie") == "PREF=hl=en; CONSENT=YES+20210329;"
            else json.dumps(headers)
        )
        try:
            self.ytmusic = YTMusic(auth=auth, requests_session=self.session)
        except Exception as e:
            logger.error("YTMusic init error: %s", str(e))
            self.ytmusic = YTMusic()

    @override
    def close(self) -> None:
        super().close()
        self._lookup_executor.shutdown(wait=False, cancel_futures=True)

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

        related_videos = []
        get_song_related_tracks = []
        try:
            logger.debug(
                f"youtube_music list_related_videos triggered "
                f"ytmusic.get_song_related ({related_browse_id})"
            )
            get_song_related_tracks = self.ytmusic.get_song_related(related_browse_id)[
                0
            ]["contents"]

            logger.debug(
                f"youtube_music list_related_videos triggered "
                f"ytmusic.get_song for {len(related_videos)} tracks."
            )
            related_videos = [
                self.ytmusic.get_song(track["videoId"])["videoDetails"]
                for track in get_song_related_tracks
            ]

        except Exception as e:
            logger.error(
                f"youtube_music list_related_videos error:{e} "
                f"Related_browseId: {related_browse_id}"
            )

        if len(related_videos) < 10:
            logger.warning(
                f"get_song_related returned {len(related_videos)} tracks. "
                f"Trying get_watch_playlist['tracks'] for more"
            )
            try:
                logger.debug(
                    f"youtube_music list_related_videos triggered "
                    f"ytmusic.get_song for {len(get_watch_playlist['tracks'])} tracks"
                )

                related_videos.extend(
                    [
                        self.ytmusic.get_song(track["videoId"])["videoDetails"]
                        for track in get_watch_playlist["tracks"]
                    ]
                )
            except Exception as e:
                logger.error(f"youtube_music list_related_videos error:{e}")

        related_albums = set()
        for item in related_videos:
            for related_track in get_song_related_tracks:
                if item["videoId"] == related_track["videoId"]:
                    album = related_track.get("album")
                    if album:  # a song without an album has `album: None`
                        item["album"] = album
                        if album.get("id"):
                            related_albums.add(album["id"])
                    if "artists" in related_track:
                        item["artists"] = related_track["artists"]

        self._lookup_executor.submit(self.list_playlists, related_albums)

        tracks = [
            ytm_item_to_video(track)
            for track in related_videos
            if track["videoId"] is not None
        ]

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

        # these the playlists that are returned
        items = [self.yt_listitem_to_playlist(result) for result in results if result]

        # create the playlist objects and video objects for each track in
        # the playlist, and add the videos to the playlist to avoid
        # list_playlistitems calling self.ytmusic.get_playlist
        self._create_playlist_objects(items)

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

        pl = Playlist.get(playlist["id"]["playlistId"])
        pl._set_api_data(["title", "video_count", "thumbnails", "channel"], playlist)

        items = [
            track for track in playlist["tracks"] if track["id"]["videoId"] is not None
        ]

        [
            item.update({"id": item["id"]["videoId"]})
            for item in items
            if "videoId" in item["id"]
        ]

        items = items[:max_results]
        ajax = None
        return json.loads(
            json.dumps(
                {"nextPageToken": ajax, "items": items},
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
            logger.debug(
                f"youtube_music process_albums triggered "
                f"ytmusic.get_album: {result['browseId']}"
            )
            # self.ytmusic.get_album is necessary to get the number of tracks
            ytmusic_album = self.ytmusic.get_album(result["browseId"])
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

        # given we're calling self.ytmusic.get_album, which returns tracks, we might
        # as well create the playlist objects and the related video objects.
        self._create_playlist_objects(albums)

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

    def _get_playlist_or_album(self, playlist_id: str) -> dict[str, Any]:
        # OLAK5uy_lUNm1YMm972Rvy0LpDg3ORQFjtN_8oBtc
        if playlist_id.startswith("OLAK5uy_"):
            playlist_id = YTMusic.get_album_browse_id(YTMusic(), playlist_id)  # pyright: ignore[reportAssignmentType]

        if playlist_id.startswith("PL"):
            logger.debug(
                "youtube_music _get_playlist_or_album triggered "
                f"ytmusic.get_playlist: {playlist_id}"
            )
            result = self.ytmusic.get_playlist(playlist_id)
            result["playlistId"] = result["id"]
            result["artists"] = [result["author"]]

        else:
            logger.debug(
                "youtube_music _get_playlist_or_album triggered "
                f"ytmusic.get_album: {playlist_id}"
            )
            result = self.ytmusic.get_album(playlist_id)
            if "artists" not in result:
                result["artists"] = result["artist"]
            if "playlistId" not in result:
                result["playlistId"] = playlist_id

        return result

    @staticmethod
    def _create_playlist_objects(items: list[dict[str, Any]]) -> None:
        for item in items:
            plvideos = []
            pl = Playlist.get(item["id"]["playlistId"])
            pl._set_api_data(["title", "video_count", "thumbnails", "channel"], item)

            pl._videos = pykka.ThreadingFuture()

            for track in item["tracks"]:
                if "album" not in track:
                    track.update(
                        {
                            "album": {
                                "name": item["snippet"]["title"],
                                "id": item["id"]["playlistId"],
                            }
                        }
                    )
                video = Video.get(track["snippet"]["resourceId"]["videoId"])
                fields = [
                    "title",
                    "channel",
                    "length",
                    "thumbnails",
                    "album",
                    "artists",
                ]
                if "track_no" in track:
                    fields.append("track_no")
                video._set_api_data(fields, track)
                plvideos.append(video)

            pl._videos.set(
                [
                    x
                    for _, x in zip(
                        range(context.playlist_max_videos), plvideos, strict=False
                    )
                ]
            )
