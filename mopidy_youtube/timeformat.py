import re


def convert_Millis(milliseconds):
    try:
        hours, miliseconds = divmod(int(milliseconds), 3600000)
    except Exception as e:
        logger.error(f"convert_Millis error: {e}, {milliseconds}")
        return "00:00:00"
    minutes, miliseconds = divmod(miliseconds, 60000)
    seconds = int(miliseconds) / 1000
    return "%i:%02i:%02i" % (hours, minutes, seconds)

def format_duration(duration_text):

    time_regex = (
        r"(?:(?:(?P<durationHours>[0-9]+)\:)?"
        r"(?P<durationMinutes>[0-9]+)\:"
        r"(?P<durationSeconds>[0-9]{2}))"
    )

    match = re.match(time_regex, duration_text)

    duration = ""
    if match.group("durationHours") is not None:
        duration += match.group("durationHours") + "H"
    if match.group("durationMinutes") is not None:
        duration += match.group("durationMinutes") + "M"
    if match.group("durationSeconds") is not None:
        duration += match.group("durationSeconds") + "S"

    return duration


def ISO8601_to_seconds(iso_duration):

    # convert PT1H2M10S to 3730
    m = re.search(
        r"P((?P<weeks>\d+)W)?"
        + r"((?P<days>\d+)D)?"
        + r"T((?P<hours>\d+)H)?"
        + r"((?P<minutes>\d+)M)?"
        + r"((?P<seconds>\d+)S)?",
        iso_duration,
    )
    if m:
        val = (
            int(m.group("weeks") or 0) * 604800
            + int(m.group("days") or 0) * 86400
            + int(m.group("hours") or 0) * 3600
            + int(m.group("minutes") or 0) * 60
            + int(m.group("seconds") or 0)
        )
    else:
        val = 0

    return val
