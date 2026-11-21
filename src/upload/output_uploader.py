import os
import re
from dataclasses import dataclass
from pathlib import Path

from upload.youtube import YouTube
from utils.timezone_manager import format_configured_time
from utils.user_identity import parse_tracked_users
from utils.utils import read_config

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".flv", ".mov", ".webm", ".ts"}
SKIP_DIRS = {"logs", ".test_tmp", "__pycache__"}
_FILENAME_USER_RE = re.compile(r"^(.+?)-\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}")


@dataclass
class OutputVideo:
    index: int
    path: Path
    relative_path: str
    username: str
    size_mb: float
    modified_ts: float
    modified_str: str
    explicit_playlist: str | None = None


def infer_username_from_path(video_path: Path, output_root: Path) -> str:
    """Infer streamer username from output/<user>/... subfolder or filename pattern."""
    try:
        rel_parts = video_path.resolve().relative_to(output_root.resolve()).parts
        if len(rel_parts) >= 2:
            return rel_parts[0]
    except ValueError:
        pass

    match = _FILENAME_USER_RE.match(video_path.stem)
    if match:
        return match.group(1)
    return video_path.stem


def _load_user_playlist_map() -> dict[str, str]:
    """Load per-streamer playlist overrides from configs/config.json if configured."""
    try:
        cfg = read_config()
        tracked = parse_tracked_users(cfg.get("user", []))
        return {
            tu.username.lower(): tu.playlist
            for tu in tracked
            if tu.username and tu.playlist
        }
    except Exception:
        return {}


def resolve_output_dir(output_dir: str | Path | None = None) -> Path:
    """Resolve the output directory from argument or configs/config.json."""
    if output_dir is not None:
        return Path(output_dir)
    cfg = read_config()
    return Path(cfg.get("output") or "output")


def list_output_videos(output_dir: str | Path | None = None) -> list[OutputVideo]:
    """Scan output directory for recorded video files, sorted newest first."""
    output_root = resolve_output_dir(output_dir)
    if not output_root.exists() or not output_root.is_dir():
        return []

    playlist_map = _load_user_playlist_map()
    candidates: list[tuple[float, Path]] = []

    for root, dirs, files in os.walk(output_root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for fname in files:
            if ".tmp" in fname:
                continue
            fpath = Path(root) / fname
            if fpath.suffix.lower() not in VIDEO_EXTENSIONS:
                continue
            try:
                stat = fpath.stat()
            except OSError:
                continue
            candidates.append((stat.st_mtime, fpath))

    candidates.sort(key=lambda item: (-item[0], str(item[1]).lower()))

    videos: list[OutputVideo] = []
    for idx, (mtime, fpath) in enumerate(candidates, start=1):
        username = infer_username_from_path(fpath, output_root)
        try:
            rel_path = str(fpath.relative_to(output_root))
        except ValueError:
            rel_path = str(fpath)
        size_mb = round(fpath.stat().st_size / (1024 * 1024), 2)
        mod_str = format_configured_time("%Y-%m-%d %H:%M:%S", timestamp=mtime)
        videos.append(
            OutputVideo(
                index=idx,
                path=fpath,
                relative_path=rel_path,
                username=username,
                size_mb=size_mb,
                modified_ts=mtime,
                modified_str=mod_str,
                explicit_playlist=playlist_map.get(username.lower()),
            )
        )
    return videos


def parse_selection(selection: str, max_index: int) -> list[int]:
    """
    Parse user video selection such as '1', '1,3,5', '1-4', or 'all'
    into an ordered, deduplicated list of 1-based indices.
    """
    raw = selection.strip().lower()
    if not raw:
        raise ValueError("No selection provided.")
    if max_index < 1:
        raise ValueError("No videos available to select.")
    if raw == "all":
        return list(range(1, max_index + 1))

    selected: list[int] = []
    seen: set[int] = set()

    for token in raw.split(","):
        part = token.strip()
        if not part:
            continue
        if "-" in part:
            bounds = part.split("-", 1)
            if (
                len(bounds) != 2
                or not bounds[0].strip().isdigit()
                or not bounds[1].strip().isdigit()
            ):
                raise ValueError(f"Invalid range '{part}'. Use format like '1-3'.")
            start, end = int(bounds[0].strip()), int(bounds[1].strip())
            if start > end or start < 1 or end > max_index:
                raise ValueError(
                    f"Range '{part}' is out of bounds (valid: 1-{max_index})."
                )
            for num in range(start, end + 1):
                if num not in seen:
                    seen.add(num)
                    selected.append(num)
        else:
            if not part.isdigit():
                raise ValueError(
                    f"Invalid selection '{part}'. Enter numbers, ranges, or 'all'."
                )
            num = int(part)
            if num < 1 or num > max_index:
                raise ValueError(
                    f"Selection '{num}' is out of bounds (valid: 1-{max_index})."
                )
            if num not in seen:
                seen.add(num)
                selected.append(num)

    if not selected:
        raise ValueError("No valid video indices selected.")
    return selected


def upload_selected_videos(
    selected_videos: list[OutputVideo],
    yt: YouTube | None = None,
    user_override: str | None = None,
    playlist_override: str | None = None,
    purge_after: bool = False,
) -> dict:
    """
    Upload selected OutputVideo items using the configs/youtube.json template.
    """
    yt = yt or YouTube()
    uploaded = 0
    failed_or_queued = 0
    results: list[dict] = []

    for video in selected_videos:
        user = user_override or video.username
        playlist = (
            playlist_override
            if playlist_override is not None
            else video.explicit_playlist
        )
        yt.last_error = None
        ok = yt.upload(
            file_path=str(video.path),
            user=user,
            playlist=playlist,
            purge_after=purge_after,
        )
        if ok:
            uploaded += 1
        else:
            failed_or_queued += 1
        results.append(
            {
                "index": video.index,
                "file": str(video.path),
                "user": user,
                "success": ok,
                "error": yt.last_error if not ok else None,
            }
        )

    return {
        "total": len(selected_videos),
        "uploaded": uploaded,
        "failed_or_queued": failed_or_queued,
        "results": results,
    }
