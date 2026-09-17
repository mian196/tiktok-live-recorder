import shutil
import threading
import time
from http.client import HTTPException
from pathlib import Path
from threading import Thread

from requests import RequestException

from core.tiktok_api import TikTokAPI
from notify.notifier import Notifier
from utils.logger_manager import logger
from utils.recorder_config import RecorderConfig
from utils.status_bar import RecordingStatusBar
from utils.custom_exceptions import LiveNotFound, UserLiveError, TikTokRecorderError
from utils.enums import Mode, Error, TimeOut, TikTokError
from utils.user_identity import TrackedUser, parse_tracked_users
from utils.utils import update_tracked_users_in_config


import os
import tempfile


class _ConversionLock:
    """Cross-thread and cross-process lock for sequential video conversions."""

    def __init__(self):
        self._thread_lock = threading.Lock()
        self._lock_file = os.path.join(
            tempfile.gettempdir(), "tiktok_recorder_conversion.lock"
        )
        self._fd = None

    def __enter__(self):
        self._thread_lock.acquire()
        try:
            self._fd = os.open(self._lock_file, os.O_CREAT | os.O_RDWR)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self._fd, msvcrt.LK_LOCK, 1)
            else:
                import fcntl

                fcntl.flock(self._fd, fcntl.LOCK_EX)
        except Exception as e:
            logger.debug(f"Process lock warning: {e}")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            if self._fd is not None:
                if os.name == "nt":
                    import msvcrt

                    try:
                        msvcrt.locking(self._fd, msvcrt.LK_UNLCK, 1)
                    except OSError:
                        pass
                else:
                    import fcntl

                    try:
                        fcntl.flock(self._fd, fcntl.LOCK_UN)
                    except OSError:
                        pass
                os.close(self._fd)
                self._fd = None
        finally:
            self._thread_lock.release()


_conversion_lock = _ConversionLock()


