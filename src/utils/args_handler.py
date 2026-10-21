import argparse
import re

from utils.custom_exceptions import ArgsParseError
from utils.enums import Mode, Regex
from utils.user_identity import parse_tracked_users


def parse_interval(val) -> float:
    """
    Parses an interval into minutes as a float.
    Supports units such as '30s' (seconds), '1m' (minutes), '1h' (hours),
    or plain numbers (treated as minutes for backward compatibility).
    """
    if val is None:
        return 5.0
    if isinstance(val, (int, float)):
        return float(val)

    val_str = str(val).strip().lower()
    if val_str.endswith("hours"):
        return float(val_str[:-5].strip()) * 60.0
    if val_str.endswith("hour"):
        return float(val_str[:-4].strip()) * 60.0
    if val_str.endswith("h"):
        return float(val_str[:-1].strip()) * 60.0
    if val_str.endswith("seconds"):
        return float(val_str[:-7].strip()) / 60.0
    if val_str.endswith("second"):
        return float(val_str[:-6].strip()) / 60.0
    if val_str.endswith("sec"):
        return float(val_str[:-3].strip()) / 60.0
    if val_str.endswith("s"):
        return float(val_str[:-1].strip()) / 60.0
    if val_str.endswith("minutes"):
        return float(val_str[:-7].strip())
    if val_str.endswith("minute"):
        return float(val_str[:-6].strip())
    if val_str.endswith("min"):
        return float(val_str[:-3].strip())
    if val_str.endswith("m"):
        return float(val_str[:-1].strip())

    return float(val_str)


def parse_args():
    """
    Parse command line arguments.
    """
    parser = argparse.ArgumentParser(
        description="TikTok Live Recorder - A tool for recording live TikTok sessions.",
        formatter_class=argparse.RawTextHelpFormatter,
    )

    parser.add_argument(
        "-url",
        dest="url",
        help="Record a live session from the TikTok URL.",
        action="store",
    )

    parser.add_argument(
        "-user",
        dest="user",
        help="Record a live session from the TikTok username.",
        action="store",
    )

    parser.add_argument(
        "-room_id",
        dest="room_id",
        help="Record a live session from the TikTok room ID.",
        action="store",
    )

    parser.add_argument(
        "-mode",
        dest="mode",
        help=(
            "Recording mode: (manual, automatic, followers) [Default: manual]\n"
            "[manual] => Manual live recording.\n"
            "[automatic] => Automatic live recording when the user is live.\n"
            "[followers] => Automatic live recording of followed users."
        ),
        default="manual",
        action="store",
    )

    parser.add_argument(
        "-automatic_interval",
        dest="automatic_interval",
        help="Sets the polling interval in automatic mode (e.g. '30s' for 30 seconds, '1m' for 1 minute). [Default: 5]",
        type=parse_interval,
        default=5.0,
        action="store",
    )

    parser.add_argument(
        "-proxy",
        dest="proxy",
        help=(
            "Use HTTP proxy to bypass login restrictions in some countries.\n"
            "Example: -proxy http://127.0.0.1:8080"
        ),
        action="store",
    )

    parser.add_argument(
        "-output",
        dest="output",
        help=("Specify the output directory where recordings will be saved.\n"),
        action="store",
    )

    parser.add_argument(
        "-duration",
        dest="duration",
        help="Specify the duration in seconds to record the live session [Default: None].",
        type=int,
        default=None,
        action="store",
    )

    parser.add_argument(
        "-telegram",
        "--telegram",
        dest="telegram",
        action="store_true",
        help="Activate the option to upload the video to Telegram at the end "
        "of the recording.\nRequires configuring the telegram.json file",
    )

    parser.add_argument(
        "-youtube",
        "--youtube",
        dest="youtube",
        action="store_true",
        help="Activate the option to upload the video to YouTube at the end "
        "of the recording.\nRequires configuring the youtube.json file",
    )

    parser.add_argument(
        "-timezone",
        "--timezone",
        dest="timezone",
        default=None,
        help="Specify the timezone for output file names, logs, and YouTube metadata (e.g. 'UTC+8', 'Asia/Manila'). [Default: UTC+8]",
        action="store",
    )

    parser.add_argument(
        "-bitrate",
        dest="bitrate",
        help="Specify the bitrate for the output file (e.g. 1000k, 1M). Default: None (keep original)",
        action="store",
    )

    parser.add_argument(
        "-ffmpeg-path",
        dest="ffmpeg_path",
        help="Specify a custom path to the ffmpeg binary. [Default: 'ffmpeg']",
        default=None,
        action="store",
    )

    parser.add_argument(
        "-retry-delay",
        "-retry_delay",
        dest="retry_delay",
        help="Sets the connection retry delay in seconds. [Default: 5]",
        type=int,
        default=5,
        action="store",
    )

    parser.add_argument(
        "-keep-flv",
        "--keep-flv",
        dest="keep_flv",
        action="store_true",
        help="Keep the raw FLV recording files alongside the converted MP4 file.",
    )

    parser.add_argument(
        "-no-recycle-bin",
        "--no-recycle-bin",
        dest="move_to_recycle_bin",
        action="store_false",
        default=True,
        help="Permanently delete FLV files instead of moving them to the Recycle Bin/Trash.",
    )

    parser.add_argument(
        "-no-update-check",
        dest="update_check",
        action="store_false",
        help=(
            "Disable the check for updates before running the program. "
            "By default, update checking is enabled."
        ),
    )

    parser.add_argument(
        "-strategy",
        "--strategy",
        "-recording-strategy",
        "--recording-strategy",
        dest="recording_strategy",
        default="requests",
        choices=["requests", "flv", "yt-dlp"],
        help=(
            "Recording strategy: (requests, flv, yt-dlp) [Default: requests]\n"
            "[requests/flv] => Python chunked HTTP downloading (default).\n"
            "[yt-dlp]       => Live stream capture via yt-dlp (recommended)."
        ),
        action="store",
    )

    parser.add_argument(
        "-yt-dlp-path",
        "--yt-dlp-path",
        dest="yt_dlp_path",
        help="Specify a custom path to the yt-dlp binary. [Default: 'yt-dlp']",
        default=None,
        action="store",
    )

    parser.add_argument(
        "-purge-after-upload",
        "--purge-after-upload",
        dest="purge_after_upload",
        action="store_true",
        default=False,
        help="Automatically delete converted MP4 and split files after verified Telegram upload.",
    )

    parser.add_argument(
        "-no-split",
        "--no-split",
        dest="split_video",
        action="store_false",
        default=True,
        help="Disable splitting videos exceeding size limits.",
    )

    parser.add_argument(
        "-split-size-mb",
        "--split-size-mb",
        dest="split_size_mb",
        type=int,
        default=1950,
        help="Maximum part size in MB before splitting video [Default: 1950].",
    )

    from utils.utils import read_config

    config_defaults = read_config()
    if "no_update_check" in config_defaults:
        config_defaults["update_check"] = not bool(
            config_defaults.pop("no_update_check")
        )
    if config_defaults.get("recording_strategy", "").lower() == "ffmpeg":
        config_defaults["recording_strategy"] = "requests"

    # Apply only non-empty values as defaults
    valid_defaults = {
        k: v for k, v in config_defaults.items() if v is not None and v != ""
    }
    parser.set_defaults(**valid_defaults)

    args = parser.parse_args()

    return args


