from __future__ import annotations

import pytest

from mopidy_youtube.timeformat import ISO8601_to_seconds, clock_to_seconds, iso_duration


@pytest.mark.parametrize(
    ("text", "seconds"),
    [("0:00", 0), ("0:59", 59), ("3:45", 225), ("12:05", 725), ("1:02:03", 3723)],
)
def test_a_clock_time_is_converted_to_seconds(text: str, seconds: int):
    assert clock_to_seconds(text) == seconds


@pytest.mark.parametrize("text", ["", "LIVE", "3", "3:4", "a:bc", "3:45 pm"])
def test_text_that_is_not_a_clock_time_is_rejected(text: str):
    with pytest.raises(ValueError, match="Invalid duration"):
        clock_to_seconds(text)


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0, "PT0S"),
        (1, "PT1S"),
        (60, "PT1M"),
        (225, "PT3M45S"),
        (3600, "PT1H"),
        (3723, "PT1H2M3S"),
        (90000, "PT25H"),
    ],
)
def test_seconds_are_written_as_an_iso_duration(seconds: int, expected: str):
    assert iso_duration(seconds) == expected


@pytest.mark.parametrize("seconds", [0, 1, 59, 60, 61, 3599, 3600, 3661, 86399])
def test_an_iso_duration_reads_back_as_the_seconds_it_was_made_from(seconds: int):
    assert ISO8601_to_seconds(iso_duration(seconds)) == seconds
