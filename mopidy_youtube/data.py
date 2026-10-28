from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import parse_qs, urlparse

from mopidy.types import Uri

from mopidy_youtube.apis.ytm_item_to_video import ytm_item_to_video

uri_video_regex = re.compile("^(?:youtube|yt):video:(?P<videoid>.{11})$")
uri_playlist_regex = re.compile("^(?:youtube|yt):playlist:(?P<playlistid>.+)$")
uri_channel_regex = re.compile("^(?:youtube|yt):channel:(?P<channelid>.+)$")
uri_preload_regex = re.compile(
    "^(?:youtube|yt):video:(?P<videoid>.{11}):preload:(?P<preload_data>.+)$"
)


def format_video_uri(id: str) -> Uri:
    return Uri(f"youtube:video:{id}")


def format_playlist_uri(id: str) -> Uri:
    return Uri(f"youtube:playlist:{id}")


def format_channel_uri(id: str) -> Uri:
    return Uri(f"youtube:channel:{id}")


def extract_video_id(uri: str | None) -> str:
    if uri is None:
        return ""
    if "youtube.com" in uri:
        url = urlparse(uri.replace("yt:", "").replace("youtube:", ""))
        req = parse_qs(url.query)
        if "v" in req:
            return req["v"][0]
    elif "youtu.be" in uri:
        url_str = uri.replace("yt:", "").replace("youtube:", "")
        if not re.match("^(?:http|https)://", url_str):
            url_str = "https://" + url_str
        video_id = urlparse(url_str).path
        if video_id[0] == "/":
            return video_id[1:]
    match = uri_video_regex.match(uri)
    if match:
        return match.group("videoid")
    return ""


def extract_playlist_id(uri: str) -> str:
    if "youtube.com" in uri:
        url = urlparse(uri.replace("yt:", "").replace("youtube:", ""))
        req = parse_qs(url.query)
        if "list" in req:
            return req["list"][0]
    match = uri_playlist_regex.match(uri)
    if match:
        return match.group("playlistid")
    return ""


def extract_channel_id(uri: str) -> str:
    match = uri_channel_regex.match(uri)
    if match:
        return match.group("channelid")
    return ""


def extract_preload_tracks(uri: str) -> dict[str, Any]:
    match = uri_preload_regex.match(uri)
    if match:
        preload_data = json.loads(
            bytes.fromhex(match.group("preload_data")).decode("utf-8")
        )
        preload_tracks = [
            ytm_item_to_video(track) for track in preload_data if "videoId" in track
        ]
        return {
            "videoUri": format_video_uri(match.group("videoid")),
            "preloadTracks": preload_tracks,
        }
    return {}
