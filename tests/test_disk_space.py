import collections
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.tiktok_recorder import TikTokRecorder  # noqa: E402
from utils.enums import Mode  # noqa: E402
from utils.recorder_config import RecorderConfig  # noqa: E402

Usage = collections.namedtuple("Usage", ["total", "used", "free"])


def test_check_disk_space_returns_false_and_notifies_when_below_threshold():
    recorder = TikTokRecorder(
        RecorderConfig(
            mode=Mode.MANUAL,
            user="streamer1",
            disk_space_alert_gb=10,
        )
    )
    recorder.notify = MagicMock()

    # 3 GB free (below 10 GB threshold)
    mock_usage = Usage(total=100 * (1024**3), used=97 * (1024**3), free=3 * (1024**3))

    with patch("shutil.disk_usage", return_value=mock_usage):
        has_space = recorder._check_disk_space("streamer1")

    assert has_space is False
    recorder.notify.notify.assert_called_once_with(
        "low_disk_space",
        user="streamer1",
        free_gb=3.0,
        threshold=10,
    )


def test_check_disk_space_returns_true_when_above_threshold():
    recorder = TikTokRecorder(
        RecorderConfig(
            mode=Mode.MANUAL,
            user="streamer1",
            disk_space_alert_gb=5,
        )
    )
    recorder.notify = MagicMock()

    # 20 GB free (above 5 GB threshold)
    mock_usage = Usage(total=100 * (1024**3), used=80 * (1024**3), free=20 * (1024**3))

    with patch("shutil.disk_usage", return_value=mock_usage):
        has_space = recorder._check_disk_space("streamer1")

    assert has_space is True
    recorder.notify.notify.assert_not_called()


def test_check_disk_space_disabled_when_zero():
    recorder = TikTokRecorder(
        RecorderConfig(
            mode=Mode.MANUAL,
            user="streamer1",
            disk_space_alert_gb=0,
        )
    )
    recorder.notify = MagicMock()

    with patch("shutil.disk_usage") as mock_usage:
        has_space = recorder._check_disk_space("streamer1")
        mock_usage.assert_not_called()

    assert has_space is True
    recorder.notify.notify.assert_not_called()
