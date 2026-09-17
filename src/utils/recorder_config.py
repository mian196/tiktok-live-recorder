from dataclasses import dataclass

from utils.enums import Mode
from utils.user_identity import TrackedUser


@dataclass
class RecorderConfig:
    mode: Mode
    url: str | None = None
    user: str | None = None
    users: list[str] | None = None
    tracked_users: list[TrackedUser] | None = None
    room_id: str | None = None
    automatic_interval: int = 5
    cookies: dict | None = None
    proxy: str | None = None
    output: str | None = None
    duration: int | None = None
    use_telegram: bool = False
    bitrate: str | None = None
    ffmpeg_path: str | None = None
    keep_flv: bool = False
    move_to_recycle_bin: bool = True
    retry_delay: int = 5
    disk_space_alert_gb: int = 5
    recording_strategy: str = "requests"
    yt_dlp_path: str | None = None
