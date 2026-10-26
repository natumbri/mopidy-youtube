from __future__ import annotations

import json
import os
import tempfile

from mopidy_youtube import logger
from mopidy_youtube.converters import convert_video_to_track


def find_cached_audio_path(cache_location, video_id):
    if not cache_location:
        return None

    cached = [
        cached_file
        for cached_file in os.listdir(cache_location)
        if cached_file
        in [f"{video_id}.{fmt}" for fmt in ["webm", "m4a", "mp3", "ogg"]]
    ]
    if not cached:
        return None
    return f"file://{os.path.join(cache_location, cached[0])}"


def cache_image(video, cache_location):
    if not cache_location:
        return

    if any(image in os.listdir(cache_location) for image in (f"{video.id}.webp", f"{video.id}.jpg")):
        return

    logger.debug(f"caching image {video.id}")
    image_uri = video.thumbnails.get()[0].uri
    response = video.api.session.get(
        image_uri,
        headers={"content-length": None, "host": None},
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
        raise Exception(f"Invalid image format for {video.id}; magic: {magic}")

    with open(os.path.join(cache_location, image_file), "wb") as out_file:
        out_file.write(magic)
        for chunk in response.iter_content():
            out_file.write(chunk)

    del response


def cache_metadata(video, cache_location, info):
    if not cache_location:
        return

    metadata_path = os.path.join(cache_location, f"{video.id}.json")
    if os.path.exists(metadata_path):
        try:
            with open(metadata_path, "r", encoding="utf-8") as infile:
                json.load(infile)
            return
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            logger.warning("Discarding malformed cache metadata for %s; rebuilding", metadata_path)
            try:
                os.remove(metadata_path)
            except OSError:
                pass

    logger.debug(f"caching metadata {video.id}")
    track = convert_video_to_track(video, bitrate=int(info.get("tbr", 0)))
    payload = json.dumps(track.model_dump(mode="json"))

    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=".json",
        dir=cache_location,
        delete=False,
    ) as tempfile_handle:
        tempfile_handle.write(payload)
        temp_path = tempfile_handle.name

    os.replace(temp_path, metadata_path)
