from unittest.mock import patch

from notify.notifier import Notifier


def test_notifier_disabled_by_default():
    with patch("requests.post") as mock_post:
        notifier = Notifier(
            {"enabled": False, "discord_webhook_url": "http://fake.discord/webhook"}
        )
        notifier.notify("live_detected", user="test_user")
        assert not mock_post.called


def test_notifier_sends_discord_embed():
    with patch("requests.post") as mock_post:
        notifier = Notifier(
            {
                "enabled": True,
                "discord_webhook_url": "http://fake.discord/webhook",
                "events": {"live_detected": True},
            }
        )
        notifier.notify("live_detected", user="streamer123")
        assert mock_post.called
        call_kwargs = mock_post.call_args[1]
        payload = call_kwargs["json"]
        assert len(payload["embeds"]) == 1
        assert "streamer123" in payload["embeds"][0]["description"]
        assert payload["embeds"][0]["color"] == 0x2ECC71


def test_notifier_cooldown():
    with patch("requests.post") as mock_post:
        notifier = Notifier(
            {
                "enabled": True,
                "discord_webhook_url": "http://fake.discord/webhook",
                "cooldown_seconds": 60,
                "events": {"live_detected": True},
            }
        )
        # First call should fire
        notifier.notify("live_detected", user="streamer123")
        assert mock_post.call_count == 1

        # Second immediate call with same user should be throttled by cooldown
        notifier.notify("live_detected", user="streamer123")
        assert mock_post.call_count == 1

        # Call with different user should fire
        notifier.notify("live_detected", user="other_streamer")
        assert mock_post.call_count == 2


def test_notifier_error_never_raises():
    with patch("requests.post", side_effect=Exception("Network error")):
        notifier = Notifier(
            {
                "enabled": True,
                "discord_webhook_url": "http://fake.discord/webhook",
                "events": {"recording_failed": True},
            }
        )
        # Must not raise an exception
        notifier.notify("recording_failed", user="user1", error="Some error")


def test_notifier_upload_events():
    with patch("requests.post") as mock_post:
        notifier = Notifier(
            {
                "enabled": True,
                "discord_webhook_url": "http://fake.discord/webhook",
            }
        )

        notifier.notify(
            "upload_started",
            user="streamer1",
            file="streamer1_2026.mp4",
            size_mb=120,
        )
        assert mock_post.called
        assert "Upload Started" in mock_post.call_args[1]["json"]["embeds"][0]["title"]
        assert "120 MB" in mock_post.call_args[1]["json"]["embeds"][0]["description"]

        notifier.notify(
            "upload_finished",
            user="streamer1",
            file="streamer1_2026.mp4",
            size_mb=120,
        )
        assert "Upload Finished" in mock_post.call_args[1]["json"]["embeds"][0]["title"]

        notifier.notify(
            "upload_failed",
            user="streamer1",
            file="streamer1_2026.mp4",
            error="File size too large",
        )
        assert "Upload Failed" in mock_post.call_args[1]["json"]["embeds"][0]["title"]


def test_telegram_parse_chat_id():
    from upload.telegram import parse_chat_id

    assert parse_chat_id("me") == "me"
    assert parse_chat_id("") == "me"
    assert parse_chat_id(None) == "me"
    assert parse_chat_id("-1001234567890") == -1001234567890
    assert parse_chat_id(-1001234567890) == -1001234567890
    assert parse_chat_id("123456789") == 123456789
    assert parse_chat_id("@my_channel") == "@my_channel"


def test_telegram_topic_id_init(monkeypatch):
    from unittest.mock import MagicMock

    from upload.telegram import Telegram

    monkeypatch.setattr("upload.telegram.TelegramClient", MagicMock())
    monkeypatch.setattr(
        "upload.telegram.read_telegram_config",
        lambda: {
            "api_id": 123,
            "api_hash": "abc",
            "chat_id": "-100123",
            "topic_id": "42",
        },
    )
    t = Telegram()
    assert t.chat_id == -100123
    assert t.topic_id == 42


def test_notifier_upload_blocked_by_oauth_token_expiry():
    with patch("requests.post") as mock_post:
        notifier = Notifier(
            {
                "enabled": True,
                "discord_webhook_url": "http://fake.discord/webhook",
            }
        )

        notifier.notify(
            "upload_failed",
            user="streamer1",
            file="output/test_video.mp4",
            error="YouTube OAuth token has expired or was revoked. Please re-authenticate using 'python auth.py --youtube'.",
            destination="YouTube",
        )

        assert mock_post.called
        embed = mock_post.call_args[1]["json"]["embeds"][0]
        assert "Upload Blocked" in embed["title"]
        assert "YouTube" in embed["title"]
        assert "OAuth token has expired or was revoked" in embed["description"]
        assert "safely preserved locally" in embed["description"]


def test_notifier_telegram_bot_api():
    from unittest.mock import MagicMock

    with patch("requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200)
        notifier = Notifier(
            {
                "enabled": True,
                "telegram": True,
                "telegram_bot_token": "123456:ABC-DEF",
                "telegram_chat_id": "987654321",
            }
        )

        notifier.notify(
            "upload_blocked",
            user="streamer1",
            file="output/test_video.mp4",
            error="OAuth token expired",
            destination="YouTube",
        )

        assert mock_post.called
        # Verify call to telegram API
        tg_call = [c for c in mock_post.call_args_list if "api.telegram.org" in str(c)]
        assert len(tg_call) == 1
        data = tg_call[0][1]["json"]
        assert data["chat_id"] == "987654321"
        assert "Upload Blocked" in data["text"]
        assert "OAuth token expired" in data["text"]
