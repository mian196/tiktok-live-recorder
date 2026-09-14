import json
import os

from utils.enums import Info


def banner() -> None:
    """
    Prints a banner with the name of the tool and its version number.
    """
    print(Info.BANNER, flush=True)


def _get_config_path(filename: str) -> str:
    """Find path to a config file, checking configs/ first, then src/."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    primary_path = os.path.abspath(
        os.path.join(script_dir, "..", "..", "configs", filename)
    )
    if os.path.exists(primary_path):
        return primary_path
    legacy_path = os.path.abspath(os.path.join(script_dir, "..", filename))
    if os.path.exists(legacy_path):
        return legacy_path
    return primary_path


def read_cookies():
    """
    Loads the cookies config file and returns it.
    """
    config_path = _get_config_path("cookies.json")
    if not os.path.exists(config_path):
        return {}
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def read_telegram_config():
    """
    Loads the telegram config file and returns it.
    """
    config_path = _get_config_path("telegram.json")
    if not os.path.exists(config_path):
        return {}
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def read_config():
    """
    Loads the main config.json file and returns it as a dict.
    """
    config_path = _get_config_path("config.json")
    if not os.path.exists(config_path):
        return {}
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def save_config(config_dict: dict) -> bool:
    """
    Saves config_dict to config.json atomically to prevent corrupted files on crash.
    """
    config_path = _get_config_path("config.json")
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    temp_path = f"{config_path}.tmp.{os.getpid()}"
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(config_dict, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(temp_path, config_path)
        return True
    except Exception:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
        return False


def update_tracked_users_in_config(tracked_users: list) -> bool:
    """
    Updates the 'user' / 'users' field in config.json by merging / upserting TrackedUser dicts
    so existing users in config.json are never deleted.
    """
    from utils.user_identity import parse_tracked_users, TrackedUser

    cfg = read_config()
    if not cfg:
        return False

    # Extract existing users from config.json
    existing_raw = cfg.get("users") if "users" in cfg else cfg.get("user")
    existing_users = parse_tracked_users(existing_raw)

    # Convert incoming tracked_users to TrackedUser objects if not already
    new_users = []
    for item in tracked_users:
        if isinstance(item, TrackedUser):
            new_users.append(item)
        else:
            u = TrackedUser.from_item(item)
            if u:
                new_users.append(u)

    # Merge / upsert without deleting existing entries
    for new_u in new_users:
        matched = False
        for ex_u in existing_users:
            if (
                (new_u.sec_uid and ex_u.sec_uid and new_u.sec_uid == ex_u.sec_uid)
                or (new_u.user_id and ex_u.user_id and new_u.user_id == ex_u.user_id)
                or (new_u.username.lower() == ex_u.username.lower())
            ):
                ex_u.username = new_u.username
                if new_u.sec_uid:
                    ex_u.sec_uid = new_u.sec_uid
                if new_u.user_id:
                    ex_u.user_id = new_u.user_id
                matched = True
                break
        if not matched:
            existing_users.append(new_u)

    merged_data = [u.to_dict() for u in existing_users]

    if "users" in cfg:
        cfg["users"] = merged_data
    elif len(merged_data) == 1 and not isinstance(existing_raw, list):
        cfg["user"] = merged_data[0]
    else:
        cfg["user"] = merged_data

    return save_config(cfg)


def is_termux() -> bool:
    """
    Checks if the script is running in Termux.

    Returns:
        bool: True if running in Termux, False otherwise.
    """
    import distro
    import platform

    return platform.system().lower() == "linux" and distro.like() == ""


def is_windows() -> bool:
    """
    Checks if the script is running on Windows.

    Returns:
        bool: True if running on Windows, False otherwise.
    """
    import platform

    return platform.system().lower() == "windows"


def is_linux() -> bool:
    """
    Checks if the script is running on Linux.

    Returns:
        bool: True if running on Linux, False otherwise.
    """
    import platform

    return platform.system().lower() == "linux"
