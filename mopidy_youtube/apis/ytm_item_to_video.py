import re

from mopidy_youtube import logger
from mopidy_youtube.comms import Client


def ytm_item_to_video(item):

    if "videoDetails" in item:
        item = item["videoDetails"]

    def _convertMillis(milliseconds):
        try:
            hours, miliseconds = divmod(int(milliseconds), 3600000)
        except Exception as e:
            logger.error(f"_convertMillis error: {e}, {milliseconds}")
            return "00:00:00"
        minutes, miliseconds = divmod(miliseconds, 60000)
        seconds = int(miliseconds) / 1000
        return "%i:%02i:%02i" % (hours, minutes, seconds)

    try:
        if "duration" in item:
            duration = item["duration"]
        elif "length" in item:
            duration = item["length"]
        elif "lengthMs" in item:
            duration = _convertMillis(item["lengthMs"])
        elif "lengthSeconds" in item:
            duration = _convertMillis(int(item["lengthSeconds"]) * 1000)
        else:
            duration = "00:00:00"
            logger.warn(f"duration missing: {item}")
    except Exception as e:
        logger.error(f"youtube_music yt_item_to_video duration error {e}: {item}")

    try:
        duration = "PT" + Client.format_duration(re.match(Client.time_regex, duration))
    except Exception as e:
        logger.error(
            f"youtube_music yt_item_to_video format duration error {e}: {item}"
        )

    try:
        if "artists" in item and item["artists"]:
            if isinstance(item["artists"], list):
                channelTitle = item["artists"][0]["name"]
            else:
                channelTitle = item["artists"]
        elif "byline" in item:
            logger.debug(f'byline: {item["byline"]}')
            channelTitle = item["byline"]
        elif "author" in item:
            channelTitle = item["author"]
        else:
            channelTitle = "unknown"
    except Exception as e:
        logger.error(f"youtube_music yt_item_to_video artists error {e}: {item}")

    # TODO: full support for thumbnails
    try:
        thumbnail = item["thumbnails"][-1]
    except Exception:
        thumbnail = item["thumbnail"]["thumbnails"][-1]

    video = {
        "id": {"kind": "youtube#video", "videoId": item["videoId"]},
        "contentDetails": {"duration": duration},
        "snippet": {
            "title": item["title"],
            "resourceId": {"kind": "youtube#video", "videoId": item["videoId"]},
            "thumbnails": {"default": thumbnail},
            "channelTitle": channelTitle,
        },
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
                "uri": f"yt:channel:{artist['id']}",
                # "thumbnail": ytmusic.get_artist(artist["id"])["thumbnails"][-1]
            }
            for artist in item["artists"]
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
