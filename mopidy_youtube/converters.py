from mopidy.models import Album, Artist, Track

from mopidy_youtube.data import format_playlist_uri, format_video_uri


def convert_video_to_track(video, album_name: str, **kwargs) -> Track:

    try:
        adjustedLength = video.length.get() * 1000
    except Exception:
        adjustedLength = 0

    track = Track(
        uri=format_video_uri(video),
        name=video.title.get(),
        artists=[Artist(name=video.channel.get())],
        album=Album(name=album_name),
        length=adjustedLength,
        comment=video.id,
        **kwargs,
    )

    return track


# YouTube Music supports 'songs'; probably should take advantage and use
#
# def convert_ytmsong_to_track(
#     video: youtube.Video, album_name: str, **kwargs
# ) -> Track:
#
#     try:
#         adjustedLength = video.length.get() * 1000
#     except Exception:
#         adjustedLength = 0
#
#     return Track(
#         uri=format_video_uri(video),
#         name=video.title.get(),
#         artists=[Artist(name=video.channel.get())],
#         album=Album(name=album_name),
#         length=adjustedLength,
#         comment=video.id,
#         **kwargs,
#     )


def convert_playlist_to_album(playlist) -> Album:
    return Album(
        uri=format_playlist_uri(playlist),
        name=playlist.title.get(),
        artists=[
            Artist(
                name=f"YouTube Playlist ({playlist.video_count.get()} videos)"
            )
        ],
        num_tracks=playlist.video_count.get(),
    )


# YouTube Music supports 'Albums'; probably should take advantage and use
#
# def convert_ytmalbum_to_album(album: youtube.Album) -> Album:
#     return Album(
#         uri=format_album_uri(album),
#         name=f"{album.title.get()} (YouTube Music Album, {album.track_count.get()} tracks),
#         artists=[
#             Artist(
#                 # actual artists from the ytm album, including a name and uri
#             )
#         ],
#         num_tracks=
#         num_discs=
#         date=
#         musicbrainz_id=
#     )
