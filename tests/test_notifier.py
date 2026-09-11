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
