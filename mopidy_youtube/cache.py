from __future__ import annotations

import contextlib
import json
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mopidy_youtube import logger
from mopidy_youtube.context import context
from mopidy_youtube.converters import convert_video_to_track

if TYPE_CHECKING:
    from mopidy_youtube.youtube import Video


class InvalidImageFormatError(Exception):
    """The downloaded thumbnail is neither a JPEG nor a WebP image."""


def find_cached_audio_path(
    cache_location: Path | str | None, video_id: str
) -> str | None:
    if not cache_location:
        return None

    names = [f"{video_id}.{fmt}" for fmt in ["webm", "m4a", "mp3", "ogg"]]
    cached = [
        cached_file
        for cached_file in Path(cache_location).iterdir()
        if cached_file.name in names
    ]
    if not cached:
        return None
    return f"file://{cached[0]}"


def cache_image(video: Video, cache_location: Path | str | None) -> None:
    if not cache_location:
        return

    cache_dir = Path(cache_location)
    existing = {path.name for path in cache_dir.iterdir()}
    if any(image in existing for image in (f"{video.id}.webp", f"{video.id}.jpg")):
        return

    logger.debug(f"caching image {video.id}")
    image_uri = video.thumbnails.get()[0].uri
    response = context.api.session.get(
        image_uri,
        # headers set to None are dropped from the session's headers by requests
        headers={"content-length": None, "host": None},  # pyright: ignore[reportArgumentType]
        stream=True,
    )

    if response.status_code != 200:
        del response
        return

    logger.debug(f"caching image {video.id}")
    magic = next(response.iter_content(4))
    if magic == b"\xff\xd8\xff\xe0":
        image_file = f"{video.id}.jpg"
    elif magic == b"\x52\x49\x46\x46":
        image_file = f"{video.id}.webp"
    else:
        logger.debug(f"invalid image format for {video.id}; magic: {magic}")
        msg = f"Invalid image format for {video.id}; magic: {magic}"
        raise InvalidImageFormatError(msg)

    with (cache_dir / image_file).open("wb") as out_file:
        out_file.write(magic)
        for chunk in response.iter_content():
            out_file.write(chunk)

    del response


def cache_metadata(
    video: Video, cache_location: Path | str | None, info: dict[str, Any]
) -> None:
    if not cache_location:
        return

    cache_dir = Path(cache_location)
    metadata_path = cache_dir / f"{video.id}.json"
    if metadata_path.exists():
        try:
            with metadata_path.open(encoding="utf-8") as infile:
                json.load(infile)
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            logger.warning(
                "Discarding malformed cache metadata for %s; rebuilding", metadata_path
            )
            with contextlib.suppress(OSError):
                metadata_path.unlink()
        else:
            return

    logger.debug(f"caching metadata {video.id}")
    track = convert_video_to_track(video, bitrate=int(info.get("tbr", 0)))
    payload = json.dumps(track.model_dump(mode="json"))

    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=".json",
        dir=cache_dir,
        delete=False,
    ) as tempfile_handle:
        tempfile_handle.write(payload)
        temp_path = tempfile_handle.name

    Path(temp_path).replace(metadata_path)
