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
                "upload_started": True,
                "upload_finished": True,
                "upload_failed": True,
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
            if isinstance(interval, (int, float)):
                if interval < 1:
                    interval_str = f"{int(round(interval * 60))}s"
                else:
                    mins = int(interval) if int(interval) == interval else interval
                    interval_str = f"{mins} min"
            else:
                interval_str = f"{interval}"
            return (
                "🚀 TikTok Live Recorder Started",
                f"Application started.\n**Mode:** `{mode}`\n**Interval:** {interval_str}",
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
        elif event == "upload_started":
            file_name = Path(kwargs.get("file", "")).name
            size_mb = kwargs.get("size_mb", 0)
            destination = kwargs.get("destination", "Telegram")
            return (
                "📤 Upload Started",
                f"Uploading recording for **@{user}** to {destination}.\n**File:** `{file_name}`\n**Size:** {size_mb} MB",
                0x3498DB,  # Blue
            )
        elif event == "upload_finished":
            file_name = Path(kwargs.get("file", "")).name
            size_mb = kwargs.get("size_mb", 0)
            destination = kwargs.get("destination", "Telegram")
            return (
                "☁️ Upload Finished",
                f"Successfully uploaded recording for **@{user}** to {destination}.\n**File:** `{file_name}`\n**Size:** {size_mb} MB",
                0x2ECC71,  # Green
            )
        elif event == "upload_failed":
            file_name = Path(kwargs.get("file", "")).name
            error = kwargs.get("error", "Unknown error")
            destination = kwargs.get("destination", "Telegram")
            return (
                "❌ Upload Failed",
                f"Failed to upload recording for **@{user}** to {destination}.\n**File:** `{file_name}`\n**Error:** `{error}`",
                0xE74C3C,  # Red
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
            from upload.telegram import _telegram_lock
            import asyncio

            async def _send():
                await self._telegram.client.connect()
                if not await self._telegram.client.is_user_authorized():
                    logger.debug(
                        "Telegram client is not authorized. Skipping notification."
                    )
                    await self._telegram.client.disconnect()
                    return
                target_entity = await self._telegram._resolve_entity(
                    self._telegram.chat_id
                )
                text = f"**{title}**\n{message}"
                send_kwargs = {
                    "entity": target_entity,
                    "message": text,
                    "parse_mode": "md",
                }
                if getattr(self._telegram, "topic_id", None) is not None:
                    send_kwargs["reply_to"] = self._telegram.topic_id

                try:
                    await self._telegram.client.send_message(**send_kwargs)
                except Exception:
                    send_kwargs["parse_mode"] = None
                    send_kwargs["message"] = f"{title}\n{message}"
                    await self._telegram.client.send_message(**send_kwargs)
                await self._telegram.client.disconnect()

            with _telegram_lock:
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
