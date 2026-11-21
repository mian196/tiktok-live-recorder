#!/usr/bin/env python3
"""
YouTube OAuth Token Expiry Monitor & Notification Script.

Checks all configured YouTube projects in configs/youtube.json, verifies whether
each refresh token is still valid, computes the exact expiration time, and sends
notifications via configured webhook (Discord / generic webhook) and/or Telegram.

Usage:
  python check_youtube_token.py                      # Check once and notify (for 12h cron/scheduler)
  python check_youtube_token.py --daemon             # Run continuously every 12 hours
  python check_youtube_token.py --interval-hours 12  # Custom daemon interval
  python check_youtube_token.py --no-notify          # Print status only
  python check_youtube_token.py --json               # Output JSON status report
"""

import argparse
import json
import os
import sys

script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(script_dir, "src"))

from notify.notifier import Notifier  # noqa: E402
from upload.youtube_token_monitor import (  # noqa: E402
    DEFAULT_CHECK_INTERVAL_HOURS,
    check_all_youtube_tokens,
    run_monitor_loop,
)


def _print_report(results: list[dict], notifier: Notifier | None) -> None:
    if notifier is not None and not notifier.enabled:
        print(
            "[!] Note: 'notifications.enabled' is false in configs/config.json; "
            "no webhook/Telegram alerts were sent."
        )
    for res in results:
        status = res["status"].upper()
        project = res["project"]
        if res["status"] == "valid":
            print(
                f"[OK] [{project}] {status} | Expires: {res['expires_at_str']} ({res['remaining_str']})"
            )
        else:
            extra = (
                f" | Expected expiry: {res['expires_at_str']}"
                if res.get("expires_at")
                else ""
            )
            print(f"[!] [{project}] {status} | {res['error']}{extra}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check YouTube OAuth token expiration and send webhook/Telegram notifications."
    )
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="Run continuously in a loop every --interval-hours (default: 12).",
    )
    parser.add_argument(
        "--interval-hours",
        type=float,
        default=DEFAULT_CHECK_INTERVAL_HOURS,
        help="Check interval in hours when using --daemon (default: 12).",
    )
    parser.add_argument(
        "--remind-before-hours",
        type=float,
        default=None,
        help="Send expiry reminder when remaining hours <= this threshold (default: config or 6h).",
    )
    parser.add_argument(
        "--no-notify",
        action="store_true",
        help="Do not send webhook/Telegram notifications; only print status.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print results as JSON (only in single-check mode).",
    )

    args = parser.parse_args()

    if args.daemon:
        try:
            run_monitor_loop(
                interval_hours=args.interval_hours,
                remind_before_hours=args.remind_before_hours,
                notify=not args.no_notify,
            )
        except KeyboardInterrupt:
            print("\n[*] YouTube token monitor stopped.")
        return 0

    notifier = None if args.no_notify else Notifier()
    results = check_all_youtube_tokens(
        notifier=notifier,
        remind_before_hours=args.remind_before_hours,
        notify=not args.no_notify,
    )

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        _print_report(results, notifier)

    has_problem = any(r["status"] != "valid" for r in results)
    return 1 if has_problem else 0


if __name__ == "__main__":
    sys.exit(main())
