from __future__ import annotations

from typing import Any

from mopidy_youtube import logger
from mopidy_youtube.timeformat import clock_to_seconds, iso_duration

NO_DURATION = "PT0S"


def _resolve_duration(
    item: dict[str, Any], *, allow_unknown: bool = False
) -> str | None:
    for key in ("duration", "length", "lengthMs", "lengthSeconds", "song_duration"):
        value = item.get(key)
        if value is None or value == "":
            continue

        if key in {"lengthSeconds", "song_duration"}:
            try:
                return iso_duration(int(value))
            except (TypeError, ValueError):
                continue

        if key == "lengthMs":
            try:
                return iso_duration(int(value) // 1000)
            except (TypeError, ValueError):
                continue

        return iso_duration(clock_to_seconds(value))

    if allow_unknown:
        return None
    logger.warning("duration missing: %s", item)
    return NO_DURATION


def _resolve_thumbnail(item: dict[str, Any]) -> dict[str, Any]:
    thumbnails = (
        item.get("thumbnails") or item.get("thumbnail", {}).get("thumbnails") or [{}]
    )
    return thumbnails[-1]


def ytm_item_to_video(
    item: dict[str, Any], *, allow_unknown_duration: bool = False
) -> dict[str, Any]:
    """Describe a song or video like a Data API video resource.

    A duration that is not known is an error, and reads as zero, unless
    `allow_unknown_duration` is set: the item then has no `contentDetails`, and
    the length of the video is left to be looked up when somebody needs it.
    """
    if "videoDetails" in item:
        item = item["videoDetails"]

    try:
        duration = _resolve_duration(item, allow_unknown=allow_unknown_duration)
    except Exception as e:
        logger.error("youtube_music yt_item_to_video duration error %s: %s", e, item)
        duration = NO_DURATION

    try:
        if item.get("artists"):
            channel_title = (
                item["artists"][0]["name"]
                if isinstance(item["artists"], list)
                else item["artists"]
            )
        elif "byline" in item:
            logger.debug("byline: %s", item["byline"])
            channel_title = item["byline"]
        elif "author" in item:
            channel_title = item["author"]
        else:
            channel_title = "unknown"
    except Exception as e:
        logger.error("youtube_music yt_item_to_video artists error %s: %s", e, item)
        channel_title = "unknown"

    thumbnail = _resolve_thumbnail(item)

    video: dict[str, Any] = {
        "id": {"kind": "youtube#video", "videoId": item["videoId"]},
        "snippet": {
            "title": item["title"],
            "resourceId": {"kind": "youtube#video", "videoId": item["videoId"]},
            "thumbnails": {"default": thumbnail},
            "channelTitle": channel_title,
        },
        "track_no": item.get("track_no"),
    }
    if duration is not None:
        video["contentDetails"] = {"duration": duration}

    if "album" in item and item["album"] is not None:
        video["album"] = {
            "name": item["album"]["name"],
            "uri": f"yt:playlist:{item['album']['id']}",
        }

    if "artists" in item and isinstance(item["artists"], list):
        video["artists"] = [
            {
                "name": artist["name"],
                "uri": f"yt:channel:{artist['id']}" if artist.get("id") else None,
            }
            for artist in item["artists"]
            if isinstance(artist, dict)
            and "name" in artist
            and artist["name"] not in ["Album", "Song"]
        ]
    elif "author" in item and "channelId" in item:
        video["artists"] = [
            {
                "name": item["author"],
                "uri": f"yt:channel:{item['channelId']}",
            }
        ]

    return video
