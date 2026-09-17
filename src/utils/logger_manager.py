import logging
import sys
from logging.handlers import RotatingFileHandler


class MaxLevelFilter(logging.Filter):
    """
    Filter that only allows log records up to a specified maximum level.
    """

    def __init__(self, max_level):
        super().__init__()
        self.max_level = max_level

    def filter(self, record):
        return record.levelno <= self.max_level


class StatusBarAwareStreamHandler(logging.StreamHandler):
    """
    StreamHandler that clears the active status bar line before printing
    a log message, ensuring log messages and alerts appear cleanly above
    the status bar without spawning duplicate REC lines.
    """

    def emit(self, record):
        try:
            msg = self.format(record)
            stream = self.stream
            if stream.isatty():
                # Erase current bottom line, write log message, then flush
                stream.write(f"\r\033[2K{msg}{self.terminator}")
                stream.flush()
                # Re-render active status bars on the new bottom line
                try:
                    from utils.status_bar import RecordingStatusBar

                    RecordingStatusBar.render_all()
                except Exception:
                    pass
            else:
                stream.write(f"{msg}{self.terminator}")
                stream.flush()
        except RecursionError:
            raise
        except Exception:
            self.handleError(record)


class LoggerManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(LoggerManager, cls).__new__(cls)
            cls._instance.logger = None
            cls._instance.setup_logger()
        return cls._instance

    def setup_logger(self):
        if self.logger is None:
            self.logger = logging.getLogger("logger")
            self.logger.setLevel(logging.DEBUG)

            fmt_datefmt = "%Y-%m-%d %H:%M:%S"

            # 1) Console INFO handler (stdout)
            info_handler = StatusBarAwareStreamHandler(sys.stdout)
            info_handler.setLevel(logging.INFO)
            info_handler.setFormatter(
                logging.Formatter("[*] %(asctime)s - %(message)s", fmt_datefmt)
            )
            info_handler.addFilter(MaxLevelFilter(logging.INFO))
            self.logger.addHandler(info_handler)

            # 2) Console WARNING & ERROR handler (stderr)
            error_handler = StatusBarAwareStreamHandler(sys.stderr)
            error_handler.setLevel(logging.WARNING)
            error_handler.setFormatter(
                logging.Formatter("[!] %(asctime)s - %(message)s", fmt_datefmt)
            )
            self.logger.addHandler(error_handler)

            # 3) File handler — DEBUG level, includes full stack traces
            #    Creates a dedicated log file per run session and keeps at most 10 log files
            import os
            from datetime import datetime
            from pathlib import Path

            script_dir = Path(__file__).resolve().parents[2]
            log_dir = script_dir / "output" / "logs"

            env_log_file = os.environ.get("TIKTOK_RECORDER_LOG_FILE")
            if not env_log_file:
                timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                log_filename = f"tiktok-recorder-{timestamp}.log"
                os.environ["TIKTOK_RECORDER_LOG_FILE"] = log_filename
            else:
                log_filename = env_log_file

            try:
                log_dir.mkdir(parents=True, exist_ok=True)
                log_file = log_dir / log_filename
                self.cleanup_old_logs(log_dir, max_files=10, current_file=log_file)
            except OSError:
                log_file = Path(log_filename)

            file_handler = RotatingFileHandler(
                str(log_file),
                maxBytes=10 * 1024 * 1024,
                backupCount=0,
                encoding="utf-8",
            )
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(
                logging.Formatter(
                    "%(asctime)s [%(levelname)s] %(message)s", fmt_datefmt
                )
            )
            self.logger.addHandler(file_handler)

    @staticmethod
    def cleanup_old_logs(log_dir, max_files=10, current_file=None):
        """Keep at most max_files log files in log_dir, deleting the oldest."""
        try:
            if not log_dir or not log_dir.exists():
                return
            log_files = sorted(
                [
                    f
                    for f in log_dir.glob("tiktok-recorder*.log")
                    if f.is_file()
                    and (not current_file or f.resolve() != current_file.resolve())
                ],
                key=lambda p: p.stat().st_mtime,
            )
            # Allow max_files - 1 existing files if a new file is being created
            allowed_existing = max(0, max_files - 1)
            if len(log_files) > allowed_existing:
                to_remove = log_files[: len(log_files) - allowed_existing]
                for f in to_remove:
                    try:
                        f.unlink(missing_ok=True)
                    except Exception:
                        pass
        except Exception:
            pass


logger = LoggerManager().logger
