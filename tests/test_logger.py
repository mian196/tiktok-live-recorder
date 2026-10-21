import logging
import sys
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from utils.logger_manager import (  # noqa: E402
    LoggerManager,
    MidnightRotatingFileHandler,
    logger,
)


def test_logger_has_rotating_file_handler():
    file_handlers = [h for h in logger.handlers if isinstance(h, RotatingFileHandler)]
    assert len(file_handlers) >= 1
    handler = file_handlers[0]
    assert handler.level == logging.DEBUG
    assert "output" in handler.baseFilename and "logs" in handler.baseFilename
    assert isinstance(handler, TimedRotatingFileHandler)
    assert handler.when == "MIDNIGHT"


def test_cleanup_old_logs_max_10_files(tmp_path):
    log_dir = tmp_path / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    # Create 15 fake log files with varying mtimes
    files = []
    for i in range(15):
        f = log_dir / f"tiktok-recorder-2026-09-17-0{i:02d}.log"
        f.write_text(f"log content {i}")
        files.append(f)

    # Call cleanup keeping max 10
    LoggerManager.cleanup_old_logs(log_dir, max_files=10)

    remaining = sorted(list(log_dir.glob("tiktok-recorder*.log")))
    assert len(remaining) == 9  # 9 existing kept so 1 new file makes 10 total


def test_midnight_rotating_file_handler_rollover(tmp_path):
    log_dir = tmp_path / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    initial_log = log_dir / "tiktok-recorder-2026-10-21.log"
    handler = MidnightRotatingFileHandler(
        str(initial_log), log_dir=log_dir, max_files=5
    )

    test_logger = logging.getLogger("test_midnight")
    test_logger.setLevel(logging.INFO)
    test_logger.addHandler(handler)

    test_logger.info("day 1 entry")

    # Simulate midnight passing to 2026-10-22
    with patch(
        "utils.timezone_manager.format_configured_time", return_value="2026-10-22"
    ):
        handler.doRollover()
        test_logger.info("day 2 entry")

    day1_file = log_dir / "tiktok-recorder-2026-10-21.log"
    day2_file = log_dir / "tiktok-recorder-2026-10-22.log"

    assert day1_file.exists()
    assert day2_file.exists()
    assert "day 1 entry" in day1_file.read_text(encoding="utf-8")
    assert "day 2 entry" in day2_file.read_text(encoding="utf-8")

    handler.close()
