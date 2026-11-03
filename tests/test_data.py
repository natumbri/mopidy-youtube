import json

from mopidy_youtube import Extension
from mopidy_youtube.data import (
    extract_playlist_id,
    extract_preload_tracks,
    extract_video_id,
)


def test_default_config_uses_yt_dlp_backend():
    config = Extension().get_default_config()

    assert "youtube_dl_package = yt_dlp" in config


def test_extract_video_id_handles_standard_uri_variants():
    assert extract_video_id("youtube:video:nvlTJrNJ5lA") == "nvlTJrNJ5lA"
    assert (
        extract_video_id("https://www.youtube.com/watch?v=nvlTJrNJ5lA") == "nvlTJrNJ5lA"
    )
    assert extract_video_id("https://youtu.be/nvlTJrNJ5lA") == "nvlTJrNJ5lA"


def test_extract_playlist_id_handles_standard_uri_variants():
    assert (
        extract_playlist_id(
            "youtube:https://www.youtube.com/watch?v=SIhb-kNvL6M&list=PLo4c-riVwz2miWOT3Y2VWzg2bmV4FmC8J"
        )
        == "PLo4c-riVwz2miWOT3Y2VWzg2bmV4FmC8J"
    )
    assert (
        extract_playlist_id("yt:playlist:PLo4c-riVwz2miWOT3Y2VWzg2bmV4FmC8J")
        == "PLo4c-riVwz2miWOT3Y2VWzg2bmV4FmC8J"
    )


def test_extract_preload_tracks_decodes_preload_payload():
    payload = [
        {
            "videoId": "abc123defgh",
            "title": "Example Title",
            "length": "00:03:45",
            "artists": [{"name": "Example Artist", "id": "artist123"}],
            "thumbnails": [{"url": "https://example.com/thumb.jpg"}],
            "author": "Example Artist",
        }
    ]
    encoded = json.dumps(payload).encode("utf-8").hex()

    result = extract_preload_tracks(f"youtube:video:nvlTJrNJ5lA:preload:{encoded}")

    assert result["videoUri"] == "youtube:video:nvlTJrNJ5lA"
    assert result["preloadTracks"][0]["id"]["videoId"] == "abc123defgh"
