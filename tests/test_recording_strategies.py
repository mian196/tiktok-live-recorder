from pathlib import Path
import threading
from unittest.mock import MagicMock, patch


from core.recording_strategies import (
    FFmpegStrategy,
    RequestsStrategy,
    YtDlpStrategy,
    get_recording_strategy,
)
from utils.enums import Mode
from utils.recorder_config import RecorderConfig


class FakeRecorder:
    def __init__(self, **kwargs):
        self.config = RecorderConfig(mode=Mode.MANUAL, **kwargs)
        self.ffmpeg_path = kwargs.get("ffmpeg_path", "ffmpeg")
        self.yt_dlp_path = kwargs.get("yt_dlp_path", "yt-dlp")
        self.duration = kwargs.get("duration", None)
        self.bitrate = kwargs.get("bitrate", None)
        self.keep_flv = kwargs.get("keep_flv", False)
        self.move_to_recycle_bin = kwargs.get("move_to_recycle_bin", True)
        self.retry_delay = kwargs.get("retry_delay", 5)
        self._proxy = kwargs.get("proxy", None)
        self.notify = MagicMock()
        self.tiktok = MagicMock()


def test_get_recording_strategy_factory():
    rec = FakeRecorder()
    assert isinstance(get_recording_strategy("ffmpeg", rec), FFmpegStrategy)
    assert isinstance(get_recording_strategy("FFMPEG", rec), FFmpegStrategy)
    assert isinstance(get_recording_strategy("requests", rec), RequestsStrategy)
    assert isinstance(get_recording_strategy("flv", rec), RequestsStrategy)
    assert isinstance(get_recording_strategy("FLV", rec), RequestsStrategy)
    assert isinstance(get_recording_strategy("yt-dlp", rec), YtDlpStrategy)
    assert isinstance(get_recording_strategy("unknown", rec), RequestsStrategy)
    assert isinstance(get_recording_strategy(None, rec), RequestsStrategy)


def test_ffmpeg_strategy_command_execution(tmp_path):
    out_file = tmp_path / "test.mp4"
    rec = FakeRecorder(duration=10, bitrate="2M", proxy="http://127.0.0.1:8080")
    strategy = FFmpegStrategy(rec)

    captured_cmds = []

    class FakeProc:
        def __init__(self, cmd, **kwargs):
            captured_cmds.append(cmd)
            self.stdin = MagicMock()
            self.stdout = MagicMock()
            self.stderr = MagicMock()
            self.returncode = 0
            # Create the output file to simulate successful stream capture
            out_file.write_bytes(b"F" * 8192)

        def poll(self):
            return 0

        def wait(self, timeout=None):
            return 0

        def communicate(self, *args, **kwargs):
            return b"", b""

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    with patch("subprocess.Popen", side_effect=FakeProc):
        success, path, total_bytes = strategy.record(
            user="streamer1",
            room_id="123",
            live_urls=["https://cdn/live.m3u8"],
            final_output=str(out_file),
        )

    assert success is True
    assert total_bytes == 8192
    assert len(captured_cmds) == 2

    # Verify recording command with fragmented MP4 flags
    rec_cmd = captured_cmds[0]
    assert rec_cmd[0] == "ffmpeg"
    assert "-reconnect" in rec_cmd
    assert "-http_proxy" in rec_cmd
    assert "http://127.0.0.1:8080" in rec_cmd
    assert "-b:v" in rec_cmd
    assert "2M" in rec_cmd
    assert "-t" in rec_cmd
    assert "10" in rec_cmd
    assert "-c" in rec_cmd
    assert "copy" in rec_cmd
    assert "-movflags" in rec_cmd
    assert "+empty_moov+frag_keyframe+default_base_moof" in rec_cmd
    assert str(out_file) in rec_cmd
    assert not Path(f"{out_file}.in_progress").exists()

    # Verify sanitization command with faststart
    san_cmd = captured_cmds[1]
    assert san_cmd[0] == "ffmpeg"
    assert "-err_detect" in san_cmd
    assert "ignore_err" in san_cmd
    assert "-movflags" in san_cmd
    assert "+faststart" in san_cmd


def test_ffmpeg_strategy_graceful_stop_via_stdin(tmp_path):
    out_file = tmp_path / "test.mp4"
    rec = FakeRecorder()
    strategy = FFmpegStrategy(rec)
    stop_event = threading.Event()

    fake_stdin = MagicMock()

    class HangingProc:
        def __init__(self, cmd, **kwargs):
            self.stdin = fake_stdin
            self.returncode = 0
            self._polls = 0
            out_file.write_bytes(b"DATA" * 2048)

        def poll(self):
            self._polls += 1
            if self._polls == 2:
                stop_event.set()
            if self._polls > 2:
                return 0
            return None

        def wait(self, timeout=None):
            return 0

        def communicate(self, *args, **kwargs):
            return b"", b""

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    with patch("subprocess.Popen", side_effect=HangingProc):
        success, path, total_bytes = strategy.record(
            user="streamer1",
            room_id="123",
            live_urls=["https://cdn/live.m3u8"],
            final_output=str(out_file),
            stop_event=stop_event,
        )

    assert success is True
    assert fake_stdin.write.called
    assert fake_stdin.write.call_args[0][0] == b"q\n"


def test_ytdlp_strategy_command_execution(tmp_path):
    out_file = tmp_path / "test_yt.mp4"
    rec = FakeRecorder(yt_dlp_path="custom-yt-dlp", proxy="http://proxy:8080")
    strategy = YtDlpStrategy(rec)

    captured_cmds = []

    class FakeYtProc:
        def __init__(self, cmd, **kwargs):
            captured_cmds.append(cmd)
            self.returncode = 0
            out_file.write_bytes(b"YTDLP" * 2000)

        def poll(self):
            return 0

        def wait(self, timeout=None):
            return 0

        def terminate(self):
            pass

    with patch("subprocess.Popen", side_effect=FakeYtProc):
        success, path, total_bytes = strategy.record(
            user="creator",
            room_id="777",
            live_urls=["https://cdn/live.m3u8"],
            final_output=str(out_file),
        )

    assert success is True
    assert total_bytes == 10000
    assert len(captured_cmds) == 1
    cmd = captured_cmds[0]
    assert cmd[0] == "custom-yt-dlp"
    assert "--no-part" in cmd
    assert "--proxy" in cmd
    assert "http://proxy:8080" in cmd
    assert str(out_file) in cmd
    assert "https://cdn/live.m3u8" in cmd
