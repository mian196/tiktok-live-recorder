import logging
import os
import sys
import time
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from pathlib import Path


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
                try:
                    from utils.status_bar import RecordingStatusBar

                    RecordingStatusBar.clear_display_for_log()
                except Exception:
                    pass
                stream.write(f"{msg}{self.terminator}")
                stream.flush()
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


class MidnightRotatingFileHandler(TimedRotatingFileHandler, RotatingFileHandler):
    """
    Rotating file handler that rotates daily at midnight to create a new file
    named tiktok-recorder-YYYY-MM-DD.log, keeping at most max_files historical logs.
    """

    def __init__(
        self,
        filename,
        log_dir=None,
        max_files=10,
        encoding="utf-8",
        delay=False,
        errors=None,
    ):
        TimedRotatingFileHandler.__init__(
            self,
            filename=str(filename),
            when="midnight",
            interval=1,
            backupCount=max_files,
            encoding=encoding,
            delay=delay,
            errors=errors,
        )
        self.maxBytes = 0
        self.log_dir = Path(log_dir) if log_dir else Path(filename).parent
        self.max_files = max_files

    def doRollover(self):
        if self.stream:
            self.stream.close()
            self.stream = None
        from utils.timezone_manager import format_configured_time

        today_str = format_configured_time("%Y-%m-%d")
        new_file = self.log_dir / f"tiktok-recorder-{today_str}.log"
        self.baseFilename = os.path.abspath(str(new_file))
        if not self.delay:
            self.stream = self._open()
        currentTime = int(time.time())
        newRolloverAt = self.computeRollover(currentTime)
        while newRolloverAt <= currentTime:
            newRolloverAt = newRolloverAt + self.interval
        self.rolloverAt = newRolloverAt
        LoggerManager.cleanup_old_logs(
            self.log_dir,
            max_files=self.max_files,
            current_file=Path(self.baseFilename),
        )


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
            from utils.timezone_manager import (
                get_logging_time_converter,
                format_configured_time,
            )

            time_conv = get_logging_time_converter()

            # 1) Console INFO handler (stdout)
            info_handler = StatusBarAwareStreamHandler(sys.stdout)
            info_handler.setLevel(logging.INFO)
            info_fmt = logging.Formatter("[*] %(asctime)s - %(message)s", fmt_datefmt)
            info_fmt.converter = time_conv
            info_handler.setFormatter(info_fmt)
            info_handler.addFilter(MaxLevelFilter(logging.INFO))
            self.logger.addHandler(info_handler)

            # 2) Console WARNING & ERROR handler (stderr)
            error_handler = StatusBarAwareStreamHandler(sys.stderr)
            error_handler.setLevel(logging.WARNING)
            err_fmt = logging.Formatter("[!] %(asctime)s - %(message)s", fmt_datefmt)
            err_fmt.converter = time_conv
            error_handler.setFormatter(err_fmt)
            self.logger.addHandler(error_handler)

            # 3) File handler — rotates daily at midnight, keeps at most 10 log files
            script_dir = Path(__file__).resolve().parents[2]
            log_dir = script_dir / "output" / "logs"

            env_log_file = os.environ.get("TIKTOK_RECORDER_LOG_FILE")
            if not env_log_file:
                timestamp = format_configured_time("%Y-%m-%d")
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

            file_handler = MidnightRotatingFileHandler(
                str(log_file),
                log_dir=log_dir,
                max_files=10,
                encoding="utf-8",
            )
            file_handler.setLevel(logging.DEBUG)
            file_fmt = logging.Formatter(
                "%(asctime)s [%(levelname)s] %(message)s", fmt_datefmt
            )
            file_fmt.converter = time_conv
            file_handler.setFormatter(file_fmt)
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
