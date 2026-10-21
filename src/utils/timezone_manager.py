import re
from datetime import datetime, timedelta, timezone

from utils.utils import read_config

_OVERRIDE_TIMEZONE = None
_OVERRIDE_DISPLAY_NAME = None


def parse_timezone(val: str | int | float | None) -> tuple[timezone, str]:
    """
    Parses a timezone configuration into a datetime.tzinfo object and a human-readable display string.
    Supports formats like:
      - 'UTC+8', 'UTC+08:00', '+8', '+08:00'
      - 'UTC-5', '-5', '-05:00'
      - 'Asia/Manila', 'Philippines', 'PHT'
      - Numbers: 8, 8.0, -5
    Defaults to UTC+8 (Philippines Standard Time).
    """
    if val is None or val == "":
        val = "UTC+8"

    if isinstance(val, (int, float)):
        offset_hours = float(val)
        tz = timezone(timedelta(hours=offset_hours))
        sign = "+" if offset_hours >= 0 else "-"
        return tz, f"UTC{sign}{int(abs(offset_hours)):02d}:00"

    val_str = str(val).strip()

    aliases = {
        "philippines": (timezone(timedelta(hours=8)), "UTC+08:00 (PHT)"),
        "asia/manila": (timezone(timedelta(hours=8)), "UTC+08:00 (PHT)"),
        "pht": (timezone(timedelta(hours=8)), "UTC+08:00 (PHT)"),
        "utc": (timezone.utc, "UTC"),
        "gmt": (timezone.utc, "GMT"),
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

    # Default fallback: Philippines UTC+8
    return timezone(timedelta(hours=8)), "UTC+08:00 (PHT)"


def set_configured_timezone(tz_value: str | int | float | None):
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
    tz_val = cfg.get("timezone", "UTC+8")
    tz, _ = parse_timezone(tz_val)
    return tz


def get_timezone_display_name() -> str:
    """Returns a friendly display string for the configured timezone (e.g. 'UTC+08:00')."""
    if _OVERRIDE_DISPLAY_NAME is not None:
        return _OVERRIDE_DISPLAY_NAME
    cfg = read_config()
    tz_val = cfg.get("timezone", "UTC+8")
    _, name = parse_timezone(tz_val)
    return name


def get_configured_now() -> datetime:
    """Returns current datetime in the configured timezone."""
    tz = get_configured_timezone()
    return datetime.now(timezone.utc).astimezone(tz)


def format_configured_time(
    fmt: str = "%Y-%m-%d-%H-%M-%S", timestamp: float | None = None
) -> str:
    """Formats a timestamp (or current time) using the configured timezone."""
    tz = get_configured_timezone()
    if timestamp is not None:
        dt = datetime.fromtimestamp(timestamp, tz=timezone.utc).astimezone(tz)
    else:
        dt = datetime.now(timezone.utc).astimezone(tz)
    return dt.strftime(fmt)


def get_logging_time_converter():
    """
    Returns a converter function for logging.Formatter.converter
    so that %(asctime)s displays in the configured timezone.
    """

    def converter(secs):
        tz = get_configured_timezone()
        dt = datetime.fromtimestamp(secs, tz=timezone.utc).astimezone(tz)
        return dt.timetuple()

    return converter
