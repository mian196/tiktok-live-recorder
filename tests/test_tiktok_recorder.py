import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.tiktok_recorder import TikTokRecorder  # noqa: E402
from utils.custom_exceptions import TikTokRecorderError  # noqa: E402
from utils.enums import Mode  # noqa: E402
from utils.recorder_config import RecorderConfig  # noqa: E402


class FakeTikTokAPI:
    def __init__(self, blacklisted=True):
        self.blacklisted = blacklisted
        self.calls = []

    def is_country_blacklisted(self):
        self.calls.append("is_country_blacklisted")
        return self.blacklisted

    def get_room_id_from_user(self, user):
        self.calls.append(f"get_room_id_from_user:{user}")
        return "1234567890"

    def get_user_from_room_id(self, room_id):
        self.calls.append(f"get_user_from_room_id:{room_id}")
        return "creator"

    def get_sec_uid(self):
        self.calls.append("get_sec_uid")
        return "sec_uid"

    def is_room_alive(self, room_id):
        self.calls.append(f"is_room_alive:{room_id}")
        return True


def test_setup_resolves_room_id_before_country_check_for_manual_user():
    recorder = TikTokRecorder(
        RecorderConfig(mode=Mode.MANUAL, user="creator", cookies={})
    )
    fake_api = FakeTikTokAPI(blacklisted=True)
    recorder.tiktok = fake_api

    recorder._setup()

    assert recorder.room_id == "1234567890"
    assert fake_api.calls == [
        "get_room_id_from_user:creator",
        "is_country_blacklisted",
        "is_room_alive:1234567890",
    ]


def test_setup_keeps_followers_country_check_before_sec_uid():
    recorder = TikTokRecorder(RecorderConfig(mode=Mode.FOLLOWERS, cookies={}))
    fake_api = FakeTikTokAPI(blacklisted=True)
    recorder.tiktok = fake_api

    with pytest.raises(TikTokRecorderError, match="Captcha required"):
        recorder._setup()

    assert fake_api.calls == ["is_country_blacklisted"]


def test_setup_keeps_automatic_mode_blocked_after_room_resolution():
    recorder = TikTokRecorder(
        RecorderConfig(mode=Mode.AUTOMATIC, user="creator", cookies={})
    )
    fake_api = FakeTikTokAPI(blacklisted=True)
    recorder.tiktok = fake_api

    with pytest.raises(TikTokRecorderError, match="Automatic mode is available"):
        recorder._setup()

    assert recorder.room_id == "1234567890"
    assert fake_api.calls == [
        "get_room_id_from_user:creator",
        "is_country_blacklisted",
    ]


def test_setup_keeps_manual_room_id_allowed_when_country_check_is_blocked():
    recorder = TikTokRecorder(
        RecorderConfig(mode=Mode.MANUAL, room_id="1234567890", cookies={})
    )
    fake_api = FakeTikTokAPI(blacklisted=True)
    recorder.tiktok = fake_api

    recorder._setup()

    assert recorder.room_id == "1234567890"
    assert fake_api.calls == [
        "get_user_from_room_id:1234567890",
        "is_country_blacklisted",
        "is_room_alive:1234567890",
    ]


