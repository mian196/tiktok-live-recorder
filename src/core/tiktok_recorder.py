import time
from http.client import HTTPException
from pathlib import Path
from threading import Thread

from requests import RequestException

from core.tiktok_api import TikTokAPI
from notify.notifier import Notifier
from utils.logger_manager import logger
from utils.recorder_config import RecorderConfig
from utils.video_management import VideoManagement
from utils.custom_exceptions import LiveNotFound, UserLiveError, TikTokRecorderError
from utils.enums import Mode, Error, TimeOut, TikTokError


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
        self.quality = getattr(config, "quality", "best")
        self.users = config.users
        self._proxy = config.proxy
        self._cookies = config.cookies

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
            logger.info(f"Multi-user automatic mode activated for {len(self.users)} users: {', '.join(self.users)}\n")
        else:
            if self.url:
                self.user, self.room_id = self.tiktok.get_room_and_user_from_url(
                    self.url
                )

            if not self.user:
                self.user = self.tiktok.get_user_from_room_id(self.room_id)

            if not self.room_id:
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

    def manual_mode(self):
        if not self.tiktok.is_room_alive(self.room_id):
            raise UserLiveError(f"@{self.user}: {TikTokError.USER_NOT_CURRENTLY_LIVE}")

        self.start_recording(self.user, self.room_id)

    def automatic_mode(self):
        while True:
            try:
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

            except (ConnectionError, RequestException, HTTPException):
                logger.error(Error.CONNECTION_CLOSED_AUTOMATIC)
                time.sleep(TimeOut.CONNECTION_CLOSED * TimeOut.ONE_MINUTE)

    def automatic_mode_multi(self):
        """Check all users in a loop with small delays, then sleep the full interval."""
        while True:
            for user in self.users:
                try:
                    self.user = user
                    self.room_id = self.tiktok.get_room_id_from_user(user)
                    if self.room_id and self.tiktok.is_room_alive(self.room_id):
                        self.notify.notify("live_detected", user=user)
                        self.manual_mode()
                except (UserLiveError, LiveNotFound) as ex:
                    logger.info(ex)
                except (ConnectionError, RequestException, HTTPException):
                    logger.error(Error.CONNECTION_CLOSED_AUTOMATIC)
                    time.sleep(TimeOut.CONNECTION_CLOSED * TimeOut.ONE_MINUTE)
                    continue

                time.sleep(TimeOut.USER_CHECK_DELAY)

            logger.info(
                f"All users checked. Waiting {self.automatic_interval} minutes...\n"
            )
            time.sleep(self.automatic_interval * TimeOut.ONE_MINUTE)

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

            except (ConnectionError, RequestException, HTTPException):
                logger.error(Error.CONNECTION_CLOSED_AUTOMATIC)
                time.sleep(TimeOut.CONNECTION_CLOSED * TimeOut.ONE_MINUTE)

    def _build_output_path(self, user: str) -> str:
        filename = (
            f"TK_{user}_{time.strftime('%Y.%m.%d_%H-%M-%S', time.localtime())}.mp4"
        )
        if self.output:
            return str(Path(self.output) / filename)
        return filename

    def start_recording(self, user, room_id):
        """
        Start recording live
        """
        live_urls = self.tiktok.get_live_url_candidates(
            room_id, user=user, quality=self.quality
        )
        if not live_urls:
            self.notify.notify("recording_failed", user=user, error=str(TikTokError.RETRIEVE_LIVE_URL))
            raise LiveNotFound(TikTokError.RETRIEVE_LIVE_URL)

        final_output = self._build_output_path(user)
        base_stem = Path(final_output).with_suffix("")

        min_stream_bytes = 4096
        for index, live_url in enumerate(live_urls, start=1):
            if self.duration:
                logger.info(
                    f"Started recording for {self.duration} seconds "
                    f"(stream {index}/{len(live_urls)})"
                )
            else:
                logger.info(f"Started recording (stream {index}/{len(live_urls)})...")

            self.notify.notify(
                "recording_started",
                user=user,
                stream_index=index,
                total=len(live_urls),
            )

            buffer_size = 512 * 1024  # 512 KB buffer
            recorded_segments = []
            part_index = 1
            total_bytes_written = 0

            logger.info("[PRESS CTRL + C ONCE TO STOP]")
            stop_recording = False
            start_time = time.time()

            while not stop_recording:
                # Check room status before attempting connection/reconnection
                if not self.tiktok.is_room_alive(room_id):
                    logger.info("User is no longer live. Stopping recording.")
                    self.notify.notify("user_offline", user=user)
                    break

                segment_path = f"{base_stem}_part{part_index}.flv"
                segment_bytes = 0
                buffer = bytearray()

                try:
                    with open(segment_path, "wb") as out_file:
                        try:
                            for chunk in self.tiktok.download_live_stream(live_url):
                                buffer.extend(chunk)
                                segment_bytes += len(chunk)
                                total_bytes_written += len(chunk)
                                if len(buffer) >= buffer_size:
                                    out_file.write(buffer)
                                    buffer.clear()

                                elapsed_time = time.time() - start_time
                                if self.duration and elapsed_time >= self.duration:
                                    stop_recording = True
                                    break
                            else:
                                if not self.tiktok.is_room_alive(room_id):
                                    logger.info(
                                        "User is no longer live. Stopping recording."
                                    )
                                    self.notify.notify("user_offline", user=user)
                                    stop_recording = True
                        finally:
                            if buffer:
                                out_file.write(buffer)
                                buffer.clear()
                            out_file.flush()

                except ConnectionError:
                    if self.mode == Mode.AUTOMATIC:
                        logger.error(Error.CONNECTION_CLOSED_AUTOMATIC)
                        time.sleep(TimeOut.CONNECTION_CLOSED * TimeOut.ONE_MINUTE)
                except (RequestException, HTTPException, OSError) as ex:
                    logger.warning(f"Network hiccup, retrying: {ex}")
                    time.sleep(2)
                except KeyboardInterrupt:
                    logger.info("Recording stopped by user.")
                    stop_recording = True
                except Exception as ex:
                    logger.error(
                        f"Unexpected error during recording: {ex}",
                        exc_info=True,
                    )
                    self.notify.notify("recording_failed", user=user, error=str(ex))
                    stop_recording = True

                if segment_bytes >= min_stream_bytes:
                    recorded_segments.append(segment_path)
                    part_index += 1
                else:
                    Path(segment_path).unlink(missing_ok=True)
                    if not stop_recording and segment_bytes == 0:
                        time.sleep(2)

            if total_bytes_written >= min_stream_bytes and recorded_segments:
                break

            logger.warning(
                f"Stream {index}/{len(live_urls)} returned only {total_bytes_written} bytes. "
                "Trying another CDN/quality..."
            )
        else:
            self.notify.notify("recording_failed", user=user, error=str(TikTokError.RETRIEVE_LIVE_URL))
            raise LiveNotFound(TikTokError.RETRIEVE_LIVE_URL)

        logger.info("Recording finished. Processing video...")
        success = VideoManagement.convert_segments_to_mp4(
            recorded_segments,
            final_output,
            self.bitrate,
            self.ffmpeg_path,
            self.keep_flv,
        )

        if success:
            self.notify.notify(
                "recording_finished",
                user=user,
                file=final_output,
                size_mb=round(total_bytes_written / (1024 * 1024)),
            )

        if success and self.use_telegram:
            try:
                from upload.telegram import Telegram

                Telegram().upload(final_output)
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
