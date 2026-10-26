from mopidy.models import Album, Artist, Track

from mopidy_youtube.data import format_playlist_uri, format_video_uri


def convert_video_to_track(
    video, album_name: str = None, album_id: str = None, **kwargs
) -> Track:
    try:
        adjustedLength = video.length.get() * 1000
    except Exception:
        adjustedLength = 0

    if not album_name:
        album = video.album.get()
    else:
        album = {"name": album_name, "uri": f"yt:playlist:{album_id}"}
    track = Track(
        uri=format_video_uri(video.id),
        name=video.title.get(),
        artists=[
            Artist(name=artist["name"], uri=artist["uri"])
            for artist in video.artists.get()
        ],
        album=Album(name=album["name"], uri=album["uri"]),
        length=adjustedLength,
        comment=video.id,
        track_no=video.track_no.get(),
        **kwargs,
    )

    return track


def convert_playlist_to_album(playlist) -> Album:
    return Album(
        uri=format_playlist_uri(playlist.id),
        name=playlist.title.get(),
        artists=[
            Artist(
                name=playlist.channel.get()
            )  # f"YouTube Playlist ({playlist.video_count.get()} videos)")
        ],
        num_tracks=playlist.video_count.get(),
    )

