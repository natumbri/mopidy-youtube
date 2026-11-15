from __future__ import annotations

import re

_CLOCK = re.compile(r"(?:(\d+):)?(\d+):(\d{2})")


def clock_to_seconds(text: str) -> int:
    """Convert `3:45` or `1:02:03` to seconds; raise ValueError for anything else."""
    match = _CLOCK.fullmatch(text.strip())
    if match is None:
        msg = f"Invalid duration text: {text!r}"
        raise ValueError(msg)
    hours, minutes, seconds = match.groups()
    return int(hours or 0) * 3600 + int(minutes) * 60 + int(seconds)


def iso_duration(seconds: int) -> str:
    """Convert seconds to an ISO 8601 duration such as `PT1H2M3S`."""
    hours, rest = divmod(seconds, 3600)
    minutes, seconds = divmod(rest, 60)
    parts = [
        f"{value}{unit}"
        for value, unit in ((hours, "H"), (minutes, "M"), (seconds, "S"))
        if value
    ]
    return "PT" + "".join(parts) if parts else "PT0S"


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
