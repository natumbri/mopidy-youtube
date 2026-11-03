from __future__ import annotations

import re

from mopidy_youtube import logger


def convert_Millis(milliseconds: float | str) -> str:
    try:
        hours, miliseconds = divmod(int(milliseconds), 3600000)
    except Exception as e:
        logger.error(f"convert_Millis error: {e}, {milliseconds}")
        return "00:00:00"
    minutes, miliseconds = divmod(miliseconds, 60000)
    seconds = int(miliseconds) / 1000
    return f"{hours}:{minutes:02}:{int(seconds):02}"


def format_duration(duration_text: str) -> str:
    time_regex = (
        r"(?:(?:(?P<durationHours>[0-9]+)\:)?"
        r"(?P<durationMinutes>[0-9]+)\:"
        r"(?P<durationSeconds>[0-9]{2}))"
    )

    match = re.match(time_regex, duration_text)
    if match is None:
        msg = f"Invalid duration text: {duration_text!r}"
        raise ValueError(msg)

    duration = ""
    if match.group("durationHours") is not None:
        duration += match.group("durationHours") + "H"
    if match.group("durationMinutes") is not None:
        duration += match.group("durationMinutes") + "M"
    if match.group("durationSeconds") is not None:
        duration += match.group("durationSeconds") + "S"

    return duration


def ISO8601_to_seconds(iso_duration: str) -> int:
    # convert PT1H2M10S to 3730
    match = re.search(
        r"P((?P<weeks>\d+)W)?"
        r"((?P<days>\d+)D)?"
        r"T((?P<hours>\d+)H)?"
        r"((?P<minutes>\d+)M)?"
        r"((?P<seconds>\d+)S)?",
        iso_duration,
    )
    if match:
        val = (
            int(match.group("weeks") or 0) * 604800
            + int(match.group("days") or 0) * 86400
            + int(match.group("hours") or 0) * 3600
            + int(match.group("minutes") or 0) * 60
            + int(match.group("seconds") or 0)
        )
    else:
        val = 0

    return val
