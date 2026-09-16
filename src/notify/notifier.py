import time
from pathlib import Path
import requests

from utils.logger_manager import logger
from utils.utils import read_config


class Notifier:
    def __init__(self, config_override: dict = None):
        cfg = (
            config_override
            if config_override is not None
            else read_config().get("notifications", {})
        )
        self.enabled = bool(cfg.get("enabled", False))
        self.discord_url = cfg.get("discord_webhook_url", "")
        self.use_telegram = bool(cfg.get("telegram", False))
        self.cooldown = int(cfg.get("cooldown_seconds", 30))
        self.events = cfg.get(
            "events",
            {
                "live_detected": True,
                "recording_started": True,
                "recording_finished": True,
                "recording_failed": True,
                "user_offline": True,
                "app_started": True,
                "app_error": True,
                "low_disk_space": True,
            },
        )
        self._last_sent: dict[str, float] = {}
        self._telegram = None

    def _get_cooldown_key(self, event: str, kwargs: dict) -> str:
        user = kwargs.get("user", "")
        return f"{event}:{user}" if user else event

    def _format(self, event: str, **kwargs) -> tuple[str, str, int]:
        """Return (title, description, color) for each event type."""
        user = kwargs.get("user", "Unknown")

        if event == "live_detected":
            return (
                "🔴 Live Detected",
                f"**@{user}** is now **LIVE** on TikTok!",
                0x2ECC71,  # Green
            )
        elif event == "recording_started":
            stream_idx = kwargs.get("stream_index", 1)
            total = kwargs.get("total", 1)
            return (
                "⏺️ Recording Started",
                f"Started recording **@{user}** (stream candidate {stream_idx}/{total}).",
                0x3498DB,  # Blue
            )
        elif event == "recording_finished":
            file_name = Path(kwargs.get("file", "")).name
            size_mb = kwargs.get("size_mb", 0)
            return (
                "✅ Recording Finished",
                f"Recording finished for **@{user}**.\n**File:** `{file_name}`\n**Size:** {size_mb} MB",
                0x2ECC71,  # Green
            )
        elif event == "recording_failed":
            error = kwargs.get("error", "Unknown error")
            return (
                "❌ Recording Failed",
                f"Recording failed for **@{user}**.\n**Error:** `{error}`",
                0xE74C3C,  # Red
            )
        elif event == "user_offline":
            return (
                "⏹️ User Offline",
                f"**@{user}** is no longer live. Recording stopped.",
                0xF1C40F,  # Yellow
            )
        elif event == "app_started":
            mode = kwargs.get("mode", "manual")
            interval = kwargs.get("interval", 5)
            return (
                "🚀 TikTok Live Recorder Started",
                f"Application started.\n**Mode:** `{mode}`\n**Interval:** {interval} min",
                0x3498DB,  # Blue
            )
        elif event == "app_error":
            error = kwargs.get("error", "Unknown application error")
            return (
                "🚨 Application Error",
                f"Application encountered an error:\n`{error}`",
                0xE74C3C,  # Red
            )
        elif event == "low_disk_space":
            free_gb = kwargs.get("free_gb", 0)
            threshold = kwargs.get("threshold", 5)
            return (
                "⚠️ Low Disk Space Alert",
                f"Free space: **{free_gb} GB** (threshold: {threshold} GB). Recording paused for **@{user}**.",
                0xE67E22,  # Orange
            )
        else:
            return ("Notification", str(kwargs), 0x95A5A6)

    def _send_discord(self, title: str, message: str, color: int):
        """Send a Discord embed via webhook."""
        if not self.discord_url:
            return
        payload = {
            "embeds": [
                {
                    "title": title,
                    "description": message,
                    "color": color,
                    "footer": {"text": "TikTok Live Recorder"},
                }
            ]
        }
        try:
            requests.post(self.discord_url, json=payload, timeout=10)
        except Exception as e:
            logger.debug(f"Discord notification failed: {e}")

    def _send_telegram(self, title: str, message: str):
        """Send a message via Telegram client."""
        try:
            if not self._telegram:
                from upload.telegram import Telegram

                self._telegram = Telegram()
            # Send plain notification message
            import asyncio

            async def _send():
                await self._telegram.client.connect()
                if not await self._telegram.client.is_user_authorized():
                    logger.debug(
                        "Telegram client is not authorized. Skipping notification."
                    )
                    await self._telegram.client.disconnect()
                    return
                await self._telegram.client.send_message(
                    self._telegram.chat_id,
                    f"<b>{title}</b>\n{message}",
                    parse_mode="html",
                )
                await self._telegram.client.disconnect()

            asyncio.run(_send())
        except Exception as e:
            logger.debug(f"Telegram notification failed: {e}")

    def notify(self, event: str, **kwargs):
        """Main entry point to dispatch notifications with rate-limit cooldown."""
        if not self.enabled:
            return

        if not self.events.get(event, True):
            return

        now = time.time()
        cd_key = self._get_cooldown_key(event, kwargs)
        if (
            cd_key in self._last_sent
            and (now - self._last_sent[cd_key]) < self.cooldown
        ):
            return

        title, message, color = self._format(event, **kwargs)

        if self.discord_url:
            self._send_discord(title, message, color)

        if self.use_telegram:
            self._send_telegram(title, message)

        self._last_sent[cd_key] = now
