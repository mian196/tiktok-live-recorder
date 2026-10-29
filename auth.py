#!/usr/bin/env python3
"""
Authentication Helper Script for TikTok Live Recorder.

Pre-authenticates YouTube OAuth2 and/or Telegram sessions before running recordings,
ensuring seamless background and headless server deployments.

Usage:
  python auth.py --youtube     Authenticate YouTube Google Cloud projects
  python auth.py --telegram    Authenticate Telegram session (interactive console)
  python auth.py --all         Authenticate both YouTube and Telegram
"""

import argparse
import asyncio
import os
import sys

# Add src directory to sys.path
script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(script_dir, "src"))

from utils.utils import read_telegram_config  # noqa: E402


def authenticate_youtube():
    """Authenticates all configured YouTube projects and saves token files."""
    print("\n" + "=" * 60)
    print("  YouTube OAuth2 Authentication Helper")
    print("=" * 60)

    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow

        from upload.youtube import SCOPES, YouTube
    except ImportError:
        print("[!] Error: Google API packages not installed.")
        print(
            "    Please run: pip install google-api-python-client google-auth-oauthlib google-auth-httplib2"
        )
        return False

    yt = YouTube()
    projects = yt.projects
    print(f"[*] Found {len(projects)} configured project(s) in configs/youtube.json\n")

    all_success = True

    for idx, project in enumerate(projects, start=1):
        name = project["name"]
        secrets_path = project["client_secrets_path"]
        storage_path = project["credentials_storage_path"]

        print(f"--- Project [{idx}/{len(projects)}]: {name} ---")

        if not os.path.exists(secrets_path):
            print(f"[!] Missing client_secrets file: {secrets_path}")
            print(
                "    Please download OAuth client credentials from Google Cloud Console"
            )
            print("    and place them in configs/ according to docs/YOUTUBE_SETUP.md\n")
            all_success = False
            continue

        creds = None
        if os.path.exists(storage_path):
            try:
                creds = Credentials.from_authorized_user_file(storage_path, SCOPES)
            except Exception as e:
                print(f"[!] Existing token could not be loaded: {e}")
                creds = None

        if creds and creds.valid:
            print(f"[✓] Token is already valid: {storage_path}\n")
            continue

        if creds and creds.expired and creds.refresh_token:
            try:
                print("[*] Refreshing expired token...")
                creds.refresh(Request())
                with open(storage_path, "w", encoding="utf-8") as f:
                    f.write(creds.to_json())
                print(f"[✓] Token refreshed and saved: {storage_path}\n")
                continue
            except Exception as e:
                print(f"[!] Could not refresh token: {e}. Re-authenticating...")

        print(f"[*] Launching authorization flow for [{name}]...")
        print(
            "    A browser tab will open. Sign into your YouTube account and click 'Allow'."
        )
        print(
            "    (If running on a remote headless server without GUI, see docs/YOUTUBE_SETUP.md)\n"
        )

        try:
            flow = InstalledAppFlow.from_client_secrets_file(
                secrets_path, scopes=SCOPES
            )
            creds = flow.run_local_server(port=0)

            os.makedirs(os.path.dirname(os.path.abspath(storage_path)), exist_ok=True)
            with open(storage_path, "w", encoding="utf-8") as f:
                f.write(creds.to_json())
            print(f"[✓] SUCCESS: Token saved to {storage_path}\n")
        except Exception as e:
            print(f"[!] Authentication failed for [{name}]: {e}\n")
            all_success = False

    if all_success:
        print("[✓] All YouTube projects are authenticated and ready for uploads!")
    else:
        print(
            "[!] Some YouTube projects could not be authenticated. Check the errors above."
        )
    return all_success


def authenticate_telegram():
    """Authenticates Telegram session interactively via console."""
    print("\n" + "=" * 60)
    print("  Telegram Session Authentication Helper")
    print("=" * 60)

    try:
        from telethon import TelegramClient
    except ImportError:
        print("[!] Error: Telethon is not installed.")
        print("    Please run: pip install telethon")
        return False

    config = read_telegram_config()
    api_id = config.get("api_id")
    api_hash = config.get("api_hash")

    if not api_id or not api_hash:
        print("[!] Error: 'api_id' or 'api_hash' is missing in configs/telegram.json.")
        print("    Please configure configs/telegram.json first (see docs/GUIDE.md).")
        return False

    session_name = "tiktok_live_recorder_session"
    session_file = f"{session_name}.session"

    print(f"[*] Using session file: {session_file}")
    client = TelegramClient(session_name, api_id=api_id, api_hash=api_hash)

    async def _auth():
        await client.connect()
        if await client.is_user_authorized():
            me = await client.get_me()
            name = getattr(me, "first_name", "") or getattr(me, "username", "User")
            print(
                f"[✓] Telegram is already authorized as: {name} (@{getattr(me, 'username', 'N/A')})"
            )
            print(f"    Session file '{session_file}' is valid and ready.")
            await client.disconnect()
            return True

        print("[*] Telegram authorization required.")
        print(
            "    You will be prompted for your phone number (+countrycode...) and login code.\n"
        )
        await client.start()

        me = await client.get_me()
        name = getattr(me, "first_name", "") or getattr(me, "username", "User")
        print(
            f"\n[✓] SUCCESS: Telegram authorized as: {name} (@{getattr(me, 'username', 'N/A')})"
        )
        print(f"    Session saved to '{session_file}'.")
        await client.disconnect()
        return True

    try:
        return asyncio.run(_auth())
    except Exception as e:
        print(f"[!] Telegram authentication error: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Pre-authenticate YouTube and/or Telegram before running TikTok Live Recorder."
    )
    parser.add_argument(
        "--youtube",
        "-yt",
        action="store_true",
        help="Authenticate YouTube OAuth2 client(s)",
    )
    parser.add_argument(
        "--telegram",
        "-tg",
        action="store_true",
        help="Authenticate Telegram account session",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Authenticate both YouTube and Telegram",
    )

    args = parser.parse_args()

    if not args.youtube and not args.telegram and not args.all:
        print("=" * 60)
        print("  TikTok Live Recorder - Authentication Setup")
        print("=" * 60)
        print("1) Authenticate YouTube")
        print("2) Authenticate Telegram")
        print("3) Authenticate Both")
        print("4) Exit")
        try:
            choice = input("\nSelect an option [1-4]: ").strip()
            if choice == "1":
                args.youtube = True
            elif choice == "2":
                args.telegram = True
            elif choice == "3":
                args.all = True
            else:
                print("Exiting.")
                return
        except (KeyboardInterrupt, EOFError):
            print("\nExiting.")
            return

    if args.all or args.youtube:
        authenticate_youtube()

    if args.all or args.telegram:
        authenticate_telegram()


if __name__ == "__main__":
    main()
