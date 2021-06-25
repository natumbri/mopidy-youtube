import re
from urllib.parse import parse_qs, urlparse

import pykka
from mopidy import backend, httpclient
from mopidy.models import Album, Artist, SearchResult, Track, Ref

from mopidy_youtube import Extension, logger, youtube
from mopidy_youtube.apis import youtube_api, youtube_bs4api, youtube_music
from mopidy_youtube import channel_storage
from mopidy_youtube.data import (
    extract_channel_id,
    extract_playlist_id,
    extract_video_id,
    format_playlist_uri,
    format_video_uri,
)

"""
A typical interaction:
1. User searches for a keyword (YouTubeLibraryProvider.search)
2. User adds a track to the queue (YouTubeLibraryProvider.lookup)
3. User plays a track from the queue (YouTubePlaybackProvider.translate_uri)
step 1 requires only 2 API calls. Data for the next steps are loaded in the
background, so steps 2/3 are usually instantaneous.
"""


def convert_video_to_track(
    video: youtube.Video, album_name: str, **kwargs
) -> Track:

    try:
        adjustedLength = video.length.get() * 1000
    except Exception:
        adjustedLength = 0

    return Track(
        name=video.title.get(),
        comment=video.id,
        length=adjustedLength,
        artists=[Artist(name=video.channel.get())],
        album=Album(name=album_name),
        uri=format_video_uri(video),
        **kwargs,
    )


def convert_videos_to_tracks(videos, album_name: str):
    # load audio_url in the background to be ready for playback
    for video in videos:
        video.audio_url  # start loading

    return [
        convert_video_to_track(
            video,
            album_name,
            track_no=count,
        )
        for count, video in enumerate(videos, 1)
    ]


def convert_playlist_to_track(playlist: youtube.Playlist) -> Track:
    album_name = f"YouTube Playlist ({playlist.video_count.get()} videos)"
    return Track(
        name=playlist.title.get(),
        comment=playlist.id,
        length=0,
        artists=[Artist(name=playlist.channel.get())],
        album=Album(name=album_name),
        uri=format_playlist_uri(playlist),
    )


def convert_playlist_to_album(playlist: youtube.Playlist) -> Album:
    return Album(
        name=playlist.title.get(),
        artists=[
            Artist(
                name=f"YouTube Playlist ({playlist.video_count.get()} videos)"
            )
        ],
        uri=format_playlist_uri(playlist),
    )


class YouTubeBackend(pykka.ThreadingActor, backend.Backend):
    def __init__(self, config, audio):
        super().__init__()
        self.config = config
        self.library = YouTubeLibraryProvider(backend=self)
        self.playback = YouTubePlaybackProvider(audio=audio, backend=self)
        youtube_api.youtube_api_key = (
            config["youtube"]["youtube_api_key"] or None
        )
        youtube.Video.search_results = config["youtube"]["search_results"]
        youtube.Playlist.playlist_max_videos = config["youtube"][
            "playlist_max_videos"
        ]
        youtube.api_enabled = config["youtube"]["api_enabled"]
        youtube.musicapi_enabled = config["youtube"]["musicapi_enabled"]
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

        if youtube.api_enabled is True:
            if youtube_api.youtube_api_key is None:
                logger.error("No YouTube API key provided, disabling API")
                youtube.api_enabled = False
            else:
                youtube.Entry.api = youtube_api.API(proxy, headers)
                if youtube.Entry.search(q="test") is None:
                    logger.error(
                        "Failed to verify YouTube API key, disabling API"
                    )
                    youtube.api_enabled = False
                else:
                    logger.info("YouTube API key verified")

        if youtube.api_enabled is False:
            logger.info("using bs4API")
            youtube.Entry.api = youtube_bs4api.bs4API(proxy, headers)

        if youtube.musicapi_enabled is True:
            logger.info("Using YouTube Music API")
            music = youtube_music.Music(proxy, headers)
            youtube.Entry.api.search = music.search
            youtube.Entry.api.list_playlistitems = music.list_playlistitems
            if youtube.api_enabled is False:
                youtube.Entry.api.list_playlists = music.list_playlists


