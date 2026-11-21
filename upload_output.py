#!/usr/bin/env python3
"""
Interactive & CLI Output Folder YouTube Uploader.

Lists recorded videos in the output folder, lets the user select which videos
to upload, and uploads them using the template settings in configs/youtube.json.

Usage:
  python upload_output.py                      # Interactive list & select
  python upload_output.py --list               # List videos in output folder and exit
  python upload_output.py --select 1,3-5 -y    # Upload selected indices without prompt
  python upload_output.py --select all --purge # Upload all and delete local files after
"""

import argparse
import os
import sys

script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(script_dir, "src"))

from upload.output_uploader import (  # noqa: E402
    OutputVideo,
    list_output_videos,
    parse_selection,
    resolve_output_dir,
    upload_selected_videos,
)
from upload.youtube import YouTube  # noqa: E402


def _print_video_table(videos: list[OutputVideo], output_root: str) -> None:
    print(f"\nFound {len(videos)} video(s) in '{output_root}':\n")
    print(f"{'#':<4} {'Streamer':<20} {'Size (MB)':>10}  {'Modified':<19}  File")
    print("-" * 80)
    for v in videos:
        print(
            f"{v.index:<4} {v.username[:20]:<20} {v.size_mb:>10.2f}  {v.modified_str:<19}  {v.relative_path}"
        )
    print()


def _print_template_preview(
    selected: list[OutputVideo],
    yt: YouTube,
    user_override: str | None,
    playlist_override: str | None,
) -> None:
    print("Upload preview (using configs/youtube.json template):")
    print(f"  Privacy: {yt.privacy_status}")
    for v in selected:
        user = user_override or v.username
        title, _ = yt._format_metadata(user, v.path)
        pl_target = (
            playlist_override if playlist_override is not None else v.explicit_playlist
        )
        playlist = yt.get_playlist_for_streamer(user, explicit_playlist=pl_target)
        pl_info = f" | Playlist: {playlist}" if playlist else ""
        print(f"  [{v.index}] {title}{pl_info}")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="List videos in the output folder, select videos, and upload using configs/youtube.json."
    )
    parser.add_argument(
        "--dir",
        default=None,
        help="Output folder path to scan (defaults to 'output' in configs/config.json).",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List videos in the output folder and exit.",
    )
    parser.add_argument(
        "--select",
        default=None,
        help="Video numbers/ranges to upload (e.g. '1', '1,3,5', '1-4', or 'all').",
    )
    parser.add_argument(
        "--user",
        default=None,
        help="Override inferred TikTok username for template formatting.",
    )
    parser.add_argument(
        "--playlist",
        default=None,
        help="Override target YouTube playlist ID or name.",
    )
    parser.add_argument(
        "--purge",
        action="store_true",
        help="Delete local video file after successful upload.",
    )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Skip confirmation prompt before uploading.",
    )

    args = parser.parse_args()
    output_root = resolve_output_dir(args.dir)
    videos = list_output_videos(output_root)

    if not videos:
        print(f"[!] No videos found in '{output_root}'.")
        return 0

    _print_video_table(videos, str(output_root))

    if args.list:
        return 0

    if args.select is not None:
        try:
            indices = parse_selection(args.select, len(videos))
        except ValueError as e:
            print(f"[!] {e}")
            return 1
    else:
        while True:
            try:
                raw = input(
                    "Select videos to upload (e.g. '1', '1,3', '1-3', 'all', or 'q' to quit): "
                ).strip()
            except (EOFError, KeyboardInterrupt):
                print("\nCancelled.")
                return 0
            if not raw or raw.lower() in ("q", "quit", "exit"):
                print("Cancelled.")
                return 0
            try:
                indices = parse_selection(raw, len(videos))
                break
            except ValueError as e:
                print(f"[!] {e}")

    by_index = {v.index: v for v in videos}
    selected = [by_index[i] for i in indices]

    yt = YouTube()
    _print_template_preview(selected, yt, args.user, args.playlist)

    if not args.yes:
        try:
            confirm = (
                input(f"Upload {len(selected)} video(s) to YouTube? [Y/n]: ")
                .strip()
                .lower()
            )
        except (EOFError, KeyboardInterrupt):
            print("\nCancelled.")
            return 0
        if confirm not in ("", "y", "yes"):
            print("Cancelled.")
            return 0

    summary = upload_selected_videos(
        selected,
        yt=yt,
        user_override=args.user,
        playlist_override=args.playlist,
        purge_after=args.purge,
    )

    print(
        f"\nDone: {summary['uploaded']}/{summary['total']} uploaded, "
        f"{summary['failed_or_queued']} failed/queued."
    )
    for item in summary["results"]:
        if item["success"]:
            print(f"  [OK] {item['file']}")
        else:
            err = item["error"] or "Check logs or retry queue."
            print(f"  [!]  {item['file']} -> {err}")

    return 0 if summary["failed_or_queued"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
