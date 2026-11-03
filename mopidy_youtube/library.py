from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, override

from cachetools import TTLCache, cached
from mopidy import backend
from mopidy.models import Image, Ref, SearchResult, Track
from mopidy.types import Uri

from mopidy_youtube import logger, youtube
from mopidy_youtube.cache import read_cached_track
from mopidy_youtube.context import context
from mopidy_youtube.converters import convert_playlist_to_album, convert_video_to_track
from mopidy_youtube.data import (
    extract_channel_id,
    extract_playlist_id,
    extract_preload_tracks,
    extract_video_id,
    format_playlist_uri,
)
from mopidy_youtube.youtube import Video

if TYPE_CHECKING:
    from collections.abc import Iterable

    from mopidy.types import Query, SearchField

    from mopidy_youtube.backend import YouTubeBackend


class YouTubeLibraryProvider(backend.LibraryProvider):
    backend: YouTubeBackend

    root_directory = Ref.directory(uri=Uri("youtube:browse"), name="YouTube")

    """
    Called when root_directory is set to the URI of the youtube channel ID in the
    mopidy.conf. When enabled makes possible to browse public playlists of the
    channel as well as browse separate tracks in playlists.
    """

    cache_max_len = 4000
    cache_ttl = 21600

    youtube_library_cache = TTLCache(maxsize=cache_max_len, ttl=cache_ttl)

    @override
    def browse(self, uri: Uri) -> list[Ref]:
        return self._cached_browse(uri)

    @cached(cache=youtube_library_cache)
    def _cached_browse(self, uri: Uri) -> list[Ref]:
        if uri == "youtube:browse":
            return [
                Ref.directory(
                    uri=Uri("youtube:channel:root"), name="My Youtube playlists"
                ),
                Ref.directory(
                    uri=Uri("youtube:channel:artists"), name="My Youtube artists"
                ),
            ]

        if uri == "youtube:channel:artists":
            playlists = [
                self.lookup(Uri(f"yt:playlist:{playlist.id}"))
                for playlist in youtube.Channel.playlists("root") or []
            ]
            artistrefs = {
                Ref.artist(  # pyright: ignore[reportUnhashable] - frozen model
                    uri=artist.uri, name=artist.name
                )
                for playlist in playlists
                for track in playlist
                for artist in track.artists
                if artist.uri
            }
            return sorted(artistrefs, key=lambda x: (x.name or "").lower())

        if extract_playlist_id(uri):
            tracks = self.lookup(uri)
            return [Ref.track(uri=track.uri, name=track.name) for track in tracks]

        if extract_channel_id(uri):
            logger.debug(f"browse channel / library {uri}")
            playlists = youtube.Channel.playlists(extract_channel_id(uri))
            playlistrefs = [
                Ref.playlist(uri=format_playlist_uri(pl.id), name=pl.title.get())
                for pl in playlists or []
            ]
            playlistrefs.sort(key=lambda x: (x.name or "").lower())
            return playlistrefs

        return []

    @override
    def search(
        self,
        query: Query[SearchField] | None = None,
        uris: Iterable[Uri] | None = None,
        exact: bool = False,
    ) -> SearchResult | None:
        logger.debug('youtube LibraryProvider.search "%s"', query)

        if not (query and any(key in query for key in ["uri", "any"])):
            return None
        if "uri" in query:
            tracks = self.lookup(Uri(str(next(iter(query["uri"])))))
            if tracks and tracks[0].uri:
                return SearchResult(uri=Uri("youtube:search"), tracks=tuple(tracks))
            return None

        search_query = " ".join(str(value) for value in query["any"])
        logger.debug('Searching YouTube for query "%s"', search_query)

        try:
            entries = youtube.Entry.search(search_query)
        except Exception as e:
            logger.error('backend search error "%s"', e)
            return None

        playlists = [entry for entry in entries if isinstance(entry, youtube.Playlist)]
        videos = [entry for entry in entries if isinstance(entry, youtube.Video)]
        youtube.Playlist.load_info(playlists)
        youtube.Video.load_info(videos)

        tracks = [convert_video_to_track(video) for video in videos]

        albums = []
        for pl in playlists:
            albums.append(convert_playlist_to_album(pl))
            pl.videos  # noqa: B018 - starts the background load

        return SearchResult(
            uri=Uri("youtube:search"),
            tracks=tuple(tracks),
            artists=(),
            albums=tuple(albums),
        )

    def lookup_video_track(self, video_id: str) -> Track:
        if context.cache_location:
            try:
                track = read_cached_track(context.cache_location, video_id)
            except Exception as e:
                logger.debug(f"Did not open {video_id}.json: {e}")
            else:
                return track

        video = youtube.Video.get(video_id)
        video.title.get()
        return convert_video_to_track(video)

    def lookup_playlist_tracks(self, playlist_id: str) -> list[Track] | None:
        playlist = youtube.Playlist.get(playlist_id)
        if not playlist.videos.get():
            return None

        videos = [
            video for video in playlist.videos.get() if video.length.get() is not None
        ]

        return [
            convert_video_to_track(
                video,
                album_name=playlist.title.get(),
                album_id=playlist_id,
            )
            for video in videos
        ]

    def lookup_channel_tracks(self, channel_id: str) -> list[Track] | None:
        channel_playlists = youtube.Channel.playlists(channel_id)

        if not channel_playlists:
            return None

        videos = [
            video for playlist in channel_playlists for video in playlist.videos.get()
        ]
        return [convert_video_to_track(video) for video in videos]

    @override
    def lookup(self, uri: Uri) -> list[Track]:
        logger.debug('youtube LibraryProvider.lookup "%s"', uri)

        preload = extract_preload_tracks(uri)
        if preload:
            for track in preload["preloadTracks"]:
                video = Video.get(track["id"]["videoId"])
                minimum_fields = ["title", "length", "channel"]
                item, extended_fields = video.extend_fields(track, minimum_fields)
                video._set_api_data(extended_fields, item)
            uri = preload["videoUri"]

        playlist_id = extract_playlist_id(uri)
        if playlist_id:
            playlist_tracks = self.lookup_playlist_tracks(playlist_id)
            if playlist_tracks:
                return playlist_tracks

        video_id = extract_video_id(uri)
        if video_id:
            return [self.lookup_video_track(video_id)]

        channel_id = extract_channel_id(uri)
        if channel_id:
            channel_tracks = self.lookup_channel_tracks(channel_id)
            if channel_tracks:
                return channel_tracks

        logger.error(f"Cannot load {uri}")
        return [Track(uri=Uri("youtube:video:unknown"), name="Unknown")]

    @override
    def get_images(self, uris: Iterable[Uri]) -> dict[Uri, list[Image]]:
        images: dict[Uri, list[Image]] = {}

        uri_list: list[Uri] = [Uri(uris)] if isinstance(uris, str) else list(uris)
        video_ids = [extract_video_id(uri) for uri in uri_list]

        if context.cache_location and (self.backend.config.get("http") or {}).get(
            "enabled"
        ):
            cached_files = {
                path.name for path in Path(context.cache_location).iterdir()
            }
            for uri in uri_list:
                video_id = extract_video_id(uri)
                if not video_id:
                    continue
                if f"{video_id}.webp" in cached_files:
                    ext = "webp"
                elif f"{video_id}.jpg" in cached_files:
                    ext = "jpg"
                else:
                    continue
                images[uri] = [Image(uri=Uri(f"/youtube/{video_id}.{ext}"))]

            logger.debug(
                f"using cached images: {[extract_video_id(uri) for uri in images]}"
            )

        images.update(
            {
                uri: youtube.Video.get(video_id).thumbnails.get()
                for uri, video_id in zip(uri_list, video_ids, strict=False)
                if video_id and uri not in images
            }
        )

        playlist_ids = [extract_playlist_id(uri) for uri in uri_list]
        images.update(
            {
                uri: youtube.Playlist.get(playlist_id).thumbnails.get()
                for uri, playlist_id in zip(uri_list, playlist_ids, strict=False)
                if playlist_id
            }
        )
        return images
