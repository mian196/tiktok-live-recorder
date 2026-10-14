from unittest.mock import MagicMock, patch


from core.recording_strategies import (
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
    assert isinstance(get_recording_strategy("ffmpeg", rec), RequestsStrategy)
    assert isinstance(get_recording_strategy("FFMPEG", rec), RequestsStrategy)
    assert isinstance(get_recording_strategy("requests", rec), RequestsStrategy)
    assert isinstance(get_recording_strategy("flv", rec), RequestsStrategy)
    assert isinstance(get_recording_strategy("FLV", rec), RequestsStrategy)
    assert isinstance(get_recording_strategy("yt-dlp", rec), YtDlpStrategy)
    assert isinstance(get_recording_strategy("unknown", rec), RequestsStrategy)
    assert isinstance(get_recording_strategy(None, rec), RequestsStrategy)


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

        def __enter__(self):
            return self

        def __exit__(self, *args):
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
    assert len(captured_cmds) == 2
    cmd = captured_cmds[0]
    assert cmd[0] == "custom-yt-dlp"
    assert "--no-part" in cmd
    assert "--proxy" in cmd
    assert "http://proxy:8080" in cmd
    assert str(out_file) in cmd
    assert "https://cdn/live.m3u8" in cmd

    # Verify post-download sanitization
    san_cmd = captured_cmds[1]
    assert san_cmd[0] == "ffmpeg"
    assert "-movflags" in san_cmd
    assert "+faststart" in san_cmd
