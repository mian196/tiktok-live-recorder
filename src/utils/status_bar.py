import os
import sys
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


class RecordingStatusBar:
    """
    Sleek, responsive TUI bottom status bar for active stream recording.
    """

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

    def start(self):
        self.start_time = time.time()
        self.last_update_time = self.start_time
        self.last_bytes = 0
        self._is_active = True

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

            self._render(total_bytes, now - self.start_time)

    def _render(self, total_bytes: int, elapsed_time: float):
        if not sys.stdout.isatty():
            return

        duration_str = _format_duration(elapsed_time)
        size_str = _format_size(total_bytes)
        speed_str = _format_speed(self.speed)
        part_str = f"Part {self.part}" if self.part > 1 else "Live"

        # ANSI Colors
        c_reset = "\033[0m"
        c_red_bold = "\033[1;31m"
        c_cyan_bold = "\033[1;36m"
        c_white_bold = "\033[1;37m"
        c_green = "\033[1;32m"
        c_yellow = "\033[1;33m"
        c_dim = "\033[90m"

        rec_dot = f"{c_red_bold}● REC{c_reset}"
        user_badge = f"{c_cyan_bold}@{self.user}{c_reset}"
        time_badge = f"{c_white_bold}⏱ {duration_str}{c_reset}"
        size_badge = f"{c_green}💾 {size_str}{c_reset}"
        speed_badge = f"{c_yellow}⚡ {speed_str}{c_reset}"
        part_badge = f"{c_dim}[{part_str}]{c_reset}"
        sep = f"{c_dim}│{c_reset}"

        status_line = (
            f"\r {rec_dot} {sep} {user_badge} {sep} "
            f"{time_badge} {sep} {size_badge} {sep} "
            f"{speed_badge} {sep} {part_badge} "
        )

        sys.stdout.write(f"\r\033[2K{status_line}")
        sys.stdout.flush()

    def clear(self):
        """Erase the status bar line from the terminal."""
        if self._is_active and sys.stdout.isatty():
            sys.stdout.write("\r\033[2K\r")
            sys.stdout.flush()
        self._is_active = False

    def finish(self, message: str = None):
        """End status bar and optionally print a message."""
        self.clear()
        if message:
            print(message)
