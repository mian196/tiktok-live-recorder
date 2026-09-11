import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.tiktok_recorder import TikTokRecorder  # noqa: E402
from utils.enums import Mode  # noqa: E402
from utils.recorder_config import RecorderConfig  # noqa: E402


def test_conversion_lock_prevents_concurrent_conversions():
    recorder = TikTokRecorder(
        RecorderConfig(
            mode=Mode.MANUAL,
            user="test_user",
        )
    )

    class FastFakeAPI:
        def __init__(self):
            self.calls = {}

        def get_live_url_candidates(self, room_id, user=None):
            return ["http://fake.stream/live.flv"]

        def is_room_alive(self, room_id):
            count = self.calls.get(room_id, 0)
            self.calls[room_id] = count + 1
            return count < 1

        def download_live_stream(self, live_url):
            yield b"A" * 5000

    recorder.tiktok = FastFakeAPI()

    concurrent_runs = 0
    max_concurrent = 0
    run_lock = threading.Lock()

    def fake_convert(segments, output, bitrate, ffmpeg_path, keep_flv):
        nonlocal concurrent_runs, max_concurrent
        with run_lock:
            concurrent_runs += 1
            if concurrent_runs > max_concurrent:
                max_concurrent = concurrent_runs
        time.sleep(0.05)
        with run_lock:
            concurrent_runs -= 1
        return True

    with patch(
        "utils.video_management.VideoManagement.convert_segments_to_mp4",
        side_effect=fake_convert,
    ):
        t1 = threading.Thread(target=recorder.start_recording, args=("u1", "r1"))
        t2 = threading.Thread(target=recorder.start_recording, args=("u2", "r2"))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

    assert max_concurrent == 1
