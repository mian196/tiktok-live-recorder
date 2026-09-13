import json
import sys
from pathlib import Path
from unittest.mock import MagicMock


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.tiktok_recorder import TikTokRecorder  # noqa: E402
from utils.enums import Mode  # noqa: E402
from utils.recorder_config import RecorderConfig  # noqa: E402
from utils.user_identity import TrackedUser, parse_tracked_users  # noqa: E402
from utils.utils import update_tracked_users_in_config  # noqa: E402


def test_parse_tracked_users_formats():
    # Comma-separated string
    users1 = parse_tracked_users("@user1, user2")
    assert len(users1) == 2
    assert users1[0].username == "user1"
    assert users1[1].username == "user2"

    # List of strings
    users2 = parse_tracked_users(["@alpha", "beta"])
    assert len(users2) == 2
    assert users2[0].username == "alpha"
    assert users2[1].username == "beta"

    # List of dicts
    users3 = parse_tracked_users(
        [
            {"username": "streamer1", "sec_uid": "SEC_123", "user_id": "999"},
            {"user": "streamer2", "secUid": "SEC_456"},
        ]
    )
    assert len(users3) == 2
    assert users3[0].username == "streamer1"
    assert users3[0].sec_uid == "SEC_123"
    assert users3[0].user_id == "999"
    assert users3[1].username == "streamer2"
    assert users3[1].sec_uid == "SEC_456"

    # Mixed list
    users4 = parse_tracked_users(
        ["simple_user", {"username": "rich_user", "sec_uid": "SEC_789"}]
    )
    assert len(users4) == 2
    assert users4[0].username == "simple_user"
    assert users4[0].sec_uid is None
    assert users4[1].username == "rich_user"
    assert users4[1].sec_uid == "SEC_789"


def test_update_tracked_users_in_config(tmp_path, monkeypatch):
    config_file = tmp_path / "config.json"
    initial_config = {
        "mode": "automatic",
        "user": ["user1", "user2"],
        "automatic_interval": 5,
    }
    config_file.write_text(json.dumps(initial_config), encoding="utf-8")

    monkeypatch.setattr("utils.utils._get_config_path", lambda fn: str(config_file))

    tracked = [
        TrackedUser(username="user1", sec_uid="SEC_AAA", user_id="111"),
        TrackedUser(username="user2", sec_uid="SEC_BBB", user_id="222"),
    ]

    success = update_tracked_users_in_config(tracked)
    assert success is True

    saved = json.loads(config_file.read_text(encoding="utf-8"))
    assert saved["mode"] == "automatic"
    assert len(saved["user"]) == 2
    assert saved["user"][0] == {
        "username": "user1",
        "sec_uid": "SEC_AAA",
        "user_id": "111",
    }
    assert saved["user"][1] == {
        "username": "user2",
        "sec_uid": "SEC_BBB",
        "user_id": "222",
    }


def test_auto_resolve_missing_sec_uid(tmp_path, monkeypatch):
    config_file = tmp_path / "config.json"
    config_file.write_text(
        json.dumps({"mode": "automatic", "user": "creator"}), encoding="utf-8"
    )
    monkeypatch.setattr("utils.utils._get_config_path", lambda fn: str(config_file))

    recorder = TikTokRecorder(
        RecorderConfig(
            mode=Mode.AUTOMATIC,
            user="creator",
            tracked_users=[TrackedUser(username="creator")],
            output=str(tmp_path),
        )
    )

    fake_api = MagicMock()
    fake_api.get_user_info.return_value = {
        "username": "creator",
        "sec_uid": "MS4wLjAB_PERMANENT_ID",
        "user_id": "777888999",
    }
    fake_api.is_country_blacklisted.return_value = False
    recorder.tiktok = fake_api

    recorder._setup()

    assert recorder.tracked_users[0].sec_uid == "MS4wLjAB_PERMANENT_ID"
    assert recorder.tracked_users[0].user_id == "777888999"

    # Verify saved to config.json
    saved = json.loads(config_file.read_text(encoding="utf-8"))
    assert saved["user"]["sec_uid"] == "MS4wLjAB_PERMANENT_ID"
    assert saved["user"]["user_id"] == "777888999"


def test_handle_change_recovery_via_sec_uid(tmp_path, monkeypatch):
    config_file = tmp_path / "config.json"
    config_file.write_text(
        json.dumps(
            {
                "mode": "automatic",
                "user": {
                    "username": "old_handle",
                    "sec_uid": "MS4wLjAB_SAME_ID",
                    "user_id": "123",
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("utils.utils._get_config_path", lambda fn: str(config_file))

    user_obj = TrackedUser(
        username="old_handle", sec_uid="MS4wLjAB_SAME_ID", user_id="123"
    )
    recorder = TikTokRecorder(
        RecorderConfig(
            mode=Mode.AUTOMATIC,
            user="old_handle",
            tracked_users=[user_obj],
            output=str(tmp_path),
        )
    )

    fake_api = MagicMock()
    # Old handle lookup returns None (user changed handle)
    def fake_get_room(user):
        if user == "new_handle":
            return "room_99999"
        return None

    fake_api.get_room_id_from_user.side_effect = fake_get_room
    # Querying sec_uid returns new handle
    fake_api.get_user_by_sec_uid.return_value = {
        "username": "new_handle",
        "sec_uid": "MS4wLjAB_SAME_ID",
        "user_id": "123",
    }
    recorder.tiktok = fake_api

    recovered_user, room_id = recorder._check_and_recover_user_handle(user_obj)

    assert recovered_user.username == "new_handle"
    assert room_id == "room_99999"

    # Check updated in config.json
    saved = json.loads(config_file.read_text(encoding="utf-8"))
    assert saved["user"]["username"] == "new_handle"
    assert saved["user"]["sec_uid"] == "MS4wLjAB_SAME_ID"


def test_id_repair_when_sec_uid_is_outdated(tmp_path, monkeypatch):
    config_file = tmp_path / "config.json"
    config_file.write_text(
        json.dumps(
            {
                "mode": "automatic",
                "user": {
                    "username": "creator",
                    "sec_uid": "MS4wLjAB_CORRUPTED_ID",
                    "user_id": "000",
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("utils.utils._get_config_path", lambda fn: str(config_file))

    user_obj = TrackedUser(
        username="creator", sec_uid="MS4wLjAB_CORRUPTED_ID", user_id="000"
    )
    recorder = TikTokRecorder(
        RecorderConfig(
            mode=Mode.AUTOMATIC,
            user="creator",
            tracked_users=[user_obj],
            output=str(tmp_path),
        )
    )

    fake_api = MagicMock()
    # Room lookup fails
    fake_api.get_room_id_from_user.return_value = None
    # Sec_uid lookup fails/None
    fake_api.get_user_by_sec_uid.return_value = None
    # Profile by username returns fresh valid sec_uid
    fake_api.get_user_info.return_value = {
        "username": "creator",
        "sec_uid": "MS4wLjAB_CORRECT_FRESH_ID",
        "user_id": "555666",
    }
    recorder.tiktok = fake_api

    recovered_user, _ = recorder._check_and_recover_user_handle(user_obj)

    assert recovered_user.sec_uid == "MS4wLjAB_CORRECT_FRESH_ID"
    assert recovered_user.user_id == "555666"

    # Check config was repaired
    saved = json.loads(config_file.read_text(encoding="utf-8"))
    assert saved["user"]["sec_uid"] == "MS4wLjAB_CORRECT_FRESH_ID"
