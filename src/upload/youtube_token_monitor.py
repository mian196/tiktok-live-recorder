import hashlib
import json
import os
import threading
import time
from pathlib import Path

from utils.logger_manager import logger
from utils.timezone_manager import format_configured_time, get_timezone_display_name
from utils.utils import _get_config_path, read_config

try:
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    HAS_GOOGLE_AUTH = True
except ImportError:
    HAS_GOOGLE_AUTH = False
    RefreshError = Exception

from upload.youtube import SCOPES, YouTube

DEFAULT_TOKEN_LIFETIME_DAYS = 7.0
DEFAULT_CHECK_INTERVAL_HOURS = 12.0
DEFAULT_REMIND_BEFORE_HOURS = 168.0


def _get_state_path(state_path: str | None = None) -> str:
    """Return path to the persistent YouTube token state JSON file."""
    return state_path or _get_config_path("youtube_token_state.json")


def _load_state(state_path: str | None = None) -> dict:
    path = _get_state_path(state_path)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.debug(f"Could not load YouTube token state: {e}")
        return {}


def _save_state(state: dict, state_path: str | None = None) -> None:
    path = _get_state_path(state_path)
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        temp_path = f"{path}.tmp.{os.getpid()}"
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
        os.replace(temp_path, path)
    except Exception as e:
        logger.warning(f"Could not save YouTube token state: {e}")


def _compute_token_fingerprint(storage_path: str) -> str | None:
    """Compute a stable SHA-256 fingerprint for the refresh token (or file bytes)."""
    if not os.path.exists(storage_path):
        return None
    try:
        raw = Path(storage_path).read_bytes()
        try:
            parsed = json.loads(raw.decode("utf-8"))
            if isinstance(parsed, dict) and parsed.get("refresh_token"):
                return hashlib.sha256(
                    parsed["refresh_token"].encode("utf-8")
                ).hexdigest()
        except Exception:
            pass
        return hashlib.sha256(raw).hexdigest()
    except OSError:
        return None


def _format_ts(ts: float | None) -> str:
    if ts is None:
        return "Unknown"
    tz_name = get_timezone_display_name()
    return f"{format_configured_time('%Y-%m-%d %H:%M:%S', timestamp=ts)} ({tz_name})"


