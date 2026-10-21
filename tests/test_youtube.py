from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import httplib2
import pytest
from googleapiclient.errors import HttpError

from upload.youtube import (
    YouTube,
    get_next_pacific_midnight,
    is_quota_exceeded,
)
from utils.recorder_config import RecorderConfig
from utils.enums import Mode


@pytest.fixture(autouse=True)
def isolate_youtube_test_env(tmp_path, monkeypatch):
    """Ensure every test runs with an isolated queue and clear exhaustion state."""
    YouTube._exhausted_projects.clear()
    test_queue = tmp_path / "test_isolated_queue.json"
    orig_read = YouTube.__init__

    def wrapped_init(self, config_override=None):
        cfg = dict(config_override) if config_override else {}
        if "queue_file" not in cfg:
            cfg["queue_file"] = str(test_queue)
        orig_read(self, config_override=cfg)

    monkeypatch.setattr(YouTube, "__init__", wrapped_init)


def test_youtube_init_defaults():
    yt = YouTube()
    assert yt.privacy_status == "private"
    assert yt.category_id is None
    assert yt.made_for_kids is False
    assert "{username}" in yt.title_template or "{user}" in yt.title_template
    assert "tiktok" in yt.tags
    assert len(yt.projects) == 1


def test_youtube_init_custom_config():
    custom_cfg = {
        "projects": [
            {
                "name": "Project 1",
                "client_secrets_file": "custom_secrets_1.json",
                "credentials_storage_file": "custom_token_1.json",
            },
            {
                "name": "Project 2",
                "client_secrets_file": "custom_secrets_2.json",
                "credentials_storage_file": "custom_token_2.json",
            },
        ],
        "privacy_status": "unlisted",
        "title_template": "Live of {user}",
        "description_template": "Custom desc: {date}",
        "tags": ["stream", "backup"],
        "category_id": "20",
        "made_for_kids": True,
    }
    yt = YouTube(config_override=custom_cfg)
    assert yt.privacy_status == "unlisted"
    assert yt.category_id == "20"
    assert yt.made_for_kids is True
    assert yt.title_template == "Live of {user}"
    assert yt.tags == ["stream", "backup"]
    assert len(yt.projects) == 2
    assert yt.projects[0]["name"] == "Project 1"
    assert yt.projects[1]["name"] == "Project 2"


def test_format_metadata():
    yt = YouTube(
        config_override={
            "title_template": "Streamer: {user} | {date} | {unknown_key}",
            "description_template": "File: {filename}",
        }
    )
    p = Path("streamer1-2026-10-21.mp4")
    title, desc = yt._format_metadata("streamer1", p)
    assert "Streamer: streamer1" in title
    assert "{unknown_key}" in title  # SafeDict preserves unknown braces without crash
    assert "File: streamer1-2026-10-21" in desc


def test_format_metadata_title_truncation():
    yt = YouTube(config_override={"title_template": "A" * 150})
    title, _ = yt._format_metadata("user", Path("test.mp4"))
    assert len(title) == 100
    assert title.endswith("...")


def test_upload_file_not_found():
    yt = YouTube()
    assert yt.upload("non_existent_file.mp4") is False


def test_upload_empty_file(tmp_path):
    empty_file = tmp_path / "empty.mp4"
    empty_file.write_bytes(b"")
    yt = YouTube()
    assert yt.upload(str(empty_file)) is False


def test_upload_service_unavailable(tmp_path, monkeypatch):
    video = tmp_path / "test.mp4"
    video.write_bytes(b"dummy video content")

    yt = YouTube()
    monkeypatch.setattr(yt, "_get_authenticated_service_for_project", lambda p: None)
    assert yt.upload(str(video)) is False


def test_upload_success_and_purge(tmp_path, monkeypatch):
    video = tmp_path / "test_success.mp4"
    video.write_bytes(b"x" * 1024)

    mock_service = MagicMock()
    mock_insert_request = MagicMock()
    # Simulate chunk progress then final completion
    mock_chunk_status = MagicMock()
    mock_chunk_status.progress.return_value = 1.0
    mock_insert_request.next_chunk.side_effect = [
        (mock_chunk_status, None),
        (None, {"id": "yt_video_12345"}),
    ]
    mock_service.videos.return_value.insert.return_value = mock_insert_request

    yt = YouTube()
    monkeypatch.setattr(
        yt, "_get_authenticated_service_for_project", lambda p: mock_service
    )

    assert video.exists()
    success = yt.upload(str(video), user="alice", purge_after=True)

    assert success is True
    assert not video.exists()  # Purged


def test_upload_failure_does_not_purge(tmp_path, monkeypatch):
    video = tmp_path / "test_fail.mp4"
    video.write_bytes(b"x" * 1024)

    mock_service = MagicMock()
    mock_insert_request = MagicMock()
    mock_insert_request.next_chunk.side_effect = Exception("Upload error")
    mock_service.videos.return_value.insert.return_value = mock_insert_request

    yt = YouTube()
    monkeypatch.setattr(
        yt, "_get_authenticated_service_for_project", lambda p: mock_service
    )

    assert video.exists()
    success = yt.upload(str(video), user="alice", purge_after=True)

    assert success is False
    assert video.exists()  # Retained on failure