def test_start_recording_handles_reconnection_and_passes_segments(tmp_path):
    from unittest.mock import patch
    import requests

    recorder = TikTokRecorder(
        RecorderConfig(mode=Mode.MANUAL, user="test_user", output=str(tmp_path))
    )

    class StreamingFakeAPI:
        def __init__(self):
            self.call_count = 0
            self.alive_checks = 0

        def get_live_url_candidates(self, room_id, user=None):
            return ["http://fake.stream/live.flv"]

        def is_room_alive(self, room_id):
            self.alive_checks += 1
            # Alive during stream 1 and stream 2, then offline to finish recording
            return self.alive_checks <= 3

        def download_live_stream(self, live_url):
            self.call_count += 1
            if self.call_count == 1:
                # Yield 5KB of data then raise network hiccup
                yield b"X" * 5120
                raise requests.exceptions.ChunkedEncodingError("Connection dropped")
            elif self.call_count == 2:
                # Yield 5KB on reconnection then end stream
                yield b"Y" * 5120
            else:
                return

    fake_api = StreamingFakeAPI()
    recorder.tiktok = fake_api

    with patch(
        "utils.video_management.VideoManagement.convert_segments_to_mp4"
    ) as mock_convert:
        mock_convert.return_value = True
        recorder.start_recording("test_user", "1234567890")

        assert mock_convert.called
        (
            segments_arg,
            output_arg,
            bitrate_arg,
            ffmpeg_arg,
            keep_flv_arg,
        ) = mock_convert.call_args[0]
        # Should have captured 2 separate segments
        assert len(segments_arg) == 2
        assert output_arg.endswith(".mp4")
        assert "test_user-" in output_arg
        assert keep_flv_arg is False


def test_automatic_mode_multi_checks_all_users():
    from unittest.mock import patch

    recorder = TikTokRecorder(
        RecorderConfig(
            mode=Mode.AUTOMATIC,
            users=["user1", "user2"],
            automatic_interval=1,
            cookies={},
        )
    )

    checked_users = []

    class FakeMultiAPI:
        def is_country_blacklisted(self):
            return False

        def get_room_id_from_user(self, u):
            checked_users.append(u)
            return "room_" + u

        def is_room_alive(self, r):
            return False

    recorder.tiktok = FakeMultiAPI()
    recorder._setup()

    # Run one cycle of automatic_mode_multi and break
    with patch("time.sleep") as mock_sleep:
        # Stop after sleeping for the full interval
        def side_effect(seconds):
            if seconds == 60:  # 1 min interval
                raise StopIteration

        mock_sleep.side_effect = side_effect

        with pytest.raises(StopIteration):
            recorder.automatic_mode_multi()

    assert checked_users == ["user1", "user2"]


def test_start_recording_survives_vpn_toggle_and_resets_session(tmp_path):
    from unittest.mock import patch
    import requests

    recorder = TikTokRecorder(
        RecorderConfig(
            mode=Mode.MANUAL, user="vpn_user", output=str(tmp_path), retry_delay=0.01
        )
    )

    class VPNToggleFakeAPI:
        def __init__(self):
            self.session_resets = 0
            self.status_checks = 0
            self.stream_calls = 0

        def reset_session(self):
            self.session_resets += 1

        def get_live_url_candidates(self, room_id, user=None):
            return ["http://cdn.tiktok/live.flv"]

        def get_live_urls(self, room_id, user=None):
            return ["http://cdn.tiktok/live_refreshed.flv"]

        def verify_room_status(self, room_id):
            self.status_checks += 1
            if self.status_checks == 1:
                # Initial check: online
                return True, True
            elif self.status_checks == 2:
                # During VPN switch: unconfirmed / network outage
                return False, False
            elif self.status_checks == 3:
                # Reconnected to internet: online again
                return True, True
            else:
                # Finally stream finishes naturally
                return False, True

        def download_live_stream(self, live_url):
            self.stream_calls += 1
            if self.stream_calls == 1:
                # Send data then drop connection (VPN toggled)
                yield b"V" * 5000
                raise requests.exceptions.ConnectionError("VPN switched off")
            elif self.stream_calls == 2:
                # Resumed stream chunk
                yield b"W" * 5000
            else:
                return

    fake_api = VPNToggleFakeAPI()
    recorder.tiktok = fake_api

    with patch(
        "utils.video_management.VideoManagement.convert_segments_to_mp4"
    ) as mock_convert:
        mock_convert.return_value = True
        recorder.start_recording("vpn_user", "room_999")

        assert mock_convert.called
        segments_arg = mock_convert.call_args[0][0]
        assert len(segments_arg) == 2
        assert fake_api.session_resets >= 1
