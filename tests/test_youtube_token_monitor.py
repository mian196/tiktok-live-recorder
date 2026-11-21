import json
import os
import time
from unittest.mock import MagicMock, patch

from google.auth.exceptions import RefreshError

from notify.notifier import Notifier
from upload.youtube import YouTube
from upload.youtube_token_monitor import (
    check_all_youtube_tokens,
    check_project_token,
    get_token_expiry_info,
    record_token_issued,
)


def _write_token(path, refresh_token="refresh_1"):
    path.write_text(
        json.dumps(
            {
                "token": "access_1",
                "refresh_token": refresh_token,
                "token_uri": "https://oauth2.googleapis.com/token",
                "client_id": "cid",
                "client_secret": "csec",
                "scopes": ["https://www.googleapis.com/auth/youtube.upload"],
            }
        ),
        encoding="utf-8",
    )


def test_token_expiry_tracking_and_replacement(tmp_path):
    token_file = tmp_path / "youtube_token.json"
    state_file = tmp_path / "youtube_token_state.json"
    _write_token(token_file, refresh_token="token_v1")

    issued = 1_700_000_000.0
    entry = record_token_issued(
        str(token_file), issued_at=issued, lifetime_days=7, state_path=str(state_file)
    )
    assert entry["expires_at"] == issued + 7 * 86400

    # Same token_hash keeps original issued_at even if file mtime changes
    os.utime(token_file, (issued + 5000, issued + 5000))
    got_issued, got_expires, _ = get_token_expiry_info(
        str(token_file), lifetime_days=7, state_path=str(state_file)
    )
    assert got_issued == issued
    assert got_expires == issued + 7 * 86400

    # Replacing token with a new refresh_token resets issued_at to new file mtime
    _write_token(token_file, refresh_token="token_v2")
    new_mtime = issued + 10_000.0
    os.utime(token_file, (new_mtime, new_mtime))
    got_issued_2, got_expires_2, _ = get_token_expiry_info(
        str(token_file), lifetime_days=7, state_path=str(state_file)
    )
    assert got_issued_2 == new_mtime
    assert got_expires_2 == new_mtime + 7 * 86400


def test_check_project_token_missing(tmp_path):
    project = {
        "name": "Project 1",
        "credentials_storage_path": str(tmp_path / "missing.json"),
        "client_secrets_path": str(tmp_path / "secrets.json"),
    }
    res = check_project_token(project, state_path=str(tmp_path / "state.json"))
    assert res["status"] == "missing"
    assert "not found" in res["error"].lower()


def test_check_project_token_valid_and_expired(tmp_path):
    token_file = tmp_path / "youtube_token.json"
    state_file = tmp_path / "state.json"
    _write_token(token_file, refresh_token="rt_abc")
    record_token_issued(
        str(token_file),
        issued_at=time.time() - 86400,
        lifetime_days=7,
        state_path=str(state_file),
    )

    project = {
        "name": "Project 1",
        "credentials_storage_path": str(token_file),
        "client_secrets_path": str(tmp_path / "secrets.json"),
    }

    mock_creds = MagicMock()
    mock_creds.refresh_token = "rt_abc"

    with patch(
        "upload.youtube_token_monitor.Credentials.from_authorized_user_file",
        return_value=mock_creds,
    ):
        res_valid = check_project_token(project, state_path=str(state_file))
        assert res_valid["status"] == "valid"
        assert res_valid["remaining_seconds"] > 5 * 86400
        assert res_valid["expires_at_str"] != "Unknown"

        mock_creds.refresh.side_effect = RefreshError(
            "invalid_grant: Token has been expired or revoked."
        )
        res_expired = check_project_token(project, state_path=str(state_file))
        assert res_expired["status"] == "expired"
        assert "expired or revoked" in res_expired["error"].lower()


def test_check_all_youtube_tokens_notifications(tmp_path):
    token_ok = tmp_path / "token_ok.json"
    token_bad = tmp_path / "token_bad.json"
    state_file = tmp_path / "state.json"
    _write_token(token_ok, refresh_token="rt_ok")
    _write_token(token_bad, refresh_token="rt_bad")

    # Token OK expires in ~2 days (48h)
    record_token_issued(
        str(token_ok),
        issued_at=time.time() - (5 * 86400),
        lifetime_days=7,
        state_path=str(state_file),
    )
    record_token_issued(
        str(token_bad),
        issued_at=time.time() - (8 * 86400),
        lifetime_days=7,
        state_path=str(state_file),
    )

    yt = YouTube(
        config_override={
            "projects": [
                {
                    "name": "ProjOK",
                    "client_secrets_file": str(tmp_path / "s1.json"),
                    "credentials_storage_file": str(token_ok),
                },
                {
                    "name": "ProjBad",
                    "client_secrets_file": str(tmp_path / "s2.json"),
                    "credentials_storage_file": str(token_bad),
                },
            ]
        }
    )

    creds_ok = MagicMock(refresh_token="rt_ok")
    creds_bad = MagicMock(refresh_token="rt_bad")
    creds_bad.refresh.side_effect = RefreshError("invalid_grant")

    def _from_file(path, scopes):
        return creds_ok if "token_ok" in path else creds_bad

    notifier = MagicMock(spec=Notifier)

    with patch(
        "upload.youtube_token_monitor.Credentials.from_authorized_user_file",
        side_effect=_from_file,
    ):
        results = check_all_youtube_tokens(
            yt=yt,
            notifier=notifier,
            remind_before_hours=168,
            notify=True,
            state_path=str(state_file),
        )

    assert len(results) == 2
    assert results[0]["status"] == "valid"
    assert results[1]["status"] == "expired"

    assert notifier.notify.call_count == 2
    first_call = notifier.notify.call_args_list[0]
    second_call = notifier.notify.call_args_list[1]
    assert first_call.args[0] == "youtube_token_expiring"
    assert first_call.kwargs["project"] == "ProjOK"
    assert first_call.kwargs["expires_at"] != "Unknown"
    assert second_call.args[0] == "youtube_token_expired"
    assert second_call.kwargs["project"] == "ProjBad"


def test_remind_before_hours_skips_far_expiry(tmp_path):
    token_ok = tmp_path / "token_ok.json"
    state_file = tmp_path / "state.json"
    _write_token(token_ok, refresh_token="rt_ok")
    record_token_issued(
        str(token_ok),
        issued_at=time.time(),
        lifetime_days=7,
        state_path=str(state_file),
    )

    yt = YouTube(
        config_override={
            "projects": [
                {
                    "name": "ProjOK",
                    "client_secrets_file": str(tmp_path / "s1.json"),
                    "credentials_storage_file": str(token_ok),
                }
            ]
        }
    )
    notifier = Notifier(
        {"enabled": True, "discord_webhook_url": "http://fake.discord/hook"}
    )
    creds_ok = MagicMock(refresh_token="rt_ok")

    with (
        patch(
            "upload.youtube_token_monitor.Credentials.from_authorized_user_file",
            return_value=creds_ok,
        ),
        patch("requests.post") as mock_post,
    ):
        check_all_youtube_tokens(
            yt=yt,
            notifier=notifier,
            remind_before_hours=24,
            notify=True,
            state_path=str(state_file),
        )
        assert not mock_post.called
