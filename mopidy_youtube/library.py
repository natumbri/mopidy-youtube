import json
import os

from cachetools import TTLCache, cached
from mopidy import backend
from mopidy.models import Image, Ref, SearchResult, Track

from mopidy_youtube import logger, runtime, youtube
from mopidy_youtube.converters import convert_playlist_to_album, convert_video_to_track
from mopidy_youtube.data import (
    extract_channel_id,
    extract_playlist_id,
    extract_preload_tracks,
    extract_video_id,
    format_playlist_uri,
)
from mopidy_youtube.youtube import Video


class YouTubeLibraryProvider(backend.LibraryProvider):
    root_directory = Ref.directory(uri="youtube:browse", name="YouTube")

    """
    Called when root_directory is set to the URI of the youtube channel ID in the mopidy.conf
    When enabled makes possible to browse public playlists of the channel as well as browse
    separate tracks in playlists.
    """

    cache_max_len = 4000
    cache_ttl = 21600

    youtube_library_cache = TTLCache(maxsize=cache_max_len, ttl=cache_ttl)

    @cached(cache=youtube_library_cache)
    def browse(self, uri):
        if uri == "youtube:browse":
            return [
                Ref.directory(uri="youtube:channel:root", name="My Youtube playlists"),
                Ref.directory(uri="youtube:channel:artists", name="My Youtube artists"),
            ]

        if uri == "youtube:channel:artists":
            playlists = [
                self.lookup(f"yt:playlist:{playlist.id}")
                for playlist in youtube.Channel.playlists("root")
            ]
            artistrefs = {
                Ref.artist(uri=artist.uri, name=artist.name)
                for playlist in playlists
                for track in playlist
                for artist in track.artists
                if artist.uri
            }
            artistrefs_list = sorted(artistrefs, key=lambda x: x.name.lower())
            return artistrefs_list

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
            playlistrefs.sort(key=lambda x: x.name.lower())
            return playlistrefs

        return []

    def search(self, query=None, uris=None, exact=False):
        logger.debug('youtube LibraryProvider.search "%s"', query)

        if not (query and any(key in query for key in ["uri", "any"])):
            return None
        if "uri" in query:
            tracks = self.lookup(query["uri"][0])
            if tracks and tracks[0].uri:
                return SearchResult(uri="youtube:search", tracks=tracks)
            return None

        search_query = " ".join(query["any"])
        logger.debug('Searching YouTube for query "%s"', search_query)

        try:
            entries = youtube.Entry.search(search_query)
        except Exception as e:
            logger.error('backend search error "%s"', e)
            return None

        playlists = [entry for entry in entries if not entry.is_video]
        youtube.Playlist.load_info(playlists)
        youtube.Video.load_info([entry for entry in entries if entry.is_video])

        tracks = [convert_video_to_track(entry) for entry in entries if entry.is_video]
        artists = []

        albums = []
        for pl in playlists:
            albums.append(convert_playlist_to_album(pl))
            pl.videos

        search_result = SearchResult(
            uri="youtube:search", tracks=tracks, artists=artists, albums=albums
        )

        return search_result

    def lookup_video_track(self, video_id: str) -> Track:
        if runtime.cache_location:
            try:
                with open(
                    os.path.join(runtime.cache_location, f"{video_id}.json"), "r"
                ) as infile:
                    track = Track.model_validate(json.load(infile))
                return track
            except Exception as e:
                logger.debug(f"Did not open {video_id}.json: {e}")

        video = youtube.Video.get(video_id)
        video.title.get()
        return convert_video_to_track(video)

    def lookup_playlist_tracks(self, playlist_id: str):
        playlist = youtube.Playlist.get(playlist_id)
        if not playlist.videos.get():
            return None

        videos = [
            video for video in playlist.videos.get() if video.length.get() is not None
        ]

        tracks = [
            convert_video_to_track(
                video,
                album_name=playlist.title.get(),
                album_id=playlist_id,
            )
            for video in videos
        ]
        return tracks

    def lookup_channel_tracks(self, channel_id: str):
        channel_playlists = youtube.Channel.playlists(channel_id)

        if not channel_playlists:
            return None

        videos = [
            video for playlist in channel_playlists for video in playlist.videos.get()
        ]
        return [convert_video_to_track(video) for video in videos]

    def lookup(self, uri):
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
        return [Track(uri="youtube:video:unknown", name="Unknown")]

    def get_images(self, uris):
        images = {}

        if not isinstance(uris, list):
            uris = [uris]

        video_ids = [extract_video_id(uri) for uri in uris]

        if runtime.cache_location and self.backend.config.get("http").get("enabled"):
            cached_files = set(os.listdir(runtime.cache_location))
            images = {
                uri: [Image(uri=f"/youtube/{video_id}.{ext}")]
                for uri in uris
                for video_id in [extract_video_id(uri)]
                if video_id
                and (
                    (f"{video_id}.webp" in cached_files and (ext := "webp"))
                    or (f"{video_id}.jpg" in cached_files and (ext := "jpg"))
                )
            }

            logger.debug(
                f"using cached images: {[extract_video_id(uri) for uri in images]}"
            )

        images.update(
            {
                uri: youtube.Video.get(video_id).thumbnails.get()
                for uri, video_id in zip(uris, video_ids)
                if video_id and uri not in images
            }
        )

        playlist_ids = [extract_playlist_id(uri) for uri in uris]
        images.update(
            {
                uri: youtube.Playlist.get(playlist_id).thumbnails.get()
                for uri, playlist_id in zip(uris, playlist_ids)
                if playlist_id
            }
        )
        return images
