"""Tests for the conversion of YouTube Music items to Data API shaped videos.

The song, album track and `get_song` payloads are real ytmusicapi responses
(`tests/fixtures/music/`); the edge cases modify copies of them.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from mopidy_youtube.apis.ytm_item_to_video import ytm_item_to_video

from tests.support import load_fixture

NO_DURATION = "PT0H00M00S"


def fixture(name: str) -> Any:
    return load_fixture(f"music/{name}.json")


def convert(**fields: Any) -> dict[str, Any]:
    """Convert a minimal item (id and title) with the given extra fields."""
    return ytm_item_to_video({"videoId": "abc123defgh", "title": "Title", **fields})


def duration_of(**fields: Any) -> str:
    return convert(**fields)["contentDetails"]["duration"]


def channel_title_of(**fields: Any) -> str:
    return convert(**fields)["snippet"]["channelTitle"]


def test_a_song_search_result_becomes_a_video():
    song = fixture("search_songs")[0]

    video = ytm_item_to_video(song)

    assert video["id"] == {"kind": "youtube#video", "videoId": "BSTsnWoslP4"}
    assert video["snippet"]["resourceId"] == video["id"]
    assert video["snippet"]["title"] == "Bohemian Rhapsody"
    assert video["snippet"]["channelTitle"] == "Queen"
    assert video["contentDetails"]["duration"] == "PT5M55S"
    assert video["snippet"]["thumbnails"] == {"default": song["thumbnails"][-1]}
    assert video["artists"] == [
        {"name": "Queen", "uri": "yt:channel:UCEPMVbUzImPl4p8k4LkGevA"}
    ]
    assert video["album"] == {
        "name": "A Night At The Opera",
        "uri": "yt:playlist:MPREb_eEpQf8QskKl",
    }
    assert video["track_no"] is None


def test_a_get_song_response_is_read_from_its_video_details():
    response = fixture("songs")["fJ9rUzIMcZQ"]
    details = response["videoDetails"]

    video = ytm_item_to_video(response)

    assert video["id"]["videoId"] == "fJ9rUzIMcZQ"
    assert video["snippet"]["title"] == details["title"]
    assert video["snippet"]["channelTitle"] == "Queen"
    assert video["contentDetails"]["duration"] == "PT0H05M59S"
    assert (
        video["snippet"]["thumbnails"]["default"]
        == (details["thumbnail"]["thumbnails"][-1])
    )
    # no `artists` in videoDetails: the author and channel make the artist
    assert video["artists"] == [
        {"name": "Queen", "uri": "yt:channel:UCiMhD4jzUqG-IgPzUmmytRQ"}
    ]
    assert "album" not in video


def test_an_album_track_without_thumbnails_gets_an_empty_thumbnail():
    track = fixture("album")["tracks"][0]
    assert track["thumbnails"] is None
    del track["album"]  # a plain name; the playlist code replaces it by a dict

    video = ytm_item_to_video(track)

    assert video["snippet"]["thumbnails"] == {"default": {}}
    assert video["contentDetails"]["duration"] == "PT3M44S"
    assert video["snippet"]["title"] == "Death On Two Legs (Dedicated To...)"


def test_the_track_number_is_passed_through():
    assert convert(track_no=3)["track_no"] == 3


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        ({"duration": "3:44"}, "PT3M44S"),
        ({"duration": "1:02:03"}, "PT1H02M03S"),
        ({"length": "6:00"}, "PT6M00S"),
        ({"lengthMs": 225000}, "PT0H03M45S"),
        ({"lengthMs": "225000"}, "PT0H03M45S"),
        ({"lengthMs": 0}, NO_DURATION),
        ({"lengthSeconds": "359"}, "PT0H05M59S"),
        ({"song_duration": 225}, "PT0H03M45S"),
        # the first usable key wins
        ({"duration": "1:00", "lengthSeconds": "3600"}, "PT1M00S"),
        # empty values are skipped
        ({"duration": None, "length": "", "lengthSeconds": "61"}, "PT0H01M01S"),
        # as are numbers that cannot be parsed
        ({"lengthSeconds": "n/a", "lengthMs": 61000}, "PT0H01M01S"),
        ({"lengthSeconds": None, "song_duration": [1]}, NO_DURATION),
        ({"lengthMs": "n/a"}, NO_DURATION),
    ],
)
def test_the_duration_comes_from_the_first_usable_field(
    fields: dict[str, Any], expected: str
):
    assert duration_of(**fields) == expected


def test_a_missing_duration_is_zero_and_logged(caplog: pytest.LogCaptureFixture):
    with caplog.at_level(logging.WARNING, logger="mopidy_youtube"):
        assert duration_of() == NO_DURATION

    assert "duration missing" in caplog.text


def test_an_unparsable_duration_is_zero_and_logged(caplog: pytest.LogCaptureFixture):
    with caplog.at_level(logging.ERROR, logger="mopidy_youtube"):
        assert duration_of(duration="LIVE") == NO_DURATION

    assert "duration error" in caplog.text


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        ({"artists": [{"name": "A", "id": "1"}, {"name": "B", "id": "2"}]}, "A"),
        ({"artists": "Plain Artist"}, "Plain Artist"),
        # an empty artist list falls through to the next candidate
        ({"artists": [], "author": "Uploader"}, "Uploader"),
        ({"artists": None, "byline": "By Line"}, "By Line"),
        ({"byline": "By Line", "author": "Uploader"}, "By Line"),
        ({"author": "Uploader"}, "Uploader"),
        ({}, "unknown"),
    ],
)
def test_the_channel_title_prefers_artists_then_byline_then_author(
    fields: dict[str, Any], expected: str
):
    assert channel_title_of(**fields) == expected


def test_artists_become_channel_links_without_the_type_labels():
    video = convert(
        artists=[
            {"name": "Song", "id": None},
            {"name": "Queen", "id": "UCEPMVbUzImPl4p8k4LkGevA"},
            {"name": "Album", "id": None},
        ]
    )

    assert video["artists"] == [
        {"name": "Queen", "uri": "yt:channel:UCEPMVbUzImPl4p8k4LkGevA"}
    ]


def test_an_artist_without_an_id_has_no_uri():
    video = convert(artists=[{"name": "Lex Fridman", "id": None}])

    assert video["artists"] == [{"name": "Lex Fridman", "uri": None}]


@pytest.mark.parametrize("artists", [[{"id": "UC1"}], ["Queen"]])
def test_artists_that_cannot_be_read_leave_the_channel_title_unknown(
    artists: list[Any], caplog: pytest.LogCaptureFixture
):
    with caplog.at_level(logging.ERROR, logger="mopidy_youtube"):
        video = convert(artists=artists)

    assert video["snippet"]["channelTitle"] == "unknown"
    assert video["artists"] == []
    assert "artists error" in caplog.text


def test_an_artist_given_as_plain_text_is_only_the_channel_title():
    video = convert(artists="Plain Artist")

    assert video["snippet"]["channelTitle"] == "Plain Artist"
    assert "artists" not in video


def test_an_author_with_a_channel_id_is_the_artist():
    video = convert(author="Uploader", channelId="UC123")

    assert video["artists"] == [{"name": "Uploader", "uri": "yt:channel:UC123"}]


def test_an_author_without_a_channel_id_gives_no_artists():
    assert "artists" not in convert(author="Uploader")


@pytest.mark.parametrize("fields", [{}, {"album": None}])
def test_a_missing_album_is_left_out(fields: dict[str, Any]):
    assert "album" not in convert(**fields)


def test_the_album_becomes_a_playlist_link():
    video = convert(album={"name": "An Album", "id": "MPREb_1"})

    assert video["album"] == {"name": "An Album", "uri": "yt:playlist:MPREb_1"}


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        (
            {"thumbnails": [{"url": "small"}, {"url": "large"}]},
            {"url": "large"},
        ),
        (
            {"thumbnail": {"thumbnails": [{"url": "a"}, {"url": "b"}]}},
            {"url": "b"},
        ),
        # `thumbnails` wins over `thumbnail` unless it is empty
        (
            {"thumbnails": [{"url": "x"}], "thumbnail": {"thumbnails": [{"url": "y"}]}},
            {"url": "x"},
        ),
        (
            {"thumbnails": [], "thumbnail": {"thumbnails": [{"url": "y"}]}},
            {"url": "y"},
        ),
        ({"thumbnails": None}, {}),
        ({"thumbnails": []}, {}),
        ({}, {}),
    ],
)
def test_the_thumbnail_is_the_last_of_the_available_ones(
    fields: dict[str, Any], expected: dict[str, Any]
):
    assert convert(**fields)["snippet"]["thumbnails"] == {"default": expected}
