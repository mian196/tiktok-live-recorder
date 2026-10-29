import sys
import json
import os
import socket
import threading
import time
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from utils.logger_manager import logger
from utils.timezone_manager import get_configured_now, get_timezone_display_name
from utils.utils import _get_config_path, read_youtube_config

try:
    import httplib2
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload

    HAS_GOOGLE_API = True
except ImportError:
    HAS_GOOGLE_API = False

_youtube_lock = threading.RLock()

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
]
RETRYABLE_STATUS_CODES = {500, 502, 503, 504}
RETRYABLE_EXCEPTIONS = (
    socket.error,
    socket.timeout,
)
if HAS_GOOGLE_API:
    RETRYABLE_EXCEPTIONS = RETRYABLE_EXCEPTIONS + (httplib2.HttpLib2Error,)

MAX_RETRIES = 10


class SafeDict(dict):
    """Dictionary that returns the key in braces if missing to prevent KeyError during formatting."""

    def __missing__(self, key):
        return "{" + key + "}"


def get_pacific_offset_hours(dt_utc: datetime) -> int:
    """Return UTC offset in hours (-7 for PDT, -8 for PST) based on US DST rules."""
    year = dt_utc.year
    march_first_weekday = datetime(year, 3, 1).weekday()
    second_sunday_day = 1 + (6 - march_first_weekday) % 7 + 7
    dst_start = datetime(year, 3, second_sunday_day, 10, 0, tzinfo=UTC)

    nov_first_weekday = datetime(year, 11, 1).weekday()
    first_sunday_day = 1 + (6 - nov_first_weekday) % 7
    dst_end = datetime(year, 11, first_sunday_day, 9, 0, tzinfo=UTC)

    if dst_start <= dt_utc < dst_end:
        return -7
    return -8


def get_next_pacific_midnight() -> float:
    """Return the UNIX timestamp of the next midnight Pacific Time (when quota resets)."""
    now_utc = datetime.now(UTC)
    offset = get_pacific_offset_hours(now_utc)
    pt_tz = timezone(timedelta(hours=offset))
    now_pt = now_utc.astimezone(pt_tz)
    tomorrow_pt = (now_pt + timedelta(days=1)).replace(
        hour=0, minute=0, second=5, microsecond=0
    )
    return tomorrow_pt.timestamp()


def is_quota_exceeded(error: Exception) -> bool:
    """Check if an HttpError is due to daily YouTube quota exhaustion."""
    if HAS_GOOGLE_API and isinstance(error, HttpError) and error.resp.status == 403:
        content = str(getattr(error, "content", b"")).lower()
        return "quotaexceeded" in content or "dailylimitexceeded" in content
    return False


def _resolve_path(path_str: str | None, default_filename: str) -> str:
    """Resolve a configuration or storage path to an absolute path."""
    if not path_str:
        return _get_config_path(default_filename)
    if os.path.isabs(path_str):
        return path_str
    if os.path.exists(path_str):
        return os.path.abspath(path_str)
    return _get_config_path(os.path.basename(path_str))


