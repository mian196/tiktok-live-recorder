import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from utils.logger_manager import logger  # noqa: E402


def test_logger_has_rotating_file_handler():
    file_handlers = [h for h in logger.handlers if isinstance(h, RotatingFileHandler)]
    assert len(file_handlers) >= 1
    handler = file_handlers[0]
    assert handler.maxBytes == 5 * 1024 * 1024
    assert handler.backupCount == 3
    assert handler.level == logging.DEBUG
    assert "output" in handler.baseFilename and "logs" in handler.baseFilename
