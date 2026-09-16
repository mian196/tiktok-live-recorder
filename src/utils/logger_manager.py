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
            info_handler = logging.StreamHandler(sys.stdout)
            info_handler.setLevel(logging.INFO)
            info_handler.setFormatter(
                logging.Formatter("[*] %(asctime)s - %(message)s", fmt_datefmt)
            )
            info_handler.addFilter(MaxLevelFilter(logging.INFO))
            self.logger.addHandler(info_handler)

            # 2) Console WARNING & ERROR handler (stderr)
            error_handler = logging.StreamHandler(sys.stderr)
            error_handler.setLevel(logging.WARNING)
            error_handler.setFormatter(
                logging.Formatter("[!] %(asctime)s - %(message)s", fmt_datefmt)
            )
            self.logger.addHandler(error_handler)

            # 3) File handler — DEBUG level, includes full stack traces
            #    Rotates at 5 MB, keeps 3 backups
            #    Stored in output/logs/
            from pathlib import Path

            script_dir = Path(__file__).resolve().parents[2]
            log_dir = script_dir / "output" / "logs"
            try:
                log_dir.mkdir(parents=True, exist_ok=True)
                log_file = log_dir / "tiktok-recorder.log"
            except OSError:
                log_file = Path("tiktok-recorder.log")

            file_handler = RotatingFileHandler(
                str(log_file),
                maxBytes=5 * 1024 * 1024,
                backupCount=3,
                encoding="utf-8",
            )
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(
                logging.Formatter(
                    "%(asctime)s [%(levelname)s] %(message)s", fmt_datefmt
                )
            )
            self.logger.addHandler(file_handler)


logger = LoggerManager().logger