class YouTube:
    """
    Handles authentication, multi-project quota rotation, automatic pending queue,
    and resumable video uploads to YouTube via YouTube Data API v3.
    """

    # Class-level dictionary tracking exhausted projects across instances {project_index: exhausted_until_ts}
    _exhausted_projects: dict[int, float] = {}

    def __init__(self, config_override: dict | None = None):
        cfg = config_override if config_override is not None else read_youtube_config()

        # Parse projects list for multi-project rotation (Method 2)
        raw_projects = cfg.get("projects", [])
        self.projects = []

        if raw_projects and isinstance(raw_projects, list):
            for idx, p in enumerate(raw_projects):
                if isinstance(p, dict):
                    sec = (
                        p.get("client_secrets_file") or f"client_secrets_{idx + 1}.json"
                    )
                    sto = (
                        p.get("credentials_storage_file")
                        or f"youtube_token_{idx + 1}.json"
                    )
                    name = p.get("name") or f"Project {idx + 1}"
                    self.projects.append(
                        {
                            "name": name,
                            "client_secrets_path": _resolve_path(
                                sec, f"client_secrets_{idx + 1}.json"
                            ),
                            "credentials_storage_path": _resolve_path(
                                sto, f"youtube_token_{idx + 1}.json"
                            ),
                        }
                    )

        if not self.projects:
            raw_secrets = cfg.get("client_secrets_file", "client_secrets.json")
            raw_storage = cfg.get("credentials_storage_file", "youtube_token.json")
            self.projects.append(
                {
                    "name": "Primary Project",
                    "client_secrets_path": _resolve_path(
                        raw_secrets, "client_secrets.json"
                    ),
                    "credentials_storage_path": _resolve_path(
                        raw_storage, "youtube_token.json"
                    ),
                }
            )

        # Legacy backward-compatibility accessors
        self.client_secrets_path = self.projects[0]["client_secrets_path"]
        self.credentials_storage_path = self.projects[0]["credentials_storage_path"]

        # Queue path for pending uploads (Method 1)
        raw_queue = cfg.get("queue_file", "youtube_queue.json")
        self.queue_path = _resolve_path(raw_queue, "youtube_queue.json")

        self.privacy_status = cfg.get("privacy_status", "private").lower()
        if self.privacy_status not in ["private", "unlisted", "public"]:
            self.privacy_status = "private"

        self.title_template = cfg.get(
            "title_template", "{display_name} (@{username}) - TikTok Live ({date})"
        )
        self.description_template = cfg.get(
            "description_template",
            "Recorded with TikTok Live Recorder\nStreamer: {display_name} (@{username})\nUser ID: {user_id}\nDate: {date}\nTime: {time} ({timezone})",
        )
        self.tags = cfg.get("tags", ["tiktok", "live", "recording"])
        raw_category = cfg.get("category_id")
        self.category_id = (
            str(raw_category).strip()
            if raw_category is not None
            and str(raw_category).strip().lower() not in ["", "none", "null"]
            else None
        )
        self.made_for_kids = bool(cfg.get("made_for_kids", False))
        self.default_playlist = cfg.get("default_playlist")
        self.streamer_playlists = cfg.get("streamer_playlists", {})
        self.grouped_playlists = cfg.get("playlists", {})
        self.last_error: str | None = None

    def _get_authenticated_service_for_project(self, project: dict):
        """Authenticate and return the YouTube v3 service instance for a specific project configuration."""
        if not HAS_GOOGLE_API:
            self.last_error = (
                "Google API libraries are not installed. "
                "Please run: pip install google-api-python-client google-auth-oauthlib google-auth-httplib2"
            )
            logger.error(self.last_error)
            return None

        creds = None
        storage_path = project["credentials_storage_path"]
        secrets_path = project["client_secrets_path"]
        name = project["name"]

        if os.path.exists(storage_path):
            try:
                creds = Credentials.from_authorized_user_file(storage_path, SCOPES)
            except Exception as e:
                logger.warning(
                    f"Failed to load YouTube credentials from {storage_path} for [{name}]: {e}"
                )
                creds = None

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    logger.info(
                        f"Refreshing expired YouTube OAuth credentials for [{name}]..."
                    )
                    creds.refresh(Request())
                except Exception as e:
                    err_str = str(e).lower()
                    if "invalid_grant" in err_str or "expired or revoked" in err_str:
                        self.last_error = (
                            f"YouTube OAuth token for [{name}] has expired or was revoked. "
                            "Please re-authenticate using 'python auth.py --youtube'."
                        )
                    else:
                        self.last_error = (
                            f"Could not refresh YouTube OAuth token for [{name}]: {e}"
                        )
                    logger.warning(
                        f"Could not refresh YouTube OAuth token for [{name}]: {e}. Re-authenticating."
                    )
                    creds = None

            if not creds or not creds.valid:
                if not os.path.exists(secrets_path):
                    self.last_error = (
                        f"YouTube client secrets file not found at: '{secrets_path}' for [{name}]. "
                        "Please refer to docs/YOUTUBE_SETUP.md."
                    )
                    logger.error(self.last_error)
                    return None

                # In non-interactive or headless environments, avoid blocking/hanging on browser flow
                if (
                    not sys.stdin
                    or not sys.stdin.isatty()
                    or os.environ.get("HEADLESS")
                ):
                    if not self.last_error:
                        self.last_error = (
                            f"YouTube OAuth authorization required for [{name}] but running non-interactively. "
                            "Please run 'python auth.py --youtube' to authenticate."
                        )
                    logger.error(self.last_error)
                    return None

                try:
                    logger.info(
                        f"Launching browser for YouTube OAuth2 authentication for [{name}]..."
                    )
                    flow = InstalledAppFlow.from_client_secrets_file(
                        secrets_path, scopes=SCOPES
                    )
                    creds = flow.run_local_server(port=0)

                    os.makedirs(
                        os.path.dirname(os.path.abspath(storage_path)), exist_ok=True
                    )
                    temp_path = f"{storage_path}.tmp.{os.getpid()}"
                    with open(temp_path, "w", encoding="utf-8") as f:
                        f.write(creds.to_json())
                    os.replace(temp_path, storage_path)
                    logger.info(
                        f"YouTube credentials saved to {storage_path} for [{name}]"
                    )
                except Exception as auth_e:
                    self.last_error = (
                        f"YouTube OAuth authorization failed for [{name}]: {auth_e}"
                    )
                    logger.error(self.last_error)
                    return None

        try:
            return build("youtube", "v3", credentials=creds)
        except Exception as e:
            self.last_error = f"Failed to build YouTube service for [{name}]: {e}"
            logger.error(self.last_error)
            return None

    def _get_authenticated_service(self):
        """Legacy helper returning service for the first project."""
        return self._get_authenticated_service_for_project(self.projects[0])

    def get_playlist_for_streamer(
        self, user: str, explicit_playlist: str | None = None
    ) -> str | None:
        """
        Resolves the playlist ID or Title for a streamer.
        Precedence:
          1. explicit_playlist (from CLI or config.json user entry)
          2. configs/youtube.json -> streamer_playlists: {"username": "playlist"}
          3. configs/youtube.json -> playlists: {"playlist": ["user1", "user2"]}
          4. configs/youtube.json -> default_playlist
        """
        if explicit_playlist:
            return explicit_playlist.strip()

        clean_user = (user or "").lstrip("@").strip().lower()

        if self.streamer_playlists and isinstance(self.streamer_playlists, dict):
            for k, v in self.streamer_playlists.items():
                if k.lstrip("@").strip().lower() == clean_user and v:
                    return str(v).strip()

        if self.grouped_playlists and isinstance(self.grouped_playlists, dict):
            for pl_target, users in self.grouped_playlists.items():
                if isinstance(users, (list, tuple)):
                    for u in users:
                        if str(u).lstrip("@").strip().lower() == clean_user:
                            return str(pl_target).strip()
                elif isinstance(users, str):
                    if users.lstrip("@").strip().lower() == clean_user:
                        return str(pl_target).strip()

        # Check config.json tracked users as single source of truth
        try:
            from utils.user_identity import parse_tracked_users
            from utils.utils import read_config

            cfg = read_config()
            if cfg:
                raw_users = cfg.get("users") if "users" in cfg else cfg.get("user")
                for u in parse_tracked_users(raw_users):
                    if u.username.lower() == clean_user and u.playlist:
                        return str(u.playlist).strip()
        except Exception:
            pass

        if self.default_playlist:
            return str(self.default_playlist).strip()

        return None

    def _resolve_playlist_id(self, service, playlist_target: str) -> str | None:
        """
        Resolves a playlist target (either a 'PL...' ID or a playlist title) to a valid playlist ID.
        If a title is given and does not exist on the channel, automatically creates it.
        """
        target = playlist_target.strip()
        if target.startswith(("PL", "UUL", "FL", "LL", "RD")) and len(target) >= 12:
            return target

        try:
            request = service.playlists().list(
                part="snippet",
                mine=True,
                maxResults=50,
            )
            while request is not None:
                response = request.execute()
                if not isinstance(response, dict):
                    break
                for item in response.get("items", []):
                    pl_title = item.get("snippet", {}).get("title", "").strip()
                    if pl_title.lower() == target.lower():
                        return item.get("id")
                if not response.get("nextPageToken"):
                    break
                request = service.playlists().list_next(request, response)
        except Exception as e:
            logger.debug(f"Could not search channel playlists: {e}")

        try:
            logger.info(
                f"Playlist '{target}' not found on channel. Automatically creating it..."
            )
            create_req = service.playlists().insert(
                part="snippet,status",
                body={
                    "snippet": {
                        "title": target,
                        "description": f"Automated recordings for {target}",
                    },
                    "status": {
                        "privacyStatus": self.privacy_status,
                    },
                },
            )
            created = create_req.execute()
            new_id = created.get("id")
            logger.info(f"Created new YouTube playlist: '{target}' ({new_id})")
            return new_id
        except Exception as e:
            logger.warning(f"Could not auto-create playlist '{target}': {e}")
            return None

    def _add_video_to_playlist(
        self, service, video_id: str, playlist_target: str
    ) -> bool:
        """Adds an uploaded video to the resolved YouTube playlist."""
        if not playlist_target:
            return False

        try:
            playlist_id = self._resolve_playlist_id(service, playlist_target)
            if not playlist_id:
                logger.warning(f"Could not resolve playlist ID for '{playlist_target}'")
                return False

            req = service.playlistItems().insert(
                part="snippet",
                body={
                    "snippet": {
                        "playlistId": playlist_id,
                        "resourceId": {
                            "kind": "youtube#video",
                            "videoId": video_id,
                        },
                    }
                },
            )
            req.execute()
            logger.info(f"Added video to playlist [{playlist_target}] ({playlist_id})!")
            return True
        except Exception as e:
            logger.warning(
                f"Could not add video {video_id} to playlist [{playlist_target}]: {e}"
            )
            return False

    def add_video_to_playlist(self, video_id: str, playlist_target: str) -> bool:
        """Public helper to add an existing video ID to a playlist."""
        service = self._get_authenticated_service()
        if not service:
            logger.error("Could not obtain authenticated YouTube service.")
            return False
        return self._add_video_to_playlist(service, video_id, playlist_target)

    def _format_metadata(
        self, user: str, source_path: Path, nickname: str = "", room_id: str = ""
    ) -> tuple[str, str]:
        """Interpolates title and description templates safely with display name, username, and configured timezone."""
        now = get_configured_now()
        tz_name = get_timezone_display_name()
        username = user or "user"
        display_name = nickname or username
        format_vars = {
            "user": username,
            "username": username,
            "nickname": display_name,
            "display_name": display_name,
            "user_id": username,
            "date": now.strftime("%Y-%m-%d"),
            "time": now.strftime("%H:%M:%S"),
            "timezone": tz_name,
            "filename": source_path.stem,
            "room_id": str(room_id or ""),
        }
        safe_dict = SafeDict(format_vars)
        title = self.title_template.format_map(safe_dict)
        description = self.description_template.format_map(safe_dict)
        if len(title) > 100:
            title = title[:97] + "..."
        return title, description

    # =========================================================================
    # Method 1: Pending Uploads Queue (Retry next day after quota reset)
    # =========================================================================

    def _load_queue(self) -> list[dict]:
        """Loads pending queue items from disk atomically."""
        if not os.path.exists(self.queue_path):
            return []
        try:
            with open(self.queue_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
        except Exception as e:
            logger.debug(f"Could not load YouTube queue: {e}")
            return []

    def _save_queue(self, queue_items: list[dict]):
        """Saves queue items to disk atomically."""
        try:
            os.makedirs(
                os.path.dirname(os.path.abspath(self.queue_path)), exist_ok=True
            )
            temp_path = f"{self.queue_path}.tmp.{os.getpid()}"
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(queue_items, f, indent=2)
            os.replace(temp_path, self.queue_path)
        except Exception as e:
            logger.warning(f"Could not save YouTube upload queue: {e}")

    def enqueue_file(
        self,
        file_path: str,
        user: str = "",
        nickname: str = "",
        room_id: str = "",
        playlist: str | None = None,
        purge_after: bool = False,
        error_reason: str = "quotaExceeded",
    ):
        """Enqueues a file to be retried after the next quota reset."""
        queue = self._load_queue()
        abs_path = os.path.abspath(file_path)
        retry_after = get_next_pacific_midnight()

        # Check if already enqueued
        for item in queue:
            if os.path.abspath(item.get("file_path", "")) == abs_path:
                item["retry_after"] = retry_after
                item["last_error"] = error_reason
                self._save_queue(queue)
                return

        queue.append(
            {
                "file_path": str(abs_path),
                "user": user,
                "nickname": nickname,
                "room_id": str(room_id or ""),
                "playlist": playlist,
                "purge_after": purge_after,
                "added_at": time.time(),
                "retry_after": retry_after,
                "last_error": error_reason,
            }
        )
        self._save_queue(queue)
        logger.info(
            f"Enqueued '{Path(file_path).name}' for automatic retry after midnight PT quota reset."
        )

    def process_queue(self) -> int:
        """
        Processes pending uploads in the queue.
        Retries files whose retry_after time has passed or when quota reset has occurred.
        Returns the number of successfully uploaded files.
        """
        with _youtube_lock:
            queue = self._load_queue()
            if not queue:
                return 0

            now = time.time()
            # Clean expired project exhaustions if reset time has arrived
            for p_idx, until in list(self._exhausted_projects.items()):
                if now >= until:
                    del self._exhausted_projects[p_idx]

            remaining_queue = []
            successful_uploads = 0

            for item in queue:
                fpath = item.get("file_path")
                if not fpath or not os.path.exists(fpath):
                    logger.debug(f"Queue item file not found, removing: {fpath}")
                    continue

                retry_after = item.get("retry_after", 0)
                if now < retry_after and len(self._exhausted_projects) >= len(
                    self.projects
                ):
                    # Quota has not reset yet and all projects are still exhausted
                    remaining_queue.append(item)
                    continue

                user = item.get("user", "")
                nickname = item.get("nickname", "")
                room_id = item.get("room_id", "")
                pl = item.get("playlist")
                purge = item.get("purge_after", False)
                logger.info(
                    f"Retrying pending YouTube upload from queue: '{Path(fpath).name}'..."
                )

                success = self._upload_internal(
                    fpath,
                    user=user,
                    nickname=nickname,
                    room_id=room_id,
                    playlist=pl,
                    purge_after=purge,
                    is_queued_retry=True,
                )
                if success:
                    successful_uploads += 1
                else:
                    # Still failing, keep in queue with updated retry_after
                    item["retry_after"] = get_next_pacific_midnight()
                    remaining_queue.append(item)

            self._save_queue(remaining_queue)
            return successful_uploads

    # =========================================================================
    # Method 2: Multi-Project / Credential Rotation
    # =========================================================================

    def _upload_internal(
        self,
        file_path: str,
        user: str = "",
        nickname: str = "",
        room_id: str = "",
        playlist: str | None = None,
        purge_after: bool = False,
        is_queued_retry: bool = False,
    ) -> bool:
        """Internal upload runner with multi-project rotation and resumable chunked upload."""
        source_path = Path(file_path)
        if not source_path.exists():
            logger.error(f"File not found for YouTube upload: {file_path}")
            return False

        file_size = source_path.stat().st_size
        if file_size == 0:
            logger.error(f"File is empty for YouTube upload: {file_path}")
            return False

        file_size_mb = round(file_size / (1024 * 1024))
        logger.info(
            f"Starting YouTube upload for '{source_path.name}' ({file_size_mb} MB)..."
        )

        now = time.time()
        # Clean expired project exhaustions
        for p_idx, until in list(self._exhausted_projects.items()):
            if now >= until:
                del self._exhausted_projects[p_idx]

        title, description = self._format_metadata(
            user, source_path, nickname=nickname, room_id=room_id
        )
        snippet = {
            "title": title,
            "description": description,
            "tags": self.tags,
        }
        if self.category_id:
            snippet["categoryId"] = self.category_id

        body = {
            "snippet": snippet,
            "status": {
                "privacyStatus": self.privacy_status,
                "selfDeclaredMadeForKids": self.made_for_kids,
            },
        }

        # Iterate through configured projects (Method 2)
        total_projects = len(self.projects)
        all_quota_exhausted = True
        auth_failures = 0
        quota_failures = 0
        last_auth_error = None

        for idx, project in enumerate(self.projects):
            p_name = project["name"]

            # Skip project if currently exhausted today
            if idx in self._exhausted_projects:
                until = self._exhausted_projects[idx]
                if now < until:
                    logger.debug(
                        f"Project [{p_name}] ({idx + 1}/{total_projects}) quota exhausted until reset. Skipping."
                    )
                    continue

            logger.info(
                f"Attempting upload using YouTube project [{p_name}] ({idx + 1}/{total_projects})..."
            )
            service = self._get_authenticated_service_for_project(project)
            if not service:
                logger.warning(
                    f"Could not initialize service for project [{p_name}]. Trying next project..."
                )
                auth_failures += 1
                if self.last_error:
                    last_auth_error = self.last_error
                continue

            media = None
            try:
                media = MediaFileUpload(
                    str(source_path),
                    mimetype="video/*",
                    chunksize=1024 * 1024 * 8,  # 8MB chunk size
                    resumable=True,
                )

                request = service.videos().insert(
                    part="snippet,status",
                    body=body,
                    media_body=media,
                )

                response = None
                retry = 0

                while response is None:
                    try:
                        status, response = request.next_chunk()
                        if status:
                            pct = int(status.progress() * 100)
                            logger.info(
                                f"Uploading to YouTube [{source_path.name}]: {pct}%"
                            )
                        retry = 0
                    except HttpError as e:
                        if is_quota_exceeded(e):
                            logger.warning(
                                f"Daily YouTube API quota reached on project [{p_name}] ({idx + 1}/{total_projects})."
                            )
                            self._exhausted_projects[idx] = get_next_pacific_midnight()
                            quota_failures += 1
                            break  # Break inner loop to rotate to the next project
                        elif e.resp.status in RETRYABLE_STATUS_CODES:
                            retry += 1
                            if retry > MAX_RETRIES:
                                logger.error(
                                    f"YouTube upload exceeded max retries on HTTP error: {e}"
                                )
                                break
                            sleep_time = min(2**retry, 60)
                            logger.warning(
                                f"YouTube HTTP {e.resp.status}. Retrying chunk in {sleep_time}s..."
                            )
                            time.sleep(sleep_time)
                        else:
                            logger.error(
                                f"YouTube upload client error on [{p_name}]: {e}"
                            )
                            all_quota_exhausted = False
                            break
                    except RETRYABLE_EXCEPTIONS as e:
                        retry += 1
                        if retry > MAX_RETRIES:
                            logger.error(
                                f"YouTube upload exceeded max retries on network error: {e}"
                            )
                            break
                        sleep_time = min(2**retry, 60)
                        logger.warning(
                            f"YouTube network connection error ({e}). Retrying chunk in {sleep_time}s..."
                        )
                        time.sleep(sleep_time)

                if response is not None:
                    video_id = response.get("id")
                    video_url = (
                        f"https://youtu.be/{video_id}"
                        if video_id
                        else "Uploaded successfully"
                    )
                    logger.info(
                        f"YouTube upload finished successfully via [{p_name}]! Video URL: {video_url}\n"
                    )

                    target_pl = self.get_playlist_for_streamer(
                        user, explicit_playlist=playlist
                    )
                    if video_id and target_pl:
                        self._add_video_to_playlist(service, video_id, target_pl)

                    if hasattr(media, "_fd") and media._fd:
                        try:
                            media._fd.close()
                        except Exception:
                            pass

                    if purge_after and source_path.exists():
                        try:
                            source_path.unlink(missing_ok=True)
                            logger.info(
                                f"Purged local recording file: {source_path.name}"
                            )
                        except Exception as e:
                            logger.warning(f"Could not purge {source_path.name}: {e}")

                    return True

            except Exception as e:
                logger.error(
                    f"Unexpected error uploading with project [{p_name}]: {e}\n",
                    exc_info=True,
                )
                all_quota_exhausted = False
            finally:
                if media is not None and hasattr(media, "_fd") and media._fd:
                    try:
                        media._fd.close()
                    except Exception:
                        pass

        # Check why all available projects failed
        if auth_failures == total_projects and last_auth_error:
            self.last_error = last_auth_error
            logger.error(
                f"YouTube upload blocked: {self.last_error}. Retaining local file '{source_path.name}'."
            )
            return False

        if (
            all_quota_exhausted or quota_failures == total_projects
        ) and not is_queued_retry:
            self.last_error = (
                f"All {total_projects} configured YouTube project(s) have exhausted their daily quota. "
                "Enqueued for automatic retry after midnight Pacific Time (00:00 PT reset)."
            )
            logger.warning(self.last_error)
            self.enqueue_file(
                file_path=str(source_path),
                user=user,
                nickname=nickname,
                room_id=room_id,
                playlist=playlist,
                purge_after=purge_after,
                error_reason="quotaExceeded",
            )
            logger.info(
                f"Local recording '{source_path.name}' is safely retained until upload completes."
            )
            return False

        if not self.last_error:
            self.last_error = "YouTube upload did not complete."

        return False

    def upload(
        self,
        file_path: str,
        user: str = "",
        nickname: str = "",
        room_id: str = "",
        playlist: str | None = None,
        purge_after: bool = False,
        ffmpeg_path: str | None = None,
    ) -> bool:
        """
        Uploads a video file to YouTube via resumable chunked upload.
        Rotates through configured projects if daily quota is reached (Method 2).
        If all projects are exhausted, safely retains the local file and enqueues for
        automatic next-day retry (Method 1).
        Optionally adds the video to the streamer's configured playlist.
        """
        with _youtube_lock:
            # Check if any previously pending queue items can be flushed first
            self.process_queue()
            return self._upload_internal(
                file_path,
                user=user,
                nickname=nickname,
                room_id=room_id,
                playlist=playlist,
                purge_after=purge_after,
            )


if __name__ == "__main__":
    import argparse

    src_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)

    parser = argparse.ArgumentParser(
        description="Upload recordings to YouTube or process pending retry queue."
    )
    parser.add_argument("--file", "-f", help="Path to video file to upload")
    parser.add_argument("--user", "-u", default="", help="Streamer TikTok username")
    parser.add_argument(
        "--nickname", "-n", default="", help="Streamer display nickname"
    )
    parser.add_argument(
        "--playlist", "-p", default=None, help="Target YouTube playlist ID or Name"
    )
    parser.add_argument(
        "--queue", "-q", action="store_true", help="Process pending upload queue"
    )
    parser.add_argument(
        "--purge", action="store_true", help="Delete local file after upload"
    )

    cli_args = parser.parse_args()
    yt_cli = YouTube()

    if cli_args.queue or not cli_args.file:
        count = yt_cli.process_queue()
        if not cli_args.file:
            print(f"Processed retry queue: {count} video(s) uploaded successfully.")
            sys.exit(0)

    if cli_args.file:
        res = yt_cli.upload(
            file_path=cli_args.file,
            user=cli_args.user,
            nickname=cli_args.nickname,
            playlist=cli_args.playlist,
            purge_after=cli_args.purge,
        )
        if not res and yt_cli.last_error:
            print(f"[!] Upload blocked / failed: {yt_cli.last_error}")
        sys.exit(0 if res else 1)
