import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from utils.logger_manager import LoggerManager, logger  # noqa: E402


def test_logger_has_rotating_file_handler():
    file_handlers = [h for h in logger.handlers if isinstance(h, RotatingFileHandler)]
    assert len(file_handlers) >= 1
    handler = file_handlers[0]
    assert handler.level == logging.DEBUG
    assert "output" in handler.baseFilename and "logs" in handler.baseFilename


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