def validate_and_parse_args():
    args = parse_args()

    if getattr(args, "timezone", None):
        from utils.timezone_manager import set_configured_timezone

        set_configured_timezone(args.timezone)

    if args.user == "":
        args.user = None
    if args.url == "":
        args.url = None
    if args.room_id == "":
        args.room_id = None
    if args.output == "":
        args.output = None
    if args.proxy == "":
        args.proxy = None
    if args.bitrate == "":
        args.bitrate = None

    if not args.mode:
        raise ArgsParseError(
            "Missing mode value. Please specify the mode (manual, automatic or followers)."
        )
    if args.mode not in ["manual", "automatic", "followers"]:
        raise ArgsParseError(
            "Incorrect mode value. Choose between 'manual', 'automatic' or 'followers'."
        )

    if not getattr(args, "recording_strategy", None):
        args.recording_strategy = "requests"
    if args.recording_strategy.lower() == "flv":
        args.recording_strategy = "requests"
    if args.recording_strategy.lower() == "ffmpeg":
        args.recording_strategy = "requests"
    if args.recording_strategy not in ["requests", "yt-dlp"]:
        raise ArgsParseError(
            "Incorrect recording_strategy value. Choose between 'requests' (or 'flv') or 'yt-dlp'."
        )

    raw_user_input = args.user or getattr(args, "users", None)
    args.tracked_users = parse_tracked_users(raw_user_input)

    if args.tracked_users:
        usernames = [u.username for u in args.tracked_users]
        args.user = usernames if len(usernames) > 1 else usernames[0]
    else:
        args.user = None

    if args.mode in ["manual", "automatic"]:
        if not args.user and not args.room_id and not args.url:
            raise ArgsParseError(
                "Missing URL, username, or room ID. Please provide one of these parameters."
            )

    if (
        args.user
        and isinstance(args.user, list)
        and len(args.user) > 1
        and (args.room_id or args.url)
    ):
        raise ArgsParseError(
            "When using multiple usernames, do not provide room_id or url."
        )

    if args.url and not re.match(str(Regex.IS_TIKTOK_LIVE), args.url):
        raise ArgsParseError(
            "The provided URL does not appear to be a valid TikTok live URL."
        )

    if (
        (args.user and args.room_id)
        or (args.user and args.url)
        or (args.room_id and args.url)
    ):
        raise ArgsParseError("Please provide only one among username, room ID, or URL.")

    try:
        args.automatic_interval = parse_interval(args.automatic_interval)
    except (ValueError, TypeError):
        raise ArgsParseError(
            "Incorrect automatic_interval value. Specify time units, e.g. '30s' for seconds or '1m' for minutes."
        )

    if args.automatic_interval <= 0:
        raise ArgsParseError(
            "Incorrect automatic_interval value. Must be greater than 0."
        )

    if args.mode == "manual":
        mode = Mode.MANUAL
    elif args.mode == "automatic":
        mode = Mode.AUTOMATIC
    elif args.mode == "followers":
        mode = Mode.FOLLOWERS

    return args, mode
