import asyncio
import sys
import threading
from pathlib import Path

from telethon import TelegramClient

from utils.logger_manager import logger
from utils.utils import read_telegram_config


FREE_USER_MAX_FILE_SIZE = 2 * 1024 * 1024 * 1024
PREMIUM_USER_MAX_FILE_SIZE = 4 * 1024 * 1024 * 1024

_telegram_lock = threading.Lock()


def parse_chat_id(chat_id):
    """Normalize chat_id: empty/None -> 'me', numeric strings -> int, otherwise keep as is."""
    if chat_id is None or chat_id == "":
        return "me"
    if isinstance(chat_id, str):
        stripped = chat_id.strip()
        if (stripped.startswith("-") and stripped[1:].isdigit()) or stripped.isdigit():
            return int(stripped)
        return stripped
    return chat_id


class Telegram:
    def __init__(self):
        config = read_telegram_config()

        self.api_id = config.get("api_id")
        self.api_hash = config.get("api_hash")
        self.chat_id = parse_chat_id(config.get("chat_id"))
        raw_topic_id = config.get("topic_id")
        self.topic_id = (
            int(raw_topic_id)
            if raw_topic_id is not None and str(raw_topic_id).strip().isdigit()
            else None
        )

        self.client = TelegramClient(
            "tiktok_live_recorder_session",
            api_id=self.api_id,
            api_hash=self.api_hash,
        )

    async def _resolve_entity(self, entity):
        """Resolve entity, fetching dialogs if not yet cached in the session."""
        try:
            return await self.client.get_input_entity(entity)
        except (ValueError, TypeError):
            try:
                await self.client.get_dialogs(limit=100)
                return await self.client.get_input_entity(entity)
            except Exception:
                return entity

    def upload(self, file_path: str) -> bool:
        """
        Upload a file to Telegram (Saved Messages or configured chat_id) via Telethon.
        Returns True if upload succeeded, False otherwise.
        """

        async def _upload() -> bool:
            try:
                await self.client.connect()

                if not await self.client.is_user_authorized():
                    if not sys.stdin or not sys.stdin.isatty():
                        logger.error(
                            "Telegram client is not authorized and running without interactive TTY. "
                            "Please run interactively to authenticate."
                        )
                        return False
                    await self.client.start()

                me = await self.client.get_me()
                is_premium = getattr(me, "premium", False)
                max_size = (
                    PREMIUM_USER_MAX_FILE_SIZE
                    if is_premium
                    else FREE_USER_MAX_FILE_SIZE
                )

                file_size = Path(file_path).stat().st_size
                logger.info(
                    f"File to upload: {Path(file_path).name} "
                    f"({round(file_size / (1024 * 1024))} MB)"
                )

                if file_size > max_size:
                    logger.warning(
                        "The file is too large to be uploaded "
                        "with this type of account."
                    )
                    return False

                logger.info(
                    "Uploading video on Telegram... "
                    "This may take a while depending on file size."
                )

                target_entity = await self._resolve_entity(self.chat_id)

                send_kwargs = {
                    "entity": target_entity,
                    "file": file_path,
                    "caption": (
                        "🎥 <b>Video recorded via "
                        '<a href="https://github.com/Michele0303/'
                        'tiktok-live-recorder">'
                        "TikTok Live Recorder</a></b>"
                    ),
                    "parse_mode": "html",
                    "force_document": True,
                }
                if self.topic_id is not None:
                    send_kwargs["reply_to"] = self.topic_id

                await self.client.send_file(**send_kwargs)

                logger.info("File successfully uploaded to Telegram.\n")
                return True

            except Exception as e:
                logger.error(f"Error during Telegram upload: {e}\n", exc_info=True)
                return False

            finally:
                await self.client.disconnect()

        with _telegram_lock:
            return asyncio.run(_upload())