def test_tiktok_recorder_youtube_upload_notifications(tmp_path, monkeypatch):
    from core.tiktok_recorder import TikTokRecorder

    recorder = TikTokRecorder(
        RecorderConfig(
            mode=Mode.MANUAL,
            user="streamer_yt",
            output=str(tmp_path),
            use_youtube=True,
        )
    )

    class FakeAPI:
        def get_live_url_candidates(self, room_id, user=None):
            return ["http://cdn.fake/live.flv"]

    recorder.tiktok = FakeAPI()

    mock_notify = MagicMock()
    recorder.notify = mock_notify

    class FakeStrategy:
        def record(self, **kwargs):
            vid = tmp_path / "video.mp4"
            vid.write_bytes(b"data")
            return True, str(vid), 1024 * 1024 * 20

    monkeypatch.setattr(
        "core.recording_strategies.get_recording_strategy",
        lambda *a, **kw: FakeStrategy(),
    )

    mock_yt = MagicMock()
    mock_yt.return_value.upload.return_value = True
    monkeypatch.setattr("upload.youtube.YouTube", mock_yt)

    recorder.start_recording("streamer_yt", "99999")

    events = [call.args[0] for call in mock_notify.notify.call_args_list]
    assert "recording_finished" in events
    assert "upload_started" in events
    assert "upload_finished" in events

    # Verify destination was YouTube
    yt_calls = [
        call.kwargs
        for call in mock_notify.notify.call_args_list
        if call.kwargs.get("destination") == "YouTube"
    ]
    assert len(yt_calls) == 2  # started + finished


def test_dual_upload_purge_coordination(tmp_path, monkeypatch):
    from core.tiktok_recorder import TikTokRecorder

    recorder = TikTokRecorder(
        RecorderConfig(
            mode=Mode.MANUAL,
            user="streamer_dual",
            output=str(tmp_path),
            use_telegram=True,
            use_youtube=True,
            purge_after_upload=True,
        )
    )

    class FakeAPI:
        def get_live_url_candidates(self, room_id, user=None):
            return ["http://cdn.fake/live.flv"]

    recorder.tiktok = FakeAPI()

    video_file = tmp_path / "dual_test.mp4"
    video_file.write_bytes(b"video data")

    class FakeStrategy:
        def record(self, **kwargs):
            return True, str(video_file), 1024 * 1024 * 10

    monkeypatch.setattr(
        "core.recording_strategies.get_recording_strategy",
        lambda *a, **kw: FakeStrategy(),
    )

    telegram_purge_flag = []
    youtube_purge_flag = []

    mock_tg = MagicMock()

    def fake_tg_upload(path, purge_after=False, **kwargs):
        telegram_purge_flag.append(purge_after)
        return True

    mock_tg.return_value.upload.side_effect = fake_tg_upload
    monkeypatch.setattr("upload.telegram.Telegram", mock_tg)

    mock_yt = MagicMock()

    def fake_yt_upload(path, purge_after=False, **kwargs):
        youtube_purge_flag.append(purge_after)
        return True

    mock_yt.return_value.upload.side_effect = fake_yt_upload
    monkeypatch.setattr("upload.youtube.YouTube", mock_yt)

    recorder.start_recording("streamer_dual", "88888")

    # Telegram must NOT purge because YouTube still needs to run
    assert telegram_purge_flag == [False]
    # YouTube MUST purge because it is the final uploader and Telegram succeeded
    assert youtube_purge_flag == [True]


def test_pacific_midnight_calculation():
    ts = get_next_pacific_midnight()
    now_ts = datetime.now(timezone.utc).timestamp()
    # Next midnight must be in the future (within 25 hours)
    assert ts > now_ts
    assert (ts - now_ts) <= 25 * 3600


def test_is_quota_exceeded():
    resp_403 = httplib2.Response({"status": "403"})
    err_quota = HttpError(
        resp_403, b'{"error": {"errors": [{"reason": "quotaExceeded"}]}}'
    )
    assert is_quota_exceeded(err_quota) is True

    err_daily = HttpError(
        resp_403, b'{"error": {"errors": [{"reason": "dailyLimitExceeded"}]}}'
    )
    assert is_quota_exceeded(err_daily) is True

    err_other_403 = HttpError(resp_403, b'{"error": {"message": "forbidden"}}')
    assert is_quota_exceeded(err_other_403) is False

    resp_500 = httplib2.Response({"status": "500"})
    err_500 = HttpError(resp_500, b'{"error": {"message": "internal"}}')
    assert is_quota_exceeded(err_500) is False


