import collections
import subprocess
import time
from pathlib import Path
from threading import Event, Thread

from utils.logger_manager import logger
from utils.status_bar import RecordingStatusBar
from utils.video_management import VideoManagement


class BaseRecordingStrategy:
    """Base class for stream recording strategies."""

    def __init__(self, recorder):
        self.recorder = recorder

    def record(
        self,
        user: str,
        room_id: str,
        live_urls: list[str],
        final_output: str,
        stop_event: Event | None = None,
        status_bar: RecordingStatusBar = None,
    ) -> tuple[bool, str, int]:
        """
        Executes recording.
        Returns (success: bool, output_file: str, total_bytes: int).
        """
        raise NotImplementedError


class YtDlpStrategy(BaseRecordingStrategy):
    """
    Strategy 3: Live stream capture via yt-dlp.
    Leverages yt-dlp's battle-tested HLS downloader and fragment retry logic.
    """

    def record(
        self,
        user: str,
        room_id: str,
        live_urls: list[str],
        final_output: str,
        stop_event: Event | None = None,
        status_bar: RecordingStatusBar = None,
    ) -> tuple[bool, str, int]:
        stop_event = stop_event or Event()
        yt_dlp_bin = getattr(self.recorder, "yt_dlp_path", None) or "yt-dlp"
        min_stream_bytes = 4096
        total_bytes = 0

        # Ensure output directory exists
        Path(final_output).parent.mkdir(parents=True, exist_ok=True)

        # Candidate targets: prioritize HLS (.m3u8) streams, then other formats, fallback to live user URL
        target_urls = []
        if live_urls:
            hls_urls = [u for u in live_urls if ".m3u8" in u or "hls" in u]
            other_urls = [u for u in live_urls if u not in hls_urls]
            target_urls.extend(hls_urls)
            target_urls.extend(other_urls)
        target_urls.append(f"https://www.tiktok.com/@{user}/live")

        for index, target_url in enumerate(target_urls, start=1):
            if stop_event.is_set():
                break

            marker_file = Path(f"{final_output}.in_progress")
            try:
                marker_file.touch(exist_ok=True)
            except Exception:
                pass

            logger.info(
                f"[yt-dlp Strategy] Starting recording for @{user} (attempt {index}/{len(target_urls)})..."
            )
            self.recorder.notify.notify(
                "recording_started",
                user=user,
                stream_index=index,
                total=len(target_urls),
            )

            cmd = [
                yt_dlp_bin,
                "--no-part",
                "--no-warnings",
                "--no-progress",
                "--socket-timeout",
                "15",
                "--retries",
                "10",
                "--fragment-retries",
                "10",
                "--add-header",
                "Referer:https://www.tiktok.com/",
                "--add-header",
                "Origin:https://www.tiktok.com",
                "-o",
                final_output,
            ]

            if getattr(self.recorder, "_proxy", None):
                cmd.extend(["--proxy", self.recorder._proxy])
            if self.recorder.ffmpeg_path:
                cmd.extend(["--ffmpeg-location", self.recorder.ffmpeg_path])
            if getattr(self.recorder, "_cookies", None) and isinstance(
                self.recorder._cookies, dict
            ):
                cookie_str = "; ".join(
                    f"{k}={v}" for k, v in self.recorder._cookies.items() if v
                )
                if cookie_str:
                    cmd.extend(["--add-header", f"Cookie:{cookie_str}"])

            cmd.append(target_url)

            try:
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                )
            except Exception as e:
                logger.error(f"[yt-dlp Strategy] Failed to launch yt-dlp: {e}")
                try:
                    marker_file.unlink(missing_ok=True)
                except Exception:
                    pass
                continue

            # Continuously drain stderr in background daemon thread to prevent OS pipe buffer deadlock
            stderr_buffer = collections.deque(maxlen=30)
            if getattr(proc, "stderr", None):

                def _drain_stderr(pipe):
                    try:
                        for line in iter(pipe.readline, b""):
                            decoded = line.decode("utf-8", errors="replace").strip()
                            if decoded:
                                stderr_buffer.append(decoded)
                    except Exception:
                        pass
                    finally:
                        try:
                            pipe.close()
                        except Exception:
                            pass

                stderr_drain_thread = Thread(
                    target=_drain_stderr, args=(proc.stderr,), daemon=True
                )
                stderr_drain_thread.start()

            start_time = time.time()
            last_room_check = start_time
            last_bytes_seen = 0
            last_growth_time = start_time
            stall_timeout = 45.0  # seconds with zero byte growth before timeout

            if status_bar:
                status_bar.start()

            try:
                while proc.poll() is None:
                    if stop_event.is_set():
                        logger.info(f"Stopping yt-dlp recording for @{user}...")
                        proc.terminate()
                        try:
                            proc.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            proc.kill()
                        break

                    now = time.time()

                    # Check room status every 5 seconds to prevent hanging on stalled streams
                    if now - last_room_check >= 5.0:
                        last_room_check = now
                        is_alive, is_confirmed = self.recorder._verify_room_status(
                            room_id
                        )
                        if is_confirmed and not is_alive:
                            logger.info(
                                f"User @{user} is no longer live. Stopping yt-dlp recording."
                            )
                            self.recorder.notify.notify("user_offline", user=user)
                            proc.terminate()
                            try:
                                proc.wait(timeout=5)
                            except subprocess.TimeoutExpired:
                                proc.kill()
                            break

                    # Monitor duration
                    elapsed = now - start_time
                    if self.recorder.duration and elapsed >= self.recorder.duration:
                        proc.terminate()
                        try:
                            proc.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            proc.kill()
                        break

                    # Monitor recorded bytes and update status bar
                    if Path(final_output).exists():
                        total_bytes = Path(final_output).stat().st_size
                        if total_bytes > last_bytes_seen:
                            last_bytes_seen = total_bytes
                            last_growth_time = now
                        if status_bar:
                            status_bar.update(total_bytes)

                    # Stall detection: if stream has run for 20s grace period and no data received for stall_timeout
                    if (now - start_time >= 20.0) and (
                        now - last_growth_time >= stall_timeout
                    ):
                        logger.warning(
                            f"[yt-dlp Strategy] Stream for @{user} stalled (no data for {int(now - last_growth_time)}s). "
                            "Terminating process to retry or try next candidate stream..."
                        )
                        proc.terminate()
                        try:
                            proc.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            proc.kill()
                        break

                    time.sleep(0.5)

            except KeyboardInterrupt:
                if status_bar:
                    status_bar.clear()
                logger.info(
                    f"Ctrl-C detected: Stopping recording for @{user} and finalizing video "
                    "(press Ctrl-C again to exit)..."
                )
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except Exception:
                    proc.kill()
                try:
                    marker_file.unlink(missing_ok=True)
                except Exception:
                    pass
                if (
                    Path(final_output).exists()
                    and Path(final_output).stat().st_size >= min_stream_bytes
                ):
                    VideoManagement.sanitize_mp4_timestamps(
                        final_output, ffmpeg_path=self.recorder.ffmpeg_path
                    )
                    total_bytes = Path(final_output).stat().st_size
                    size_mb = total_bytes / (1024 * 1024)
                    logger.info(
                        f"[yt-dlp Strategy] Recording finished for @{user} ({size_mb:.1f} MB saved)."
                    )
                    return True, final_output, total_bytes
                return False, final_output, total_bytes

            # Capture remaining output/errors if process finished
            stderr_msg = "\n".join(stderr_buffer).strip()

            if Path(final_output).exists():
                total_bytes = Path(final_output).stat().st_size

            try:
                marker_file.unlink(missing_ok=True)
            except Exception:
                pass

            if total_bytes >= min_stream_bytes:
                if status_bar:
                    status_bar.finish()
                # Run quick timestamp sanitization on final MP4 to ensure valid duration & seekability
                VideoManagement.sanitize_mp4_timestamps(
                    final_output, ffmpeg_path=self.recorder.ffmpeg_path
                )
                if Path(final_output).exists():
                    total_bytes = Path(final_output).stat().st_size
                size_mb = total_bytes / (1024 * 1024)
                logger.info(
                    f"[yt-dlp Strategy] Recording finished for @{user} ({size_mb:.1f} MB saved)."
                )
                return True, final_output, total_bytes
            else:
                if stderr_msg:
                    logger.warning(
                        f"[yt-dlp Strategy] Stream {index} failed: {stderr_msg}"
                    )
                Path(final_output).unlink(missing_ok=True)

        return False, final_output, total_bytes


