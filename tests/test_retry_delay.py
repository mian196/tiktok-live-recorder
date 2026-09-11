import sys
from pathlib import Path
from unittest.mock import patch

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.tiktok_recorder import TikTokRecorder  # noqa: E402
from utils.enums import Mode  # noqa: E402
from utils.recorder_config import RecorderConfig  # noqa: E402


def test_retry_delay_used_on_reconnection(tmp_path):
    recorder = TikTokRecorder(
        RecorderConfig(
            mode=Mode.MANUAL,
            user="test_user",
            retry_delay=7,
            output=str(tmp_path),
        )
    )

    class StreamingFakeAPI:
        def __init__(self):
            self.calls = 0

        def get_live_url_candidates(self, room_id, user=None):
            return ["http://fake.stream/live.flv"]

        def is_room_alive(self, room_id):
            return self.calls <= 2

        def download_live_stream(self, live_url):
            self.calls += 1
            if self.calls == 1:
                yield b"A" * 5000
                raise requests.exceptions.ChunkedEncodingError("Drop")
            else:
                yield b"B" * 5000

    recorder.tiktok = StreamingFakeAPI()

    slept_durations = []

    with (
        patch(
            "utils.video_management.VideoManagement.convert_segments_to_mp4"
        ) as mock_convert,
        patch("time.sleep") as mock_sleep,
    ):
        mock_convert.return_value = True
        mock_sleep.side_effect = lambda s: slept_durations.append(s)

        recorder.start_recording("test_user", "12345")

    assert 7 in slept_durations
