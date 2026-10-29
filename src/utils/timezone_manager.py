import re
from datetime import UTC, datetime, timedelta, timezone

from utils.utils import read_config

_OVERRIDE_TIMEZONE = None
_OVERRIDE_DISPLAY_NAME = None


def _get_new_york_timezone() -> tuple[timezone, str]:
    """Returns New York timezone taking Daylight Saving Time (EDT vs EST) into account."""
    now_utc = datetime.now(UTC)
    year = now_utc.year
    march_first = datetime(year, 3, 1, tzinfo=UTC)
    dst_start = datetime(year, 3, 8 + (6 - march_first.weekday()) % 7, 2, tzinfo=UTC)
    nov_first = datetime(year, 11, 1, tzinfo=UTC)
    dst_end = datetime(year, 11, 1 + (6 - nov_first.weekday()) % 7, 2, tzinfo=UTC)

    if dst_start <= now_utc < dst_end:
        return timezone(timedelta(hours=-4)), "UTC-04:00 (EDT)"
    else:
        return timezone(timedelta(hours=-5)), "UTC-05:00 (EST)"


def parse_timezone(val: str | float | None) -> tuple[timezone, str]:
    """
    Parses a timezone configuration into a datetime.tzinfo object and a human-readable display string.
    Supports formats like:
      - 'UTC-5', 'UTC-05:00', '-5', '-05:00'
      - 'UTC+8', '+8', '+08:00'
      - 'America/New_York', 'New York', 'EST', 'EDT'
      - Numbers: -5, -4, 8
    Defaults to New York (America/New_York).
    """
    if val is None or val == "":
        return _get_new_york_timezone()

    if isinstance(val, (int, float)):
        offset_hours = float(val)
        tz = timezone(timedelta(hours=offset_hours))
        sign = "+" if offset_hours >= 0 else "-"
        return tz, f"UTC{sign}{int(abs(offset_hours)):02d}:00"

    val_str = str(val).strip()

    clean_key = val_str.lower().replace(" ", "").replace("_", "")
    if clean_key in {"newyork", "americanewyork", "useastern", "eastern"}:
        return _get_new_york_timezone()

    aliases = {
        "est": (timezone(timedelta(hours=-5)), "UTC-05:00 (EST)"),
        "edt": (timezone(timedelta(hours=-4)), "UTC-04:00 (EDT)"),
        "utc": (UTC, "UTC"),
        "gmt": (UTC, "GMT"),
    }
    if val_str.lower() in aliases:
        return aliases[val_str.lower()]

    try:
        import zoneinfo

        tz = zoneinfo.ZoneInfo(val_str)
        return tz, val_str
    except Exception:
        pass

    # Regex matching: UTC+8, UTC-5, +08:00, -0500, +8, -5
    m = re.match(
        r"^(?:UTC|GMT)?\s*([+-])?\s*(\d{1,2})(?::?(\d{2}))?$",
        val_str,
        re.IGNORECASE,
    )
    if m:
        sign = -1 if m.group(1) == "-" else 1
        hours = int(m.group(2))
        mins = int(m.group(3)) if m.group(3) else 0
        total_mins = sign * (hours * 60 + mins)
        tz = timezone(timedelta(minutes=total_mins))
        sign_char = "+" if total_mins >= 0 else "-"
        display = (
            f"UTC{sign_char}{abs(total_mins) // 60:02d}:{abs(total_mins) % 60:02d}"
        )
        return tz, display

    # Default fallback: New York
    return _get_new_york_timezone()


def set_configured_timezone(tz_value: str | float | None):
    """Sets a global runtime override for the configured timezone."""
    global _OVERRIDE_TIMEZONE, _OVERRIDE_DISPLAY_NAME
    if tz_value is None:
        _OVERRIDE_TIMEZONE = None
        _OVERRIDE_DISPLAY_NAME = None
    else:
        _OVERRIDE_TIMEZONE, _OVERRIDE_DISPLAY_NAME = parse_timezone(tz_value)


def get_configured_timezone() -> timezone:
    """Returns the configured tzinfo object."""
    if _OVERRIDE_TIMEZONE is not None:
        return _OVERRIDE_TIMEZONE
    cfg = read_config()
    tz_val = cfg.get("timezone", "New York")
    tz, _ = parse_timezone(tz_val)
    return tz


def get_timezone_display_name() -> str:
    """Returns a friendly display string for the configured timezone (e.g. 'UTC-04:00')."""
    if _OVERRIDE_DISPLAY_NAME is not None:
        return _OVERRIDE_DISPLAY_NAME
    cfg = read_config()
    tz_val = cfg.get("timezone", "New York")
    _, name = parse_timezone(tz_val)
    return name


def get_configured_now() -> datetime:
    """Returns current datetime in the configured timezone."""
    tz = get_configured_timezone()
    return datetime.now(UTC).astimezone(tz)


def format_configured_time(
    fmt: str = "%Y-%m-%d-%H-%M-%S", timestamp: float | None = None
) -> str:
    """Formats a timestamp (or current time) using the configured timezone."""
    tz = get_configured_timezone()
    if timestamp is not None:
        dt = datetime.fromtimestamp(timestamp, tz=UTC).astimezone(tz)
    else:
        dt = datetime.now(UTC).astimezone(tz)
    return dt.strftime(fmt)


def get_logging_time_converter():
    """
    Returns a converter function for logging.Formatter.converter
    so that %(asctime)s displays in the configured timezone.
    """

    def converter(secs):
        tz = get_configured_timezone()
        dt = datetime.fromtimestamp(secs, tz=UTC).astimezone(tz)
        return dt.timetuple()

    return converter
