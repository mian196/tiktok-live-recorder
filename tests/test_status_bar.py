import io
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from utils.status_bar import (  # noqa: E402
    RecordingStatusBar,
    _format_duration,
    _format_size,
    _format_speed,
)


def test_format_duration():
    assert _format_duration(45) == "00:45"
    assert _format_duration(125) == "02:05"
    assert _format_duration(3665) == "01:01:05"


def test_format_size():
    assert _format_size(500) == "500 B"
    assert _format_size(2048) == "2 KB"
    assert _format_size(15 * 1024 * 1024) == "15.0 MB"
    assert _format_size(2 * 1024 * 1024 * 1024) == "2.00 GB"


def test_format_speed():
    assert _format_speed(500) == "500 B/s"
    assert _format_speed(150 * 1024) == "150 KB/s"
    assert _format_speed(3.5 * 1024 * 1024) == "3.5 MB/s"


def test_status_bar_renders_formatted_line():
    fake_stdout = io.StringIO()
    fake_stdout.isatty = lambda: True

    bar = RecordingStatusBar("streamer_test", part=1, update_interval=0.0)

    with patch("sys.stdout", fake_stdout):
        bar.update(10 * 1024 * 1024, part=1)

    output = fake_stdout.getvalue()
    assert "@streamer_test" in output
    assert "REC" in output
    assert "10.0 MB" in output


def test_status_bar_clear_and_finish():
    fake_stdout = io.StringIO()
    fake_stdout.isatty = lambda: True

    bar = RecordingStatusBar("streamer_test", part=1, update_interval=0.0)

    with patch("sys.stdout", fake_stdout):
        bar.start()
        bar.finish()

    output = fake_stdout.getvalue()
    assert "\033[2K" in output


def test_multiple_status_bars_render_each_user_on_separate_lines():
    fake_stdout = io.StringIO()
    fake_stdout.isatty = lambda: True

    bar1 = RecordingStatusBar("user_one", part=1, update_interval=0.0)
    bar2 = RecordingStatusBar("user_two", part=1, update_interval=0.0)

    with patch("sys.stdout", fake_stdout):
        bar1.start()
        bar2.start()
        bar1.update(5 * 1024 * 1024, part=1)
        bar2.update(12 * 1024 * 1024, part=1)

        output = fake_stdout.getvalue()
        assert "@user_one" in output
        assert "@user_two" in output
        assert "5.0 MB" in output
        assert "12.0 MB" in output

        bar1.finish()
        bar2.finish()
