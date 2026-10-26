from mopidy_youtube import logger
from mopidy_youtube.timeformat import convert_Millis, format_duration


def _resolve_duration(item):
    for key in ("duration", "length", "lengthMs", "lengthSeconds", "song_duration"):
        if key not in item:
            continue

        value = item[key]
        if value is None or value == "":
            continue

        if key in {"lengthSeconds", "song_duration"}:
            try:
                return "PT" + format_duration(convert_Millis(int(value) * 1000))
            except (TypeError, ValueError):
                continue

        if key == "lengthMs":
            try:
                return "PT" + format_duration(convert_Millis(int(value)))
            except (TypeError, ValueError):
                continue

        return "PT" + format_duration(value)

    logger.warning("duration missing: %s", item)
    return "PT0H00M00S"


def _resolve_thumbnail(item):
    thumbnails = item.get("thumbnails") or item.get("thumbnail", {}).get("thumbnails") or [{}]
    return thumbnails[-1]


def ytm_item_to_video(item):
    if "videoDetails" in item:
        item = item["videoDetails"]

    try:
        duration = _resolve_duration(item)
    except Exception as e:
        logger.error("youtube_music yt_item_to_video duration error %s: %s", e, item)
        duration = "PT0H00M00S"

    try:
        if item.get("artists"):
            channelTitle = (
                item["artists"][0]["name"]
                if isinstance(item["artists"], list)
                else item["artists"]
            )
        elif "byline" in item:
            logger.debug("byline: %s", item["byline"])
            channelTitle = item["byline"]
        elif "author" in item:
            channelTitle = item["author"]
        else:
            channelTitle = "unknown"
    except Exception as e:
        logger.error("youtube_music yt_item_to_video artists error %s: %s", e, item)
        channelTitle = "unknown"

    thumbnail = _resolve_thumbnail(item)

    video = {
        "id": {"kind": "youtube#video", "videoId": item["videoId"]},
        "contentDetails": {"duration": duration},
        "snippet": {
            "title": item["title"],
            "resourceId": {"kind": "youtube#video", "videoId": item["videoId"]},
            "thumbnails": {"default": thumbnail},
            "channelTitle": channelTitle,
        },
        "track_no": item.get("track_no"),
    }

    if "album" in item and item["album"] is not None:
        video["album"] = {
            "name": item["album"]["name"],
            "uri": f"yt:playlist:{item['album']['id']}",
        }

    if "artists" in item and isinstance(item["artists"], list):
        video["artists"] = [
            {
                "name": artist["name"],
                "uri": f"yt:channel:{artist.get('id')}",
                # "thumbnail": ytmusic.get_artist(artist["id"])["thumbnails"][-1]
            }
            for artist in item["artists"]
            if artist["name"] not in ["Album", "Song"]
        ]
    elif "author" in item and "channelId" in item:
        video["artists"] = [
            {
                "name": item["author"],
                "uri": f"yt:channel:{item['channelId']}",
                # "thumbnail": ytmusic.get_artist(item['channelId'])["thumbnails"][-1]
            }
        ]

    return video
