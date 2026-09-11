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
