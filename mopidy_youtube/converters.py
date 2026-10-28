from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mopidy.models import Album, Artist, Track
from mopidy.types import DurationMs

from mopidy_youtube.data import format_playlist_uri, format_video_uri

if TYPE_CHECKING:
    from mopidy_youtube.youtube import Playlist, Video


def convert_video_to_track(
    video: Video,
    album_name: str | None = None,
    album_id: str | None = None,
    **kwargs: Any,
) -> Track:
    try:
        adjusted_length = video.length.get() * 1000
    except Exception:
        adjusted_length = 0

    album: dict[str, Any]
    if not album_name:
        album = video.album.get()
    else:
        album = {"name": album_name, "uri": f"yt:playlist:{album_id}"}
    return Track(
        uri=format_video_uri(video.id),
        name=video.title.get(),
        artists=frozenset(
            Artist(name=artist["name"], uri=artist["uri"])
            for artist in video.artists.get()
        ),
        album=Album(name=album["name"], uri=album["uri"]),
        length=DurationMs(adjusted_length),
        comment=video.id,
        track_no=video.track_no.get(),
        **kwargs,
    )


def convert_playlist_to_album(playlist: Playlist) -> Album:
    return Album(
        uri=format_playlist_uri(playlist.id),
        name=playlist.title.get(),
        artists=frozenset([Artist(name=playlist.channel.get())]),
        num_tracks=playlist.video_count.get(),
    )
