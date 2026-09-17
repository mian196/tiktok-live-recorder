import subprocess
import time
from pathlib import Path
from threading import Event

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
        stop_event: Event = None,
        status_bar: RecordingStatusBar = None,
    ) -> tuple[bool, str, int]:
        """
        Executes recording.
        Returns (success: bool, output_file: str, total_bytes: int).
        """
        raise NotImplementedError


class FFmpegStrategy(BaseRecordingStrategy):
    """
    Strategy 1 (Default): Direct stream ingestion via FFmpeg.
    Streams directly into a single cohesive MP4 file with native reconnect flags.
    Completely avoids file part-splitting and post-recording transcoding.
    """

    def record(
        self,
        user: str,
        room_id: str,
        live_urls: list[str],
        final_output: str,
        stop_event: Event = None,
        status_bar: RecordingStatusBar = None,
    ) -> tuple[bool, str, int]:
        if not live_urls:
            return False, final_output, 0

        stop_event = stop_event or Event()
        ffmpeg_bin = self.recorder.ffmpeg_path or "ffmpeg"
        min_stream_bytes = 4096
        total_bytes = 0

        # Ensure output directory exists
        Path(final_output).parent.mkdir(parents=True, exist_ok=True)

        user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.6478.127 Safari/537.36"
        if (
            hasattr(self.recorder.tiktok, "_client_wrapper")
            and self.recorder.tiktok._client_wrapper
        ):
            user_agent = self.recorder.tiktok._client_wrapper.headers.get(
                "User-Agent", user_agent
            )

        cookie_header = ""
        if getattr(self.recorder, "_cookies", None) and isinstance(
            self.recorder._cookies, dict
        ):
            cookie_str = "; ".join(
                f"{k}={v}" for k, v in self.recorder._cookies.items() if v
            )
            if cookie_str:
                cookie_header = f"Cookie: {cookie_str}\r\n"

        headers_str = (
            f"User-Agent: {user_agent}\r\n"
            "Referer: https://www.tiktok.com/\r\n"
            "Origin: https://www.tiktok.com\r\n"
            f"{cookie_header}"
        )

        for index, live_url in enumerate(live_urls, start=1):
            if stop_event.is_set():
                break

            logger.info(
                f"[FFmpeg Strategy] Started direct recording for @{user} (stream {index}/{len(live_urls)})..."
            )
            self.recorder.notify.notify(
                "recording_started",
                user=user,
                stream_index=index,
                total=len(live_urls),
            )

            marker_file = Path(f"{final_output}.in_progress")
            try:
                marker_file.touch(exist_ok=True)
            except Exception:
                pass

            cmd = [
                ffmpeg_bin,
                "-hide_banner",
                "-loglevel",
                "warning",
                "-y",
                "-reconnect",
                "1",
                "-reconnect_at_eof",
                "1",
                "-reconnect_streamed",
                "1",
                "-reconnect_delay_max",
                str(max(1, getattr(self.recorder, "retry_delay", 5))),
                "-rw_timeout",
                "15000000",
                "-timeout",
                "10000000",
                "-headers",
                headers_str,
                "-i",
                live_url,
            ]

            if getattr(self.recorder, "_proxy", None):
                cmd.extend(["-http_proxy", self.recorder._proxy])
            if self.recorder.duration:
                cmd.extend(["-t", str(self.recorder.duration)])
            if getattr(self.recorder, "bitrate", None):
                cmd.extend(["-b:v", self.recorder.bitrate])

            # Output directly to MP4 container with fragmented MP4 flags for crash-resilience
            cmd.extend(
                [
                    "-c",
                    "copy",
                    "-movflags",
                    "+empty_moov+frag_keyframe+default_base_moof",
                    final_output,
                ]
            )

            try:
                proc = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
            except Exception as e:
                logger.error(f"[FFmpeg Strategy] Failed to launch FFmpeg: {e}")
                try:
                    marker_file.unlink(missing_ok=True)
                except Exception:
                    pass
                continue

            start_time = time.time()
            if status_bar:
                status_bar.start()

            try:
                while proc.poll() is None:
                    if stop_event.is_set():
                        logger.info(f"Stopping recording for @{user} gracefully...")
                        try:
                            # Send 'q' to ffmpeg stdin to write MP4 trailer cleanly
                            if proc.stdin:
                                proc.stdin.write(b"q\n")
                                proc.stdin.flush()
                        except Exception:
                            pass
                        try:
                            proc.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            proc.terminate()
                        break

                    # Monitor duration if specified
                    elapsed = time.time() - start_time
                    if self.recorder.duration and elapsed >= self.recorder.duration:
                        try:
                            if proc.stdin:
                                proc.stdin.write(b"q\n")
                                proc.stdin.flush()
                            proc.wait(timeout=5)
                        except Exception:
                            proc.terminate()
                        break

                    # Update status bar with output file size
                    if Path(final_output).exists():
                        total_bytes = Path(final_output).stat().st_size
                        if status_bar:
                            status_bar.update(total_bytes)

                    time.sleep(0.5)

            except KeyboardInterrupt:
                if status_bar:
                    status_bar.clear()
                logger.info(f"Recording stopped by user for @{user}.")
                try:
                    if proc.stdin:
                        proc.stdin.write(b"q\n")
                        proc.stdin.flush()
                    proc.wait(timeout=5)
                except Exception:
                    proc.terminate()
                try:
                    marker_file.unlink(missing_ok=True)
                except Exception:
                    pass
                if (
                    Path(final_output).exists()
                    and Path(final_output).stat().st_size >= min_stream_bytes
                ):
                    VideoManagement.sanitize_mp4_timestamps(
                        final_output, ffmpeg_path=ffmpeg_bin
                    )
                raise

            if Path(final_output).exists():
                total_bytes = Path(final_output).stat().st_size

            try:
                marker_file.unlink(missing_ok=True)
            except Exception:
                pass

            if total_bytes >= min_stream_bytes:
                if status_bar:
                    status_bar.finish()
                # Run quick timestamp sanitization on final MP4
                VideoManagement.sanitize_mp4_timestamps(
                    final_output, ffmpeg_path=ffmpeg_bin
                )
                if Path(final_output).exists():
                    total_bytes = Path(final_output).stat().st_size
                size_mb = total_bytes / (1024 * 1024)
                logger.info(
                    f"[FFmpeg Strategy] Recording finished for @{user} ({size_mb:.1f} MB saved directly to MP4)."
                )
                return True, final_output, total_bytes
            else:
                logger.warning(
                    f"[FFmpeg Strategy] Stream {index} captured only {total_bytes} bytes. Trying next candidate..."
                )
                # Clean up empty file candidate
                Path(final_output).unlink(missing_ok=True)

        return False, final_output, total_bytes


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
        stop_event: Event = None,
        status_bar: RecordingStatusBar = None,
    ) -> tuple[bool, str, int]:
        stop_event = stop_event or Event()
        yt_dlp_bin = getattr(self.recorder, "yt_dlp_path", None) or "yt-dlp"
        min_stream_bytes = 4096
        total_bytes = 0

        # Ensure output directory exists
        Path(final_output).parent.mkdir(parents=True, exist_ok=True)

        # Candidate targets: primary stream candidate URL, fallback to live user URL
        target_urls = []
        if live_urls:
            target_urls.extend(live_urls)
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
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
            except Exception as e:
                logger.error(f"[yt-dlp Strategy] Failed to launch yt-dlp: {e}")
                try:
                    marker_file.unlink(missing_ok=True)
                except Exception:
                    pass
                continue

            start_time = time.time()
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

                    # Monitor duration
                    elapsed = time.time() - start_time
                    if self.recorder.duration and elapsed >= self.recorder.duration:
                        proc.terminate()
                        try:
                            proc.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            proc.kill()
                        break

                    if Path(final_output).exists():
                        total_bytes = Path(final_output).stat().st_size
                        if status_bar:
                            status_bar.update(total_bytes)

                    time.sleep(0.5)

            except KeyboardInterrupt:
                if status_bar:
                    status_bar.clear()
                logger.info(f"Recording stopped by user for @{user}.")
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except Exception:
                    proc.kill()
                try:
                    marker_file.unlink(missing_ok=True)
                except Exception:
                    pass
                raise

            # Capture remaining output/errors if process finished
            stderr_msg = ""
            if getattr(proc, "stderr", None):
                try:
                    stderr_msg = (
                        proc.stderr.read().decode("utf-8", errors="replace").strip()
                    )
                except Exception:
                    pass

            if Path(final_output).exists():
                total_bytes = Path(final_output).stat().st_size

            try:
                marker_file.unlink(missing_ok=True)
            except Exception:
                pass

            if total_bytes >= min_stream_bytes:
                if status_bar:
                    status_bar.finish()
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
        stop_event: Event = None,
        status_bar: RecordingStatusBar = None,
    ) -> tuple[bool, str, int]:
        stop_event = stop_event or Event()
        base_stem = Path(final_output).with_suffix("")
        min_stream_bytes = 4096
        total_bytes_written = 0
        recorded_segments = []

        from requests import RequestException
        from http.client import HTTPException

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
                    logger.info("Recording stopped by user.")
                    stop_event.set()
                    raise
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
    elif clean_name == "ffmpeg":
        return FFmpegStrategy(recorder)
    # Default to RequestsStrategy (legacy FLV engine)
    return RequestsStrategy(recorder)