class YouTubeLibraryProvider(backend.LibraryProvider):
    channel = channel_storage.my_channel
    if channel:
        print(type(channel))
        my_channel_uri = "youtube:channel:{}".format(channel)
        root_directory = Ref.directory(uri=my_channel_uri, name='My Youtube playlists')

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
        logger.info('youtube LibraryProvider.search "%s"', query)

        # handle only searching (queries with 'any') not browsing!
        if not (query and "any" in query):
            return None

        search_query = " ".join(query["any"])
        logger.info('Searching YouTube for query "%s"', search_query)

        try:
            entries = youtube.Entry.search(search_query)
        except Exception as e:
            logger.error('search error "%s"', e)
            return None

        # load playlist info (to get video_count) of all playlists together
        playlists = [entry for entry in entries if not entry.is_video]
        youtube.Playlist.load_info(playlists)

        albums = []
        artists = []
        tracks = []

        for entry in entries:
            if entry.is_video:
                tracks.append(convert_video_to_track(entry, "YouTube Video"))

                # # does it make sense to try to return youtube 'channels' as
                # # mopidy 'artists'? I'm not convinced.
                # if entry.channelId.get():
                #     artists.append(
                #         Artist(
                #             name=f"YouTube Channel: {entry.channel.get()}",
                #             uri=f"youtube:channel:{entry.channelId.get()}",
                #         )
                #     )
                # else:
                #     logger.info("no channelId")

            else:
                tracks.append(convert_playlist_to_track(entry))

        # load video info and playlist videos in the background. they should be
        # ready by the time the user adds search results to the playing queue
        for pl in playlists:
            albums.append(convert_playlist_to_album(pl))
            pl.videos  # start loading

        return SearchResult(
            uri="youtube:search", tracks=tracks, artists=artists, albums=albums
        )

    def lookup_video_track(self, video_id: str) -> Track:
        video = youtube.Video.get(video_id)
        video.audio_url  # start loading
        video.title.get()
        return convert_video_to_track(video, "YouTube Video")

    def lookup_playlist_tracks(self, playlist_id: str):
        playlist = youtube.Playlist.get(playlist_id)

        if not playlist.videos.get():
            return None

        # ignore videos for which no info was found (removed, etc)
        videos = [
            video
            for video in playlist.videos.get()
            if video.length.get() is not None
        ]
        album_name = playlist.title.get()

        return convert_videos_to_tracks(videos, album_name)

    # def lookup_channel_tracks(self, channel_id: str):
    #     channel = youtube.Channel.get(channel_id)
    #
    #     if not channel.videos.get():
    #         return None
    #
    #     # ignore videos for which no info was found (removed, etc)
    #     videos = [
    #         video for video in channel.videos.get() if video.length.get() is not None
    #     ]
    #     album_name = channel.title.get()
    #
    #     return convert_videos_to_tracks(videos, album_name)

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

        logger.info('youtube LibraryProvider.lookup "%s"', uri)

        if "youtube.com" in uri:
            url = urlparse(uri.replace("yt:", "").replace("youtube:", ""))
            req = parse_qs(url.query)
            if "list" in req:
                playlist_id = req.get("list")[0]
                if playlist_id:
                    return self.lookup_playlist_tracks(playlist_id)
            elif "v" in req:
                video_id = req.get("v")[0]
                if video_id:
                    return [self.lookup_video_track(video_id)]
            else:
                return []

        elif "youtu.be" in uri:
            url = uri.replace("yt:", "").replace("youtube:", "")
            if not re.match("^(?:http|https)://", url):
                url = "https://" + url
            video_id = urlparse(url).path
            if video_id[0] == "/":
                video_id = video_id[1:]
            if video_id:
                return [self.lookup_video_track(video_id)]
            else:
                return []

        video_id = extract_video_id(uri)
        if video_id:
            return [self.lookup_video_track(video_id)]

        playlist_id = extract_playlist_id(uri)
        if playlist_id:
            playlist_tracks = self.lookup_playlist_tracks(playlist_id)
            if playlist_tracks is None:
                logger.error('Cannot load "%s"', uri)
                return []
            else:
                return playlist_tracks

        # channel_id = extract_channel_id(uri)
        # if channel_id:
        #     channel_tracks = self.lookup_channel_tracks(channel_id)
        #     if channel_tracks is None:
        #         logger.error('Cannot load "%s"', uri)
        #         return []
        #     else:
        #         return channel_tracks

        return []

    def browse(self, uri):
        """
        Called when root_directory is set to the URI of "My Youtube Channel" in channel_storage.py.
        When enabled makes possible to browse public playlists of the channel as well as browse separate tracks in playlists
        Requires enabled API at the moment
        """
        logger.debug('browse: ' + uri)
        if uri.startswith("youtube:playlist"):
            trackrefs = []
            tracks = self.lookup(uri)
            for track in tracks:
                trackrefs.append(Ref.track(uri=track.uri, name=track.name))
            return trackrefs
        elif uri.startswith("youtube:channel"):
            playlistrefs = []
            albums = []
            channel_id = extract_channel_id(uri)
            playlists = youtube.Channel.get_channel_playlists(channel_id)
            for pl in playlists:
                albums.append(convert_playlist_to_album(pl))
            for album in albums:
                playlistrefs.append(Ref.playlist(uri=album.uri, name=album.name))
            return playlistrefs

    def get_images(self, uris):
        return {uri: youtube.Video.get(uri).thumbnails.get() for uri in uris}


class YouTubePlaybackProvider(backend.PlaybackProvider):
    def should_download(self, uri):
        return True

    def translate_uri(self, uri):
        """
        Called when a track us ready to play, we need to return the actual url of
        the audio. uri must be of the form youtube:video/<title>.<id> or youtube:video:<id>
        (only videos can be played, playlists are expanded into tracks by
        YouTubeLibraryProvider.lookup)
        """

        logger.info('youtube PlaybackProvider.translate_uri "%s"', uri)

        video_id = extract_video_id(uri)
        if not video_id:
            return None

        try:
            return youtube.Video.get(video_id).audio_url.get()
        except Exception as e:
            logger.error('translate_uri error "%s"', e)
            return None