def test_multi_project_rotation_on_quota_exceeded(tmp_path, monkeypatch):
    """Method 2: If Project 1 hits quotaExceeded, rotation switches to Project 2 and succeeds."""
    video = tmp_path / "rotate_test.mp4"
    video.write_bytes(b"data" * 100)

    cfg = {
        "projects": [
            {
                "name": "P1",
                "client_secrets_file": "s1.json",
                "credentials_storage_file": "t1.json",
            },
            {
                "name": "P2",
                "client_secrets_file": "s2.json",
                "credentials_storage_file": "t2.json",
            },
        ],
        "queue_file": str(tmp_path / "queue.json"),
    }
    yt = YouTube(config_override=cfg)

    resp_403 = httplib2.Response({"status": "403"})
    quota_err = HttpError(
        resp_403, b'{"error": {"errors": [{"reason": "quotaExceeded"}]}}'
    )

    # Service 1 throws quotaExceeded
    req1 = MagicMock()
    req1.next_chunk.side_effect = quota_err
    service1 = MagicMock()
    service1.videos.return_value.insert.return_value = req1

    # Service 2 succeeds
    req2 = MagicMock()
    req2.next_chunk.return_value = (None, {"id": "vid_from_project_2"})
    service2 = MagicMock()
    service2.videos.return_value.insert.return_value = req2

    def mock_get_service(project):
        if project["name"] == "P1":
            return service1
        return service2

    monkeypatch.setattr(yt, "_get_authenticated_service_for_project", mock_get_service)

    success = yt.upload(str(video), user="charlie")
    assert success is True
    # Project 1 (index 0) must now be marked exhausted
    assert 0 in yt._exhausted_projects


def test_all_projects_exhausted_enqueues_file(tmp_path, monkeypatch):
    """Method 1: If all projects are exhausted, file is queued and not deleted."""
    video = tmp_path / "queue_me.mp4"
    video.write_bytes(b"data" * 100)

    queue_file = tmp_path / "test_queue.json"
    cfg = {
        "projects": [
            {
                "name": "P1",
                "client_secrets_file": "s1.json",
                "credentials_storage_file": "t1.json",
            },
        ],
        "queue_file": str(queue_file),
    }
    yt = YouTube(config_override=cfg)

    resp_403 = httplib2.Response({"status": "403"})
    quota_err = HttpError(
        resp_403, b'{"error": {"errors": [{"reason": "quotaExceeded"}]}}'
    )

    req = MagicMock()
    req.next_chunk.side_effect = quota_err
    service = MagicMock()
    service.videos.return_value.insert.return_value = req

    monkeypatch.setattr(yt, "_get_authenticated_service_for_project", lambda p: service)

    # Attempt upload with purge_after=True
    success = yt.upload(str(video), user="dave", purge_after=True)
    assert success is False

    # Local file MUST NOT be purged
    assert video.exists()

    # File must be enqueued in queue_file
    queue = yt._load_queue()
    assert len(queue) == 1
    assert queue[0]["user"] == "dave"
    assert queue[0]["last_error"] == "quotaExceeded"


def test_process_queue_flushes_pending_uploads(tmp_path, monkeypatch):
    """Method 1: process_queue successfully uploads and removes items from queue."""
    video = tmp_path / "queued_stream.mp4"
    video.write_bytes(b"data" * 50)

    queue_file = tmp_path / "test_queue.json"
    cfg = {
        "projects": [
            {
                "name": "P1",
                "client_secrets_file": "s1.json",
                "credentials_storage_file": "t1.json",
            },
        ],
        "queue_file": str(queue_file),
    }
    yt = YouTube(config_override=cfg)

    # Pre-populate queue with retry_after in the past
    yt._save_queue(
        [
            {
                "file_path": str(video),
                "user": "eve",
                "purge_after": True,
                "added_at": 1000.0,
                "retry_after": 2000.0,  # in the past relative to now
                "last_error": "quotaExceeded",
            }
        ]
    )

    req = MagicMock()
    req.next_chunk.return_value = (None, {"id": "vid_flushed_123"})
    service = MagicMock()
    service.videos.return_value.insert.return_value = req

    monkeypatch.setattr(yt, "_get_authenticated_service_for_project", lambda p: service)

    uploaded_count = yt.process_queue()
    assert uploaded_count == 1

    # Queue must now be empty
    queue = yt._load_queue()
    assert len(queue) == 0
    # Video was purged because purge_after was True in queue item
    assert not video.exists()


def test_format_metadata_with_display_name_and_timezone():
    from utils.timezone_manager import set_configured_timezone

    set_configured_timezone("Asia/Manila")

    yt = YouTube(
        config_override={
            "title_template": "{display_name} (@{username}) - Live {date}",
            "description_template": "Streamer: {display_name}\nHandle: @{username}\nID: {user_id}\nTime: {time} {timezone}",
        }
    )
    p = Path("video.mp4")
    title, desc = yt._format_metadata("charlidamelio", p, nickname="Charli D'Amelio")
    assert "Charli D'Amelio (@charlidamelio)" in title
    assert "Streamer: Charli D'Amelio" in desc
    assert "Handle: @charlidamelio" in desc
    assert "ID: charlidamelio" in desc
    assert "UTC+08:00" in desc

    set_configured_timezone(None)


def test_timezone_manager_philippines():
    from utils.timezone_manager import parse_timezone, format_configured_time

    tz, name = parse_timezone("Philippines")
    assert "08:00" in name
    formatted = format_configured_time("%Y-%m-%d")
    assert len(formatted) == 10
