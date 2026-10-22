import asyncio
import sys
import threading
from pathlib import Path

from telethon import TelegramClient

from utils.logger_manager import logger
from utils.utils import read_telegram_config, read_config


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

    def upload(
        self, file_path: str, purge_after: bool = False, ffmpeg_path: str = None
    ) -> bool:
        """
        Upload a file to Telegram (Saved Messages or configured chat_id) via Telethon.
        If file exceeds max_size (or 1950MB safety cap), fast-splits into parts without
        re-encoding and uploads each part sequentially.
        If purge_after is True, deletes local files after successful upload.
        Returns True if upload succeeded, False otherwise.
        """
        from utils.video_management import VideoManagement

        async def _upload_single_file(
            client, file_to_send: str, caption_suffix: str = ""
        ) -> bool:
            target_entity = await self._resolve_entity(self.chat_id)
            caption = (
                "🎥 <b>Video recorded via "
                '<a href="https://github.com/mian196/tiktok-live-recorder/'
                'tiktok-live-recorder">'
                "TikTok Live Recorder</a></b>"
            )
            if caption_suffix:
                caption += f"\n{caption_suffix}"

            send_kwargs = {
                "entity": target_entity,
                "file": file_to_send,
                "caption": caption,
                "parse_mode": "html",
                "force_document": True,
            }
            if self.topic_id is not None:
                send_kwargs["reply_to"] = self.topic_id

            await client.send_file(**send_kwargs)
            return True

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
                max_allowed = (
                    PREMIUM_USER_MAX_FILE_SIZE
                    if is_premium
                    else FREE_USER_MAX_FILE_SIZE
                )

                app_cfg = read_config()
                split_enabled = bool(app_cfg.get("split_video", True))
                cfg_split_mb = app_cfg.get("split_size_mb")

                if (
                    cfg_split_mb is not None
                    and str(cfg_split_mb).isdigit()
                    and int(cfg_split_mb) > 0
                ):
                    split_threshold = int(cfg_split_mb) * 1024 * 1024
                else:
                    split_threshold = min(max_allowed, 1950 * 1024 * 1024)

                source_path = Path(file_path)
                if not source_path.exists():
                    logger.error(f"File not found for upload: {file_path}")
                    return False

                file_size = source_path.stat().st_size
                logger.info(
                    f"File to upload: {source_path.name} "
                    f"({round(file_size / (1024 * 1024))} MB)"
                )

                # Check if splitting is needed
                files_to_upload = [str(source_path)]
                was_split = False
                if split_enabled and file_size > split_threshold:
                    logger.info(
                        f"File size exceeds split threshold ({round(split_threshold / (1024 * 1024))} MB). "
                        "Splitting without re-encoding..."
                    )
                    files_to_upload = VideoManagement.fast_split_video(
                        str(source_path),
                        max_bytes=split_threshold,
                        ffmpeg_path=ffmpeg_path,
                    )
                    was_split = len(files_to_upload) > 1
                elif not split_enabled and file_size > max_allowed:
                    logger.warning(
                        f"File size ({round(file_size / (1024 * 1024))} MB) exceeds Telegram max size "
                        f"({round(max_allowed / (1024 * 1024))} MB) and split_video is disabled."
                    )
                    return False

                total_parts = len(files_to_upload)
                for idx, part in enumerate(files_to_upload):
                    p_path = Path(part)
                    part_mb = round(p_path.stat().st_size / (1024 * 1024))
                    logger.info(
                        f"Uploading to Telegram [{idx + 1}/{total_parts}]: {p_path.name} ({part_mb} MB)..."
                    )
                    suffix = (
                        f"<b>Part {idx + 1}/{total_parts}</b>"
                        if total_parts > 1
                        else ""
                    )
                    await _upload_single_file(self.client, part, caption_suffix=suffix)
                    logger.info(f"Part {idx + 1}/{total_parts} uploaded successfully.")

                    if was_split and part != str(source_path):
                        try:
                            p_path.unlink(missing_ok=True)
                            logger.info(f"Removed split chunk: {p_path.name}")
                        except Exception as e:
                            logger.debug(f"Could not remove split part {part}: {e}")

                if purge_after and source_path.exists():
                    try:
                        source_path.unlink(missing_ok=True)
                        logger.info(f"Purged local recording file: {source_path.name}")
                    except Exception as e:
                        logger.warning(f"Could not purge {source_path.name}: {e}")

                logger.info("File successfully uploaded to Telegram.\n")
                return True

            except Exception as e:
                logger.error(f"Error during Telegram upload: {e}\n", exc_info=True)
                return False

            finally:
                await self.client.disconnect()

        with _telegram_lock:
            return asyncio.run(_upload())
