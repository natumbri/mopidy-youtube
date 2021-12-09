import json
import os

import pykka
from mopidy import backend, httpclient
from mopidy.core import CoreListener
from mopidy.models import Image, Ref, SearchResult, Track, model_json_decoder

from mopidy_youtube import Extension, logger, youtube
from mopidy_youtube.apis import youtube_api, youtube_japi, youtube_music
from mopidy_youtube.converters import convert_playlist_to_album, convert_video_to_track
from mopidy_youtube.data import (
    extract_channel_id,
    extract_playlist_id,
    extract_video_id,
)

"""
A typical interaction:
1. User searches for a keyword (YouTubeLibraryProvider.search)
2. User adds a track to the queue (YouTubeLibraryProvider.lookup)
3. User plays a track from the queue (YouTubePlaybackProvider.translate_uri)
step 1 requires only 2 API calls. Data for the next steps are loaded in the
background, so steps 2/3 are usually instantaneous.
"""


class YouTubeCoreListener(pykka.ThreadingActor, CoreListener):
    def __init__(self, config, core):
        super().__init__()
        self.config = config
        self.core = core

    def tracklist_changed(self):
        # We really only need an audio url for tracks that are going to be played
        # (ie have been added to the tracklist): when a track is added to the
        # tracklist, get the audio_url for the added track.
        # Previously this was taken care of by YouTubeLibraryProvider.lookup(),
        # but that seems to get called for tracks that are not being added to the
        # tracklist. So how do you do that?
        # This method is triggered when the tracklist is changed. At the moment,
        # it then tries to get the audio_url for all youtube tracks in the tracklist.
        # Since audio_url is low cost for tracks that already have an audio url, it
        # doesn't bother to keep track of which tracks it has and hasn't requested an
        # audio url for. There must be a better way.

        tracks = self.core.tracklist.get_tracks().get()
        video_ids = [
            extract_video_id(track.uri)
            for track in tracks
            if track.uri.startswith("youtube:video:")
            or track.uri.startswith("yt:video:")
        ]
        videos = [youtube.Video.get(video_id) for video_id in video_ids]
        [video.audio_url for video in videos]


class YouTubeBackend(pykka.ThreadingActor, backend.Backend):
    def __init__(self, config, audio):
        super().__init__()
        self.config = config
        self.library = YouTubeLibraryProvider(backend=self)
        self.playback = YouTubePlaybackProvider(audio=audio, backend=self)
        youtube_api.API.youtube_api_key = config["youtube"]["youtube_api_key"] or None
        youtube.channel = config["youtube"]["channel_id"]
        youtube.Video.search_results = config["youtube"]["search_results"]
        youtube.Video.http_port = config["http"]["port"]
        youtube.Playlist.playlist_max_videos = config["youtube"]["playlist_max_videos"]
        youtube.api_enabled = config["youtube"]["api_enabled"]
        youtube.musicapi_enabled = config["youtube"]["musicapi_enabled"]
        youtube.musicapi_cookie = config["youtube"].get("musicapi_cookie", None)
        youtube_music.own_channel_id = youtube.channel
        youtube.youtube_dl_package = config["youtube"]["youtube_dl_package"]
        self.uri_schemes = ["youtube", "yt"]
        self.user_agent = "{}/{}".format(Extension.dist_name, Extension.version)

    def on_start(self):
        proxy = httpclient.format_proxy(self.config["proxy"])
        youtube.Video.proxy = proxy
        headers = {
            "user-agent": httpclient.format_user_agent(self.user_agent),
            "Cookie": "PREF=hl=en; CONSENT=YES+20210329;",
            "Accept-Language": "en;q=0.8",
        }

        if self.config["youtube"]["allow_cache"]:
            youtube.cache_location = Extension.get_cache_dir(self.config)
            logger.info(f"file caching enabled (at {youtube.cache_location})")
        else:
            youtube.cache_location = None
            logger.info("file caching not enabled")

        if youtube.api_enabled is True:
            if youtube_api.API.youtube_api_key is None:
                logger.error("No YouTube API key provided, disabling API")
                youtube.api_enabled = False
            else:
                youtube.Entry.api = youtube_api.API(proxy, headers)
                if youtube.Entry.search(q="test") is None:
                    logger.error("Failed to verify YouTube API key, disabling API")
                    youtube.api_enabled = False
                else:
                    logger.info("YouTube API key verified")

        if youtube.api_enabled is False:
            logger.info("using jAPI")
            youtube.Entry.api = youtube_japi.jAPI(proxy, headers)

        if youtube.musicapi_enabled is True:
            logger.info("Using YouTube Music API")

            if youtube.musicapi_cookie:
                headers.update({"Cookie": youtube.musicapi_cookie})

            headers.update(
                {
                    "Accept": "*/*",
                    "Content-Type": "application/json",
                    "origin": "https://music.youtube.com",
                }
            )

            youtube.Entry.api = youtube_music.Music(proxy, headers)
            # if youtube.api_enabled:
            #     youtube.Entry.api.list_playlists = music.list_playlists