class RequestsStrategy(BaseRecordingStrategy):
    """
    Strategy 2: Python chunked streaming using requests (legacy engine).
    Downloads segments to part*.flv and concatenates/converts to MP4 with FFmpeg.
    """

    def record(
        self,
        user: str,
        room_id: str,
        live_urls: list[str],
        final_output: str,
        stop_event: Event | None = None,
        status_bar: RecordingStatusBar = None,
    ) -> tuple[bool, str, int]:
        stop_event = stop_event or Event()
        base_stem = Path(final_output).with_suffix("")
        min_stream_bytes = 4096
        total_bytes_written = 0
        recorded_segments = []

        from http.client import HTTPException

        from requests import RequestException

        for index, live_url in enumerate(live_urls, start=1):
            if stop_event.is_set():
                break

            if self.recorder.duration:
                logger.info(
                    f"[Requests Strategy] Started recording for {self.recorder.duration} seconds "
                    f"(stream {index}/{len(live_urls)})"
                )
            else:
                logger.info(
                    f"[Requests Strategy] Started recording (stream {index}/{len(live_urls)})..."
                )

            self.recorder.notify.notify(
                "recording_started",
                user=user,
                stream_index=index,
                total=len(live_urls),
            )

            buffer_size = 512 * 1024
            part_index = 1
            start_time = time.time()

            while not stop_event.is_set():
                # Check room status
                is_alive, is_confirmed = self.recorder._verify_room_status(room_id)
                if is_confirmed and not is_alive:
                    if status_bar:
                        status_bar.clear()
                    logger.info("User is no longer live. Stopping recording.")
                    self.recorder.notify.notify("user_offline", user=user)
                    stop_event.set()
                    break
                elif not is_confirmed:
                    if status_bar:
                        status_bar.clear()
                    logger.warning(
                        "Network connection interrupted (e.g. VPN switch). Waiting to reconnect..."
                    )
                    self.recorder._reset_session_if_available()
                    time.sleep(self.recorder.retry_delay)
                    continue

                segment_path = f"{base_stem}-part{part_index}.flv"
                segment_bytes = 0
                buffer = bytearray()
                part_reason = "Stream completed"

                if part_index > 1:
                    logger.info(f"Started recording (Part {part_index})...")

                try:
                    with open(segment_path, "wb") as out_file:
                        try:
                            for chunk in self.recorder.tiktok.download_live_stream(
                                live_url
                            ):
                                if stop_event.is_set():
                                    break
                                buffer.extend(chunk)
                                segment_bytes += len(chunk)
                                total_bytes_written += len(chunk)
                                if status_bar:
                                    status_bar.update(
                                        total_bytes_written, part=part_index
                                    )
                                if len(buffer) >= buffer_size:
                                    out_file.write(buffer)
                                    buffer.clear()

                                elapsed_time = time.time() - start_time
                                if (
                                    self.recorder.duration
                                    and elapsed_time >= self.recorder.duration
                                ):
                                    stop_event.set()
                                    part_reason = f"Duration limit reached ({self.recorder.duration}s)"
                                    break
                            else:
                                is_alive, is_confirmed = (
                                    self.recorder._verify_room_status(room_id)
                                )
                                if is_confirmed and not is_alive:
                                    if status_bar:
                                        status_bar.clear()
                                    logger.info(
                                        "User is no longer live. Stopping recording."
                                    )
                                    self.recorder.notify.notify(
                                        "user_offline", user=user
                                    )
                                    stop_event.set()
                                    part_reason = "Creator ended live stream"
                                else:
                                    if status_bar:
                                        status_bar.clear()
                                    part_reason = "TikTok CDN stream connection ended"
                                    logger.info(
                                        "Stream connection ended. Refreshing live stream URL and resuming recording..."
                                    )
                                    self.recorder._reset_session_if_available()
                                    try:
                                        fresh_urls = self.recorder.tiktok.get_live_urls(
                                            room_id, user=user
                                        )
                                        if fresh_urls:
                                            live_url = fresh_urls[0]
                                    except Exception:
                                        pass
                        finally:
                            if buffer:
                                out_file.write(buffer)
                                buffer.clear()
                            out_file.flush()

                except ConnectionError as ex:
                    if status_bar:
                        status_bar.clear()
                    part_reason = f"Network connection lost ({ex})"
                    logger.warning(
                        f"Connection lost ({ex}). Resetting network session and resuming recording..."
                    )
                    self.recorder._reset_session_if_available()
                    time.sleep(self.recorder.retry_delay)
                    try:
                        fresh_urls = self.recorder.tiktok.get_live_urls(
                            room_id, user=user
                        )
                        if fresh_urls:
                            live_url = fresh_urls[0]
                    except Exception:
                        pass
                except (RequestException, HTTPException, OSError) as ex:
                    if status_bar:
                        status_bar.clear()
                    part_reason = f"Network interruption / VPN toggle ({ex})"
                    logger.warning(
                        f"Network interruption ({ex}). Resetting session and resuming recording..."
                    )
                    self.recorder._reset_session_if_available()
                    time.sleep(self.recorder.retry_delay)
                    try:
                        fresh_urls = self.recorder.tiktok.get_live_urls(
                            room_id, user=user
                        )
                        if fresh_urls:
                            live_url = fresh_urls[0]
                    except Exception:
                        pass

                except KeyboardInterrupt:
                    if status_bar:
                        status_bar.clear()
                    logger.info(
                        f"Ctrl-C detected: Stopping recording for @{user} and finalizing video "
                        "(press Ctrl-C again to exit)..."
                    )
                    stop_event.set()
                    part_reason = "Recording stopped by user (Ctrl-C)"
                except Exception as ex:
                    if status_bar:
                        status_bar.clear()
                    logger.error(
                        f"Unexpected error during recording: {ex}", exc_info=True
                    )
                    self.recorder.notify.notify(
                        "recording_failed", user=user, error=str(ex)
                    )
                    stop_event.set()

                if segment_bytes >= min_stream_bytes:
                    if status_bar:
                        status_bar.clear()
                    size_mb = segment_bytes / (1024 * 1024)
                    logger.info(
                        f"Part {part_index} recording completed ({size_mb:.1f} MB saved). Reason: {part_reason}."
                    )
                    recorded_segments.append(segment_path)
                    part_index += 1
                    if not stop_event.is_set():
                        logger.info(f"Continuing with Part {part_index} recording...")
                else:
                    Path(segment_path).unlink(missing_ok=True)
                    if not stop_event.is_set() and segment_bytes == 0:
                        time.sleep(self.recorder.retry_delay)

            if total_bytes_written >= min_stream_bytes and recorded_segments:
                break

        if not recorded_segments:
            return False, final_output, total_bytes_written

        logger.info("Recording finished. Processing video...")
        from core.tiktok_recorder import _conversion_lock

        with _conversion_lock:
            success = VideoManagement.convert_segments_to_mp4(
                recorded_segments,
                final_output,
                self.recorder.bitrate,
                self.recorder.ffmpeg_path,
                self.recorder.keep_flv,
                self.recorder.move_to_recycle_bin,
            )

        return success, final_output, total_bytes_written


def get_recording_strategy(strategy_name: str, recorder) -> BaseRecordingStrategy:
    """Factory to retrieve the appropriate stream recording strategy."""
    clean_name = (strategy_name or "requests").strip().lower()
    if clean_name == "yt-dlp":
        return YtDlpStrategy(recorder)
    if clean_name == "ffmpeg":
        logger.warning(
            "[Strategy] The 'ffmpeg' direct download strategy has been removed. Using 'requests' strategy."
        )
    # Default to RequestsStrategy (chunked FLV engine)
    return RequestsStrategy(recorder)
