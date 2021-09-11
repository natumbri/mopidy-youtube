import re

uri_video_regex = re.compile("^(?:youtube|yt):video:(?P<videoid>.+)$")
uri_playlist_regex = re.compile("^(?:youtube|yt):playlist:(?P<playlistid>.+)$")
uri_channel_regex = re.compile("^(?:youtube|yt):channel:(?P<channelid>.+)$")

old_uri_video_regex = re.compile(
    r"^(?:youtube|yt):video/(?:.+)\.(?P<videoid>.+)$"
)
old_uri_playlist_regex = re.compile(
    r"^(?:youtube|yt):playlist/(?:.+)\.(?P<playlistid>.+)$"
)
old_uri_channel_regex = re.compile(
    r"^(?:youtube|yt):channel/(?:.+)\.(?P<channelid>.+)$"
)


def format_video_uri(video) -> str:
    return f"youtube:video:{video.id}"


def format_playlist_uri(playlist) -> str:
    return f"youtube:playlist:{playlist.id}"


def format_channel_uri(channel) -> str:
    return f"youtube:channel:{channel.id}"


def extract_video_id(uri) -> str:
    for regex in (uri_video_regex, old_uri_video_regex):
        match = regex.match(uri)
        if match:
            return match.group("videoid")
    return ""


def extract_playlist_id(uri) -> str:
    for regex in (uri_playlist_regex, old_uri_playlist_regex):
        match = regex.match(uri)
        if match:
            return match.group("playlistid")
    return ""


def extract_channel_id(uri) -> str:
    for regex in (uri_channel_regex, old_uri_channel_regex):
        match = regex.match(uri)
        if match:
            return match.group("channelid")
    return ""