class YouTubeLibraryProvider(backend.LibraryProvider):

    root_directory = Ref.directory(
        uri="youtube:channel:root", name="My Youtube playlists"
    )

    """
    Called when root_directory is set to the URI of the youtube channel ID in the mopidy.conf
    When enabled makes possible to browse public playlists of the channel as well as browse
    separate tracks in playlists.
    """

    def browse(self, uri):
        if extract_playlist_id(uri):
            trackrefs = []
            tracks = self.lookup(uri)
            for track in tracks:
                trackrefs.append(Ref.track(uri=track.uri, name=track.name))
            return trackrefs
        elif extract_channel_id(uri):
            logger.info(f"browse channel / library {uri}")
            playlistrefs = []
            albums = []
            playlists = youtube.Channel.playlists(extract_channel_id(uri))
            if playlists:
                for pl in playlists:
                    pl.videos
                    albums.append(convert_playlist_to_album(pl))
                for album in albums:
                    playlistrefs.append(Ref.playlist(uri=album.uri, name=album.name))
            return playlistrefs

    """
    Called when browsing or searching the library. To avoid horrible browsing
    performance, and since only search makes sense for youtube anyway, we we
    only answer queries for the 'any' field (for instance a {'artist': 'U2'}
    query is ignored).

    For performance we only do 2 API calls before we reply, one for search
    (youtube.Entry.search) and one to fetch video_count of all playlists
    (youtube.Playlist.load_info).

    We also start loading 2 things in the background:
     - info for all videos
     - video list for all playlists
    Hence, adding search results to the playing queue (see
    YouTubeLibraryProvider.lookup) will most likely be instantaneous, since
    all info will be ready by that time.
    """

    def search(self, query=None, uris=None, exact=False):
        # TODO Support exact search
        logger.debug('youtube LibraryProvider.search "%s"', query)

        # handle only searching (queries with 'any') not browsing!
        if not (query and "any" in query):
            return None

        search_query = " ".join(query["any"])
        logger.debug('Searching YouTube for query "%s"', search_query)

        try:
            entries = youtube.Entry.search(search_query)
        except Exception as e:
            logger.error('backend search error "%s"', e)
            return None

        # load playlist info (to get video_count) of all playlists together
        playlists = [entry for entry in entries if not entry.is_video]
        youtube.Playlist.load_info(playlists)

        # load video info (to get length) of all videos together
        youtube.Video.load_info([entry for entry in entries if entry.is_video])

        albums = []
        artists = []
        tracks = []

        for entry in entries:
            if entry.is_video:
                tracks.append(convert_video_to_track(entry))

        # load video info and playlist videos in the background. they should be
        # ready by the time the user adds search results to the playing queue
        for pl in playlists:
            albums.append(convert_playlist_to_album(pl))
            pl.videos  # start loading

        search_result = SearchResult(
            uri="youtube:search", tracks=tracks, artists=artists, albums=albums
        )

        return search_result

    def lookup_video_track(self, video_id: str) -> Track:
        if youtube.cache_location:
            cached = [
                cached_file
                for cached_file in os.listdir(youtube.cache_location)
                if cached_file == f"{video_id}.json"
            ]
            if cached:
                with open(
                    os.path.join(youtube.cache_location, cached[0]), "r"
                ) as infile:
                    track = json.load(infile, object_hook=model_json_decoder)
                return track

        video = youtube.Video.get(video_id)
        video.title.get()
        return convert_video_to_track(video)

    def lookup_playlist_tracks(self, playlist_id: str):
        playlist = youtube.Playlist.get(playlist_id)
        if not playlist.videos.get():
            return None

        # ignore videos for which no info was found (removed, etc)
        videos = [
            video for video in playlist.videos.get() if video.length.get() is not None
        ]

        tracks = [
            convert_video_to_track(
                video,
                album_name=playlist.title.get(),
                album_id=playlist_id,
                track_no=count,
            )
            for count, video in enumerate(videos, 1)
        ]
        return tracks

    def lookup_channel_tracks(self, channel_id: str):
        channel_playlists = youtube.Channel.playlists(channel_id)

        if not channel_playlists:
            return None

        videos = []
        for playlist in channel_playlists:
            videos.extend(playlist.videos.get())

        tracks = [
            convert_video_to_track(video, track_no=count)
            for count, video in enumerate(videos, 1)
        ]
        return tracks

    def lookup(self, uri):
        """
        Called when the user adds a track to the playing queue, either from the
        search results, or directly by adding a yt:https://youtube.com/.... uri.
        uri can be of the form
            [yt|youtube]:<url to youtube video>
            [yt|youtube]:<url to youtube playlist>
            [yt|youtube]:video:<id>
            [yt|youtube]:playlist:<id>
            [yt|youtube]:video/<title>.<id>
            [yt|youtube]:playlist/<title>.<id>

        If uri is a video then a single track is returned. If it's a playlist the
        list of all videos in the playlist is returned.

        We also start loading the audio_url of all videos in the background, to
        be ready for playback (see YouTubePlaybackProvider.translate_uri).
        """

        logger.debug('youtube LibraryProvider.lookup "%s"', uri)

        video_id = extract_video_id(uri)
        if video_id:
            return [self.lookup_video_track(video_id)]

        playlist_id = extract_playlist_id(uri)
        if playlist_id:
            playlist_tracks = self.lookup_playlist_tracks(playlist_id)
            if playlist_tracks:
                return playlist_tracks

        channel_id = extract_channel_id(uri)
        if channel_id:
            channel_tracks = self.lookup_channel_tracks(channel_id)
            if channel_tracks is None:
                logger.error('Cannot load "%s"', uri)
                return []
            else:
                return channel_tracks

        logger.error('Cannot load "%s"', uri)
        return []

    def get_images(self, uris):
        images = {}

        if not isinstance(uris, list):
            uris = [uris]

        video_ids = [extract_video_id(uri) for uri in uris]

        if youtube.cache_location and self.backend.config.get("http").get("enabled"):
            for uri in uris:
                video_id = extract_video_id(uri)
                if video_id:
                    imageFile = f"{video_id}.jpg"
                    if imageFile in os.listdir(youtube.cache_location):
                        images.update({uri: [Image(uri=f"/youtube/{imageFile}")]})

            logger.debug(
                f"using cached images: {[extract_video_id(uri) for uri in images]}"
            )

        images.update(
            {
                uri: youtube.Video.get(video_id).thumbnails.get()
                for uri, video_id in zip(uris, video_ids)
                if video_id
                if uri not in images
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


class YouTubePlaybackProvider(backend.PlaybackProvider):
    def should_download(self, uri):
        return False

    def translate_uri(self, uri):
        """
        Called when a track us ready to play, we need to return the actual url of
        the audio. uri must be of the form youtube:video/<title>.<id> or youtube:video:<id>
        (only videos can be played, playlists are expanded into tracks by
        YouTubeLibraryProvider.lookup)
        """

        logger.debug('youtube PlaybackProvider.translate_uri "%s"', uri)

        video_id = extract_video_id(uri)
        if not video_id:
            return None

        try:
            return youtube.Video.get(video_id).audio_url.get()
        except Exception as e:
            logger.error('translate_uri error "%s"', e)
            return None
