import json
import os
import sys
import tempfile
import threading
import time


def _format_duration(seconds: float) -> str:
    total_seconds = int(max(0, seconds))
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _format_size(bytes_val: int) -> str:
    if bytes_val >= 1024 * 1024 * 1024:
        return f"{bytes_val / (1024**3):.2f} GB"
    elif bytes_val >= 1024 * 1024:
        return f"{bytes_val / (1024**2):.1f} MB"
    elif bytes_val >= 1024:
        return f"{bytes_val / 1024:.0f} KB"
    return f"{bytes_val} B"


def _format_speed(bytes_per_sec: float) -> str:
    if bytes_per_sec >= 1024 * 1024:
        return f"{bytes_per_sec / (1024**2):.1f} MB/s"
    elif bytes_per_sec >= 1024:
        return f"{bytes_per_sec / 1024:.0f} KB/s"
    return f"{bytes_per_sec:.0f} B/s"


class _CrossProcessRenderLock:
    """Cross-thread and cross-process lock for console status bar rendering."""

    def __init__(self):
        self._thread_lock = threading.Lock()
        self._lock_file = os.path.join(
            tempfile.gettempdir(), "tiktok_recorder_statusbar.lock"
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
        except Exception:
            pass
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
        except Exception:
            pass
        finally:
            self._thread_lock.release()


_render_lock = _CrossProcessRenderLock()
_STATUS_DIR = os.path.join(tempfile.gettempdir(), "tiktok_live_status_registry")


class RecordingStatusBar:
    """
    Sleek, responsive multi-stream status bar pinned at terminal bottom.
    Supports concurrent multi-user streams with each active stream on its own line.
    """

    _active_bars: dict[str, "RecordingStatusBar"] = {}
    _last_rendered_lines_count: int = 0

    def __init__(self, user: str, part: int = 1, update_interval: float = 0.5):
        self.user = user
        self.part = part
        self.update_interval = update_interval
        self.start_time = time.time()
        self.last_update_time = 0.0
        self.last_bytes = 0
        self.speed = 0.0
        self._is_active = False

        if os.name == "nt":
            os.system("")

        try:
            os.makedirs(_STATUS_DIR, exist_ok=True)
        except Exception:
            pass

    def _get_status_file(self) -> str:
        safe_user = "".join(c for c in self.user if c.isalnum() or c in ("-", "_"))
        return os.path.join(_STATUS_DIR, f"{safe_user}.json")

    def _sync_to_file(self, total_bytes: int):
        try:
            data = {
                "user": self.user,
                "start_time": self.start_time,
                "last_bytes": total_bytes,
                "speed": self.speed,
                "part": self.part,
                "updated_at": time.time(),
                "pid": os.getpid(),
            }
            status_file = self._get_status_file()
            tmp_file = f"{status_file}.tmp"
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(data, f)
            os.replace(tmp_file, status_file)
        except Exception:
            pass

    def _remove_from_file(self):
        try:
            status_file = self._get_status_file()
            if os.path.exists(status_file):
                os.remove(status_file)
        except Exception:
            pass

    def start(self):
        self.start_time = time.time()
        self.last_update_time = self.start_time
        self.last_bytes = 0
        self._is_active = True
        RecordingStatusBar._active_bars[self.user] = self
        self._sync_to_file(0)

    def update(self, total_bytes: int, part: int = None):
        if not self._is_active:
            self.start()

        if part is not None:
            self.part = part

        now = time.time()
        elapsed_since_update = now - self.last_update_time

        if elapsed_since_update >= self.update_interval:
            bytes_delta = total_bytes - self.last_bytes
            if elapsed_since_update > 0:
                instant_speed = bytes_delta / elapsed_since_update
                self.speed = (
                    (0.7 * instant_speed) + (0.3 * self.speed)
                    if self.speed > 0
                    else instant_speed
                )

            self.last_update_time = now
            self.last_bytes = total_bytes
            self._sync_to_file(total_bytes)

            self._render()

    @classmethod
    def _collect_all_active_streams(cls) -> list[dict]:
        """Collects all active streams across all processes and threads."""
        streams: dict[str, dict] = {}
        now = time.time()

        # 1. Check file registry (cross-process)
        if os.path.exists(_STATUS_DIR):
            try:
                for fname in os.listdir(_STATUS_DIR):
                    if fname.endswith(".json"):
                        fpath = os.path.join(_STATUS_DIR, fname)
                        try:
                            with open(fpath, "r", encoding="utf-8") as f:
                                data = json.load(f)
                            if now - data.get("updated_at", 0) <= 5.0:
                                streams[data["user"]] = data
                            else:
                                os.remove(fpath)
                        except Exception:
                            pass
            except Exception:
                pass

        # 2. Check local in-memory active bars
        for u, bar in list(cls._active_bars.items()):
            if bar._is_active:
                streams[u] = {
                    "user": bar.user,
                    "start_time": bar.start_time,
                    "last_bytes": bar.last_bytes,
                    "speed": bar.speed,
                    "part": bar.part,
                    "updated_at": now,
                    "pid": os.getpid(),
                }

        return sorted(streams.values(), key=lambda s: s["user"].lower())

    @classmethod
    def _format_stream_line(cls, stream: dict) -> str:
        now = time.time()
        elapsed_time = max(0, now - stream.get("start_time", now))
        total_bytes = stream.get("last_bytes", 0)
        speed = stream.get("speed", 0.0)
        part = stream.get("part", 1)
        user = stream.get("user", "recorder")

        # ANSI Colors
        c_reset = "\033[0m"
        c_red_bold = "\033[1;31m"
        c_cyan_bold = "\033[1;36m"
        c_white_bold = "\033[1;37m"
        c_green = "\033[1;32m"
        c_yellow = "\033[1;33m"
        c_dim = "\033[90m"

        rec_dot = f"{c_red_bold}● REC{c_reset}"
        sep = f"{c_dim}│{c_reset}"

        duration_str = _format_duration(elapsed_time)
        size_str = _format_size(total_bytes)
        speed_str = _format_speed(speed)
        part_str = f"Part {part}" if part > 1 else "Live"

        user_badge = f"{c_cyan_bold}@{user}{c_reset}"
        time_badge = f"{c_white_bold}⏱ {duration_str}{c_reset}"
        size_badge = f"{c_green}💾 {size_str}{c_reset}"
        speed_badge = f"{c_yellow}⚡ {speed_str}{c_reset}"
        part_badge = f"{c_dim}[{part_str}]{c_reset}"

        return (
            f" {rec_dot} {sep} {user_badge} {sep} "
            f"{time_badge} {sep} {size_badge} {sep} "
            f"{speed_badge} {sep} {part_badge} "
        )

    def _render(self):
        if not sys.stdout.isatty():
            return

        with _render_lock:
            streams = self._collect_all_active_streams()
            if not streams:
                RecordingStatusBar._erase_rendered_lines()
                return

            lines = [self._format_stream_line(s) for s in streams]
            RecordingStatusBar._draw_lines(lines)

    @classmethod
    def _draw_lines(cls, lines: list[str]):
        """Draws multi-line status cleanly without jumping or flickering."""
        if not sys.stdout.isatty():
            return

        n_lines = len(lines)
        prev_n = cls._last_rendered_lines_count

        # Move cursor to the top of the previously rendered block
        if prev_n > 1:
            sys.stdout.write(f"\r\033[{prev_n - 1}A")
        elif prev_n == 1:
            sys.stdout.write("\r")

        # Write each line
        for i, line in enumerate(lines):
            if i < n_lines - 1:
                sys.stdout.write(f"\r\033[2K{line}\n")
            else:
                sys.stdout.write(f"\r\033[2K{line}")

        # If previous count was larger, clear remaining lines below
        if prev_n > n_lines:
            extra = prev_n - n_lines
            for _ in range(extra):
                sys.stdout.write("\n\033[2K")
            sys.stdout.write(f"\033[{extra}A")

        cls._last_rendered_lines_count = n_lines
        sys.stdout.flush()

    @classmethod
    def _erase_rendered_lines(cls):
        """Erases all status bar lines currently on screen."""
        if not sys.stdout.isatty():
            return

        prev_n = cls._last_rendered_lines_count
        if prev_n > 0:
            if prev_n > 1:
                sys.stdout.write(f"\r\033[{prev_n - 1}A")
            for _ in range(prev_n):
                sys.stdout.write("\r\033[2K\n")
            sys.stdout.write(f"\033[{prev_n}A\r")
            cls._last_rendered_lines_count = 0
            sys.stdout.flush()

    @classmethod
    def clear_display_for_log(cls):
        """Erases status lines so a log message prints cleanly above them."""
        with _render_lock:
            cls._erase_rendered_lines()

    @classmethod
    def render_all(cls):
        """Re-renders all active status lines (e.g. after a log message)."""
        if not sys.stdout.isatty():
            return
        with _render_lock:
            streams = cls._collect_all_active_streams()
            if streams:
                lines = [cls._format_stream_line(s) for s in streams]
                cls._draw_lines(lines)

    def clear(self):
        """Erase this user from status bar."""
        self._remove_from_file()
        RecordingStatusBar._active_bars.pop(self.user, None)
        self._is_active = False
        with _render_lock:
            streams = RecordingStatusBar._collect_all_active_streams()
            if streams:
                lines = [RecordingStatusBar._format_stream_line(s) for s in streams]
                RecordingStatusBar._draw_lines(lines)
            else:
                RecordingStatusBar._erase_rendered_lines()

    def finish(self, message: str = None):
        """End status bar and optionally print a message."""
        self.clear()
        if message:
            print(message)