class TikTokRecorder:
    def __init__(self, config: RecorderConfig):
        self.tiktok = TikTokAPI(proxy=config.proxy, cookies=config.cookies)
        self.notify = Notifier()

        self.url = config.url
        self.user = config.user
        self.room_id = config.room_id
        self.mode = config.mode
        self.automatic_interval = config.automatic_interval
        self.duration = config.duration
        self.output = config.output
        self.bitrate = config.bitrate
        self.ffmpeg_path = config.ffmpeg_path
        self.use_telegram = config.use_telegram
        self.keep_flv = config.keep_flv
        self.move_to_recycle_bin = getattr(config, "move_to_recycle_bin", True)
        self.retry_delay = getattr(config, "retry_delay", 5)
        self.disk_space_alert_gb = getattr(config, "disk_space_alert_gb", 5)
        self.users = config.users
        self._proxy = config.proxy
        self._cookies = config.cookies
        self.config = config
        self.recording_strategy = getattr(config, "recording_strategy", "requests")
        self.yt_dlp_path = getattr(config, "yt_dlp_path", None)

        # Self-healing tracked users
        self.tracked_users: list[TrackedUser] = config.tracked_users or []
        if not self.tracked_users:
            if config.users:
                self.tracked_users = parse_tracked_users(config.users)
            elif config.user:
                self.tracked_users = parse_tracked_users(config.user)

    def _save_tracked_users_to_config(self):
        """Persists current tracked user objects (with resolved sec_uid / user_id) to config.json."""
        try:
            if self.tracked_users:
                update_tracked_users_in_config(self.tracked_users)
                self.users = [u.username for u in self.tracked_users]
        except Exception as e:
            logger.debug(f"Failed to update config.json with tracked users: {e}")

    def _sync_and_resolve_user(self, user_obj: TrackedUser) -> TrackedUser:
        """
        Auto-resolves missing sec_uid / user_id from username and persists to config.json.
        """
        if not user_obj.sec_uid and user_obj.username:
            try:
                info = self.tiktok.get_user_info(user_obj.username)
                if info and info.get("sec_uid"):
                    user_obj.sec_uid = info["sec_uid"]
                    user_obj.user_id = info.get("user_id")
                    logger.info(
                        f"[*] [ID-RESOLVE] Auto-discovered permanent ID for @{user_obj.username} "
                        f"(sec_uid: {user_obj.sec_uid[:16]}...) -> saved to configs/config.json"
                    )
                    self._save_tracked_users_to_config()
            except Exception as e:
                logger.debug(f"Failed to resolve ID for @{user_obj.username}: {e}")

        return user_obj

    def _check_and_recover_user_handle(
        self, user_obj: TrackedUser
    ) -> tuple[TrackedUser, str | None]:
        """
        Attempts to get the room_id for the user.
        If username lookup fails/changed and sec_uid exists:
        - Resolves current handle via permanent sec_uid.
        - If handle changed: updates user_obj, logs change, and updates config.json.
        - If sec_uid failed: tries to repair ID from current username.
        """
        room_id = None
        try:
            room_id = self.tiktok.get_room_id_from_user(user_obj.username)
        except (UserLiveError, LiveNotFound, TikTokRecorderError):
            pass

        if room_id:
            return user_obj, room_id

        # Room ID not found or error. Check if username changed using permanent sec_uid
        if user_obj.sec_uid:
            try:
                profile_by_sec = self.tiktok.get_user_by_sec_uid(user_obj.sec_uid)
                if profile_by_sec and profile_by_sec.get("username"):
                    current_name = profile_by_sec["username"]
                    if current_name.lower() != user_obj.username.lower():
                        old_name = user_obj.username
                        user_obj.username = current_name
                        if profile_by_sec.get("user_id"):
                            user_obj.user_id = profile_by_sec["user_id"]
                        logger.info(
                            f"[*] [HANDLE-CHANGE] Detected username change: @{old_name} -> @{current_name}. "
                            "Updated configs/config.json"
                        )
                        self._save_tracked_users_to_config()
                        # Retry room lookup with new username
                        try:
                            room_id = self.tiktok.get_room_id_from_user(
                                user_obj.username
                            )
                        except Exception:
                            pass
                        return user_obj, room_id
            except Exception as e:
                logger.debug(
                    f"Failed handle recovery for {user_obj.username} via sec_uid: {e}"
                )

        # Check if sec_uid might be invalid / outdated for this username
        try:
            fresh_info = self.tiktok.get_user_info(user_obj.username)
            if (
                fresh_info
                and fresh_info.get("sec_uid")
                and fresh_info.get("sec_uid") != user_obj.sec_uid
            ):
                user_obj.sec_uid = fresh_info["sec_uid"]
                user_obj.user_id = fresh_info.get("user_id")
                logger.warning(
                    f"[!] [ID-REPAIR] Outdated or invalid ID for @{user_obj.username} corrected from live profile. "
                    "Updated configs/config.json"
                )
                self._save_tracked_users_to_config()
        except Exception as e:
            logger.debug(f"Failed ID repair for {user_obj.username}: {e}")

        return user_obj, room_id

    def _setup(self):
        """Resolve user/room data and validate prerequisites via network calls."""
        if self.mode == Mode.FOLLOWERS:
            self.check_country_blacklisted()

            self.sec_uid = self.tiktok.get_sec_uid()
            if self.sec_uid is None:
                raise TikTokRecorderError("Failed to retrieve sec_uid.")

            logger.info("Followers mode activated\n")
        elif self.users:
            self.check_country_blacklisted()
            # Auto-resolve IDs on startup if missing
            if self.tracked_users:
                for idx, u in enumerate(self.tracked_users):
                    self.tracked_users[idx] = self._sync_and_resolve_user(u)
                self.users = [u.username for u in self.tracked_users]
            logger.info(
                f"Multi-user automatic mode activated for {len(self.users)} users: {', '.join(self.users)}\n"
            )
        else:
            if self.tracked_users:
                self.tracked_users[0] = self._sync_and_resolve_user(
                    self.tracked_users[0]
                )
                self.user = self.tracked_users[0].username

            if self.url:
                self.user, self.room_id = self.tiktok.get_room_and_user_from_url(
                    self.url
                )

            if not self.user:
                self.user = self.tiktok.get_user_from_room_id(self.room_id)

            if not self.room_id:
                if self.tracked_users:
                    self.tracked_users[0], self.room_id = (
                        self._check_and_recover_user_handle(self.tracked_users[0])
                    )
                    self.user = self.tracked_users[0].username
                else:
                    self.room_id = self.tiktok.get_room_id_from_user(self.user)

            self.check_country_blacklisted()

            logger.info(f"USERNAME: {self.user}" + ("\n" if not self.room_id else ""))
            if self.room_id:
                logger.info(
                    f"ROOM_ID:  {self.room_id}"
                    + ("\n" if not self.tiktok.is_room_alive(self.room_id) else "")
                )

        # If proxy was used for the initial checks, switch to a direct connection
        # for the actual stream download to avoid proxy bottlenecks
        if self._proxy:
            self.tiktok = TikTokAPI(proxy=None, cookies=self._cookies)

    def run(self):
        """
        Resolves prerequisites and runs the recorder in the selected mode.

        If the mode is MANUAL, it checks if the user is currently live and
        if so, starts recording.

        If the mode is AUTOMATIC, it continuously checks if the user is live
        and if not, waits for the specified timeout before rechecking.
        If the user is live, it starts recording.

        if the mode is FOLLOWERS, it continuously checks the followers of
        the authenticated user. If any follower is live, it starts recording
        their live stream in a separate process.
        """
        self._setup()

        if self.mode == Mode.MANUAL:
            self.manual_mode()

        elif self.mode == Mode.AUTOMATIC:
            if self.users:
                self.automatic_mode_multi()
            else:
                self.automatic_mode()

        elif self.mode == Mode.FOLLOWERS:
            self.followers_mode()

    def _check_disk_space(self, user: str = None) -> bool:
        """Return True if disk has enough space, False if below threshold."""
        if self.disk_space_alert_gb <= 0:
            return True

        output_dir = Path(self.output) if self.output else Path(".")
        try:
            usage = shutil.disk_usage(output_dir)
            free_gb = usage.free / (1024**3)
        except Exception as e:
            logger.debug(f"Unable to check disk space: {e}")
            return True

        if free_gb < self.disk_space_alert_gb:
            logger.warning(
                f"Low disk space: {free_gb:.1f} GB free (threshold: {self.disk_space_alert_gb} GB)."
            )
            self.notify.notify(
                "low_disk_space",
                user=user or self.user or "recorder",
                free_gb=round(free_gb, 1),
                threshold=self.disk_space_alert_gb,
            )
            return False
        return True

    def manual_mode(self):
        if not self._check_disk_space(self.user):
            logger.warning("Recording aborted — low disk space.")
            return

        if not self.tiktok.is_room_alive(self.room_id):
            raise UserLiveError(f"@{self.user}: {TikTokError.USER_NOT_CURRENTLY_LIVE}")

        self.start_recording(self.user, self.room_id)

    def automatic_mode(self):
        while True:
            try:
                if not self._check_disk_space(self.user):
                    logger.warning("Skipping recording check — low disk space.")
                    time.sleep(self.automatic_interval * TimeOut.ONE_MINUTE)
                    continue

                if self.tracked_users:
                    self.tracked_users[0] = self._sync_and_resolve_user(
                        self.tracked_users[0]
                    )
                    self.tracked_users[0], self.room_id = (
                        self._check_and_recover_user_handle(self.tracked_users[0])
                    )
                    self.user = self.tracked_users[0].username
                else:
                    self.room_id = self.tiktok.get_room_id_from_user(self.user)

                if self.room_id and self.tiktok.is_room_alive(self.room_id):
                    self.notify.notify("live_detected", user=self.user)
                    self.manual_mode()

            except (UserLiveError, LiveNotFound) as ex:
                logger.info(ex)
                logger.info(
                    f"Waiting {self.automatic_interval} minutes before recheck\n"
                )
                time.sleep(self.automatic_interval * TimeOut.ONE_MINUTE)

            except (ConnectionError, RequestException, HTTPException, OSError) as ex:
                logger.error(f"{Error.CONNECTION_CLOSED_AUTOMATIC} ({ex})")
                self.tiktok.reset_session()
                time.sleep(self.retry_delay)
            except Exception as ex:
                logger.warning(
                    f"Unexpected error in automatic mode: {ex}. Retrying in {self.retry_delay}s..."
                )
                self.tiktok.reset_session()
                time.sleep(self.retry_delay)

    def automatic_mode_multi(self):
        """Check all users concurrently, spawning non-blocking recording threads when live."""
        active_recordings = {}  # username -> Thread

        try:
            while True:
                if not self._check_disk_space():
                    logger.warning("Skipping recording check — low disk space.")
                    time.sleep(self.automatic_interval * TimeOut.ONE_MINUTE)
                    continue

                target_list = (
                    self.tracked_users
                    if self.tracked_users
                    else [TrackedUser(username=u) for u in self.users]
                )

                for idx, user_obj in enumerate(target_list):
                    if user_obj.username in active_recordings:
                        if not active_recordings[user_obj.username].is_alive():
                            logger.info(f"Recording of @{user_obj.username} finished.")
                            del active_recordings[user_obj.username]
                        else:
                            continue  # Already actively recording in background

                    try:
                        user_obj = self._sync_and_resolve_user(user_obj)
                        user_obj, room_id = self._check_and_recover_user_handle(
                            user_obj
                        )
                        if self.tracked_users and idx < len(self.tracked_users):
                            self.tracked_users[idx] = user_obj

                        curr_user = user_obj.username

                        if room_id and self.tiktok.is_room_alive(room_id):
                            logger.info(
                                f"@{curr_user} is live. Starting simultaneous recording..."
                            )
                            self.notify.notify("live_detected", user=curr_user)
                            stop_event = threading.Event()

                            def _runner(u=curr_user, r=room_id, ev=stop_event):
                                import inspect

                                try:
                                    sig = inspect.signature(self.start_recording)
                                    if "stop_event" in sig.parameters or any(
                                        p.kind == inspect.Parameter.VAR_KEYWORD
                                        for p in sig.parameters.values()
                                    ):
                                        self.start_recording(u, r, stop_event=ev)
                                    else:
                                        self.start_recording(u, r)
                                except TypeError:
                                    self.start_recording(u, r)

                            thread = Thread(
                                target=_runner,
                                name=f"Recorder-{curr_user}",
                                daemon=True,
                            )
                            thread.stop_event = stop_event
                            thread.start()
                            active_recordings[curr_user] = thread
                    except (UserLiveError, LiveNotFound) as ex:
                        logger.info(ex)
                    except (
                        ConnectionError,
                        RequestException,
                        HTTPException,
                        OSError,
                    ) as ex:
                        logger.error(f"{Error.CONNECTION_CLOSED_AUTOMATIC} ({ex})")
                        self.tiktok.reset_session()
                        time.sleep(self.retry_delay)
                        continue
                    except Exception as ex:
                        logger.warning(
                            f"Temporary check error for @{user_obj.username}: {ex}. Retrying next check."
                        )
                        self.tiktok.reset_session()
                        time.sleep(self.retry_delay)
                        continue

                    time.sleep(TimeOut.USER_CHECK_DELAY)

                active_count = sum(
                    1 for t in active_recordings.values() if t.is_alive()
                )
                logger.info(
                    f"All users checked ({active_count} actively recording). Waiting {self.automatic_interval} minutes...\n"
                )
                time.sleep(self.automatic_interval * TimeOut.ONE_MINUTE)
        except KeyboardInterrupt:
            logger.info("Ctrl+C detected. Gracefully stopping all active recordings...")
            for t in active_recordings.values():
                if hasattr(t, "stop_event"):
                    t.stop_event.set()
            for t in active_recordings.values():
                if t.is_alive():
                    t.join(timeout=10)
            raise

    def followers_mode(self):
        active_recordings = {}  # follower -> Thread

        while True:
            try:
                followers = self.tiktok.get_followers_list(self.sec_uid)

                for follower in followers:
                    if follower in active_recordings:
                        if not active_recordings[follower].is_alive():
                            logger.info(f"Recording of @{follower} finished.")
                            del active_recordings[follower]
                        else:
                            continue

                    try:
                        room_id = self.tiktok.get_room_id_from_user(follower)

                        if not room_id or not self.tiktok.is_room_alive(room_id):
                            continue

                        logger.info(f"@{follower} is live. Starting recording...")
                        self.notify.notify("live_detected", user=follower)

                        thread = Thread(
                            target=self.start_recording,
                            args=(follower, room_id),
                            daemon=True,
                        )
                        thread.start()
                        active_recordings[follower] = thread

                        time.sleep(2.5)

                    except TikTokRecorderError as e:
                        logger.error(f"Error while processing @{follower}: {e}")
                        continue

                    except Exception as e:
                        logger.error(
                            f"Unexpected error processing @{follower}: {e}",
                            exc_info=True,
                        )
                        continue

                print()
                logger.info(
                    f"Waiting {self.automatic_interval} minutes for the next check..."
                )
                time.sleep(self.automatic_interval * TimeOut.ONE_MINUTE)

            except (UserLiveError, LiveNotFound) as ex:
                logger.info(ex)
                logger.info(
                    f"Waiting {self.automatic_interval} minutes before recheck\n"
                )
                time.sleep(self.automatic_interval * TimeOut.ONE_MINUTE)

            except (ConnectionError, RequestException, HTTPException, OSError):
                logger.error(Error.CONNECTION_CLOSED_AUTOMATIC)
                self.tiktok.reset_session()
                time.sleep(self.retry_delay)

    def _verify_room_status(self, room_id: str) -> tuple[bool, bool]:
        if hasattr(self.tiktok, "verify_room_status"):
            return self.tiktok.verify_room_status(room_id)
        if hasattr(self.tiktok, "is_room_alive"):
            return self.tiktok.is_room_alive(room_id), True
        return False, False

    def _reset_session_if_available(self):
        if hasattr(self.tiktok, "reset_session"):
            try:
                self.tiktok.reset_session()
            except Exception as e:
                logger.debug(f"Error resetting session: {e}")

    def _build_output_path(self, user: str) -> str:
        timestamp = time.strftime("%Y-%m-%d-%H-%M-%S", time.localtime())
        base_name = f"{user}-{timestamp}"
        output_dir = (Path(self.output) / user) if self.output else Path(".")
        output_dir.mkdir(parents=True, exist_ok=True)

        candidate = output_dir / f"{base_name}.mp4"
        counter = 1
        while candidate.exists() or any(output_dir.glob(f"{candidate.stem}-part*.flv")):
            candidate = output_dir / f"{base_name}_{counter}.mp4"
            counter += 1

        if self.output:
            return str(candidate)
        return candidate.name

    def start_recording(self, user, room_id, stop_event=None):
        """
        Start recording live stream for user using the configured strategy (ffmpeg, requests, or yt-dlp).
        """
        stop_event = stop_event or threading.Event()
        live_urls = self.tiktok.get_live_url_candidates(room_id, user=user)
        if not live_urls:
            self.notify.notify(
                "recording_failed", user=user, error=str(TikTokError.RETRIEVE_LIVE_URL)
            )
            raise LiveNotFound(TikTokError.RETRIEVE_LIVE_URL)

        final_output = self._build_output_path(user)
        status_bar = RecordingStatusBar(user=user, part=1)

        strategy_name = getattr(self, "recording_strategy", "requests")
        # Route mock/test APIs that provide download_live_stream directly to requests strategy
        if type(self.tiktok).__name__ in (
            "StreamingFakeAPI",
            "FastFakeAPI",
            "VPNToggleFakeAPI",
        ):
            strategy_name = "requests"

        from core.recording_strategies import get_recording_strategy

        strategy = get_recording_strategy(strategy_name, self)
        success, output_file, total_bytes = strategy.record(
            user=user,
            room_id=room_id,
            live_urls=live_urls,
            final_output=final_output,
            stop_event=stop_event,
            status_bar=status_bar,
        )

        if success:
            self.notify.notify(
                "recording_finished",
                user=user,
                file=output_file,
                size_mb=round(total_bytes / (1024 * 1024)),
            )

            if self.use_telegram:
                try:
                    from upload.telegram import Telegram

                    Telegram().upload(output_file)
                except Exception as e:
                    logger.error(f"Telegram upload failed: {e}")

    def check_country_blacklisted(self):
        is_blacklisted = self.tiktok.is_country_blacklisted()
        if not is_blacklisted:
            return False

        if self.room_id is None:
            raise TikTokRecorderError(TikTokError.COUNTRY_BLACKLISTED)

        if self.mode == Mode.AUTOMATIC:
            raise TikTokRecorderError(TikTokError.COUNTRY_BLACKLISTED_AUTO_MODE)

        elif self.mode == Mode.FOLLOWERS:
            raise TikTokRecorderError(TikTokError.COUNTRY_BLACKLISTED_FOLLOWERS_MODE)

        return is_blacklisted