def _format_duration(seconds: float) -> str:
    """Format a duration in seconds into a human-readable string."""
    abs_secs = int(abs(seconds))
    days, rem = divmod(abs_secs, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours or days:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    text = " ".join(parts)
    return f"in {text}" if seconds >= 0 else f"{text} ago"


def record_token_issued(
    storage_path: str,
    issued_at: float | None = None,
    lifetime_days: float | None = None,
    state_path: str | None = None,
) -> dict | None:
    """Record or update the issuance and expected expiration time for a token file."""
    fingerprint = _compute_token_fingerprint(storage_path)
    if not fingerprint:
        return None

    if lifetime_days is None:
        notif_cfg = read_config().get("notifications", {})
        lifetime_days = float(
            notif_cfg.get("youtube_token_lifetime_days", DEFAULT_TOKEN_LIFETIME_DAYS)
        )

    issued_ts = issued_at if issued_at is not None else time.time()
    expires_ts = issued_ts + (lifetime_days * 86400.0)

    state = _load_state(state_path)
    key = os.path.abspath(storage_path)
    entry = {
        "token_hash": fingerprint,
        "issued_at": issued_ts,
        "expires_at": expires_ts,
        "lifetime_days": lifetime_days,
    }
    state[key] = entry
    _save_state(state, state_path)
    return entry


def get_token_expiry_info(
    storage_path: str,
    lifetime_days: float | None = None,
    state_path: str | None = None,
) -> tuple[float | None, float | None, float | None]:
    """
    Return (issued_at, expires_at, remaining_seconds) for a token file.
    Automatically detects when a new token file is placed on disk.
    """
    fingerprint = _compute_token_fingerprint(storage_path)
    if not fingerprint:
        return None, None, None

    if lifetime_days is None:
        notif_cfg = read_config().get("notifications", {})
        lifetime_days = float(
            notif_cfg.get("youtube_token_lifetime_days", DEFAULT_TOKEN_LIFETIME_DAYS)
        )

    state = _load_state(state_path)
    key = os.path.abspath(storage_path)
    entry = state.get(key)

    if not isinstance(entry, dict) or entry.get("token_hash") != fingerprint:
        # New or replaced token detected on disk; anchor issued_at to file mtime
        try:
            file_mtime = os.path.getmtime(storage_path)
        except OSError:
            file_mtime = time.time()
        entry = record_token_issued(
            storage_path,
            issued_at=file_mtime,
            lifetime_days=lifetime_days,
            state_path=state_path,
        )

    if not entry:
        return None, None, None

    issued_at = float(entry["issued_at"])
    expires_at = float(entry["expires_at"])
    remaining = expires_at - time.time()
    return issued_at, expires_at, remaining


def check_project_token(
    project: dict,
    lifetime_days: float | None = None,
    verify_refresh: bool = True,
    state_path: str | None = None,
) -> dict:
    """
    Check a single YouTube project's OAuth token status and compute exact expiry time.
    Returns a dict with status ('valid', 'expired', 'missing', 'error') and metadata.
    """
    name = project.get("name", "Default")
    storage_path = project.get("credentials_storage_path", "")
    result = {
        "project": name,
        "token_file": storage_path,
        "status": "unknown",
        "error": None,
        "issued_at": None,
        "expires_at": None,
        "expires_at_str": "Unknown",
        "remaining_seconds": None,
        "remaining_str": "",
    }

    if not storage_path or not os.path.exists(storage_path):
        result["status"] = "missing"
        result["error"] = f"Token file not found: {storage_path}"
        return result

    issued_at, expires_at, remaining = get_token_expiry_info(
        storage_path, lifetime_days=lifetime_days, state_path=state_path
    )
    result["issued_at"] = issued_at
    result["expires_at"] = expires_at
    result["expires_at_str"] = _format_ts(expires_at)
    result["remaining_seconds"] = remaining
    result["remaining_str"] = (
        _format_duration(remaining) if remaining is not None else ""
    )

    if not HAS_GOOGLE_AUTH:
        result["status"] = "error"
        result["error"] = "Google auth libraries are not installed."
        return result

    try:
        creds = Credentials.from_authorized_user_file(storage_path, SCOPES)
    except Exception as e:
        result["status"] = "expired"
        result["error"] = f"Failed to parse token file: {e}"
        return result

    if not creds or not creds.refresh_token:
        result["status"] = "expired"
        result["error"] = "Token file has no refresh_token; re-authentication required."
        return result

    if verify_refresh:
        try:
            creds.refresh(Request())
        except RefreshError as e:
            result["status"] = "expired"
            result["error"] = f"Refresh token expired or revoked: {e}"
            return result
        except Exception as e:
            err_lower = str(e).lower()
            if "invalid_grant" in err_lower or "expired or revoked" in err_lower:
                result["status"] = "expired"
                result["error"] = f"Refresh token expired or revoked: {e}"
            else:
                result["status"] = "error"
                result["error"] = f"Could not verify token with Google: {e}"
            return result

    result["status"] = "valid"
    return result


def check_all_youtube_tokens(
    yt: YouTube | None = None,
    notifier=None,
    remind_before_hours: float | None = None,
    notify: bool = True,
    verify_refresh: bool = True,
    state_path: str | None = None,
) -> list[dict]:
    """
    Check all configured YouTube projects and dispatch notifications for expired
    tokens or upcoming expiration reminders.
    """
    yt = yt or YouTube()
    notif_cfg = read_config().get("notifications", {})
    if remind_before_hours is None:
        remind_before_hours = float(
            notif_cfg.get(
                "youtube_token_remind_before_hours", DEFAULT_REMIND_BEFORE_HOURS
            )
        )

    if notify and notifier is None:
        from notify.notifier import Notifier

        notifier = Notifier()

    results = []
    for project in yt.projects:
        res = check_project_token(
            project, verify_refresh=verify_refresh, state_path=state_path
        )
        results.append(res)

        if not notify or notifier is None:
            continue

        if res["status"] in ("expired", "missing"):
            notifier.notify(
                "youtube_token_expired",
                project=res["project"],
                error=res["error"] or "Token is expired or missing.",
                expires_at=res["expires_at_str"] if res["expires_at"] else "",
                token_file=res["token_file"],
            )
        elif res["status"] == "valid":
            remaining = res["remaining_seconds"]
            if remaining is not None and (remaining / 3600.0) <= remind_before_hours:
                notifier.notify(
                    "youtube_token_expiring",
                    project=res["project"],
                    expires_at=res["expires_at_str"],
                    remaining=res["remaining_str"],
                    token_file=res["token_file"],
                )

    return results


def run_monitor_loop(
    interval_hours: float = DEFAULT_CHECK_INTERVAL_HOURS,
    remind_before_hours: float | None = None,
    notify: bool = True,
    stop_event: threading.Event | None = None,
) -> None:
    """Continuously check YouTube token status every `interval_hours`."""
    stop_event = stop_event or threading.Event()
    interval_seconds = max(60.0, float(interval_hours) * 3600.0)
    logger.info(
        f"[YouTube Token Monitor] Started (checking every {interval_hours:g} hours)."
    )

    while not stop_event.is_set():
        try:
            results = check_all_youtube_tokens(
                remind_before_hours=remind_before_hours,
                notify=notify,
            )
            for res in results:
                if res["status"] == "valid":
                    logger.info(
                        f"[YouTube Token Monitor] [{res['project']}] VALID — expires {res['expires_at_str']} ({res['remaining_str']})"
                    )
                else:
                    logger.warning(
                        f"[YouTube Token Monitor] [{res['project']}] {res['status'].upper()} — {res['error']}"
                    )
        except Exception as e:
            logger.error(f"[YouTube Token Monitor] Check failed: {e}")

        if stop_event.wait(timeout=interval_seconds):
            break
