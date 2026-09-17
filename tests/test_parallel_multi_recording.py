import threading

import pytest

from core.tiktok_recorder import TikTokRecorder
from utils.enums import Mode
from utils.recorder_config import RecorderConfig


def test_parallel_multi_recording_records_all_live_users(monkeypatch):
    concurrent_active = []
    max_concurrent = 0
    lock = threading.Lock()

    recorder = TikTokRecorder(
        RecorderConfig(
            mode=Mode.AUTOMATIC,
            users=["streamer_a", "streamer_b", "streamer_c"],
            automatic_interval=0,
            retry_delay=0.01,
            recording_strategy="ffmpeg",
        )
    )

    class MultiLiveAPI:
        def get_user_info(self, username):
            return {"sec_uid": f"sec_{username}", "user_id": f"id_{username}"}

        def get_room_id_from_user(self, username):
            return f"room_{username}"

        def is_room_alive(self, room_id):
            return True

        def reset_session(self):
            pass

    recorder.tiktok = MultiLiveAPI()

    gate = threading.Event()

    def mock_start_recording(user, room_id, stop_event=None):
        nonlocal max_concurrent
        with lock:
            concurrent_active.append(user)
            if len(concurrent_active) > max_concurrent:
                max_concurrent = len(concurrent_active)
        # Hold thread active until gate is opened or timeout
        gate.wait(timeout=1.0)
        with lock:
            if user in concurrent_active:
                concurrent_active.remove(user)

    monkeypatch.setattr(recorder, "start_recording", mock_start_recording)

    loop_count = 0

    def mock_sleep(seconds):
        nonlocal loop_count
        loop_count += 1
        if max_concurrent >= 2:
            gate.set()
        if loop_count >= 5:
            gate.set()
            raise StopIteration("Done polling cycles")

    monkeypatch.setattr("time.sleep", mock_sleep)

    try:
        recorder.automatic_mode_multi()
    except StopIteration:
        pass
    finally:
        gate.set()

    # Confirm that more than 1 user was recording concurrently!
    assert max_concurrent >= 2


def test_parallel_multi_recording_graceful_shutdown(monkeypatch):
    recorder = TikTokRecorder(
        RecorderConfig(
            mode=Mode.AUTOMATIC,
            users=["streamer_x", "streamer_y"],
            automatic_interval=0,
            retry_delay=0.01,
        )
    )

    class FakeAPI:
        def get_user_info(self, username):
            return {"sec_uid": f"sec_{username}", "user_id": f"id_{username}"}

        def get_room_id_from_user(self, username):
            return f"room_{username}"

        def is_room_alive(self, room_id):
            return True

        def reset_session(self):
            pass

    recorder.tiktok = FakeAPI()

    stopped_users = []

    def mock_start_recording(user, room_id, stop_event=None):
        if stop_event:
            # Wait until signaled to stop
            stop_event.wait(timeout=2.0)
            stopped_users.append(user)

    monkeypatch.setattr(recorder, "start_recording", mock_start_recording)

    call_count = 0

    def mock_sleep(seconds):
        nonlocal call_count
        call_count += 1
        if call_count >= 3:
            raise KeyboardInterrupt("Simulated Ctrl+C")

    monkeypatch.setattr("time.sleep", mock_sleep)

    with pytest.raises(KeyboardInterrupt):
        recorder.automatic_mode_multi()

    # Confirm all workers were signaled and joined gracefully
    assert "streamer_x" in stopped_users
    assert "streamer_y" in stopped_users
