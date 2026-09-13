from dataclasses import dataclass
from typing import Any


@dataclass
class TrackedUser:
    username: str
    sec_uid: str | None = None
    user_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"username": self.username}
        if self.sec_uid:
            data["sec_uid"] = self.sec_uid
        if self.user_id:
            data["user_id"] = self.user_id
        return data

    @classmethod
    def from_item(cls, item: Any) -> "TrackedUser | None":
        if isinstance(item, str):
            clean = item.lstrip("@").strip()
            return cls(username=clean) if clean else None
        elif isinstance(item, dict):
            username = item.get("username") or item.get("user") or item.get("unique_id")
            if not username:
                return None
            clean_username = str(username).lstrip("@").strip()
            sec_uid = item.get("sec_uid") or item.get("secUid")
            user_id = item.get("user_id") or item.get("userId") or item.get("id")
            return cls(
                username=clean_username,
                sec_uid=str(sec_uid) if sec_uid else None,
                user_id=str(user_id) if user_id else None,
            )
        return None


def parse_tracked_users(raw_value: Any) -> list[TrackedUser]:
    """
    Parses raw user input (string, comma-separated string, list of strings/dicts)
    into a list of TrackedUser objects.
    """
    if raw_value is None:
        return []

    if isinstance(raw_value, str):
        # Support comma-separated strings
        parts = [p.strip() for p in raw_value.split(",") if p.strip()]
        result = []
        for p in parts:
            user = TrackedUser.from_item(p)
            if user:
                result.append(user)
        return result

    if isinstance(raw_value, dict):
        user = TrackedUser.from_item(raw_value)
        return [user] if user else []

    if isinstance(raw_value, (list, tuple)):
        result = []
        for item in raw_value:
            user = TrackedUser.from_item(item)
            if user:
                result.append(user)
        return result

    return []
