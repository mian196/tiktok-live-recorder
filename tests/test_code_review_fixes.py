import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.tiktok_api import TikTokAPI  # noqa: E402
from core.tiktok_recorder import _ConversionLock  # noqa: E402
from http_utils.http_client import HttpClient  # noqa: E402
from utils.custom_exceptions import LiveNotFound, UserLiveError  # noqa: E402
from utils.logger_manager import logger  # noqa: E402


def test_logger_warning_handler_level():
    stream_handlers = [
        h for h in logger.handlers if isinstance(h, logging.StreamHandler)
    ]
    warning_handlers = [
        h
        for h in stream_handlers
        if h.level <= logging.WARNING and h.stream == sys.stderr
    ]
    assert len(warning_handlers) >= 1


def test_get_user_from_room_id_detects_account_private():
    api = TikTokAPI.__new__(TikTokAPI)
    api.WEBCAST_URL = "https://webcast.tiktok.com"

    class FakeClient:
        def get(self, url, **kwargs):
            class Resp:
                def json(self):
                    return {"data": {}, "message": "This account is private"}

            return Resp()

    api.http_client = FakeClient()
    with pytest.raises(UserLiveError, match=r".*Account is private.*"):
        api.get_user_from_room_id("12345")


def test_get_room_and_user_from_url_raises_live_not_found_on_invalid():
    api = TikTokAPI.__new__(TikTokAPI)

    class FakeClient:
        def get(self, url, **kwargs):
            class Resp:
                status_code = 200
                text = "<html>No live user here</html>"

            return Resp()

    api.http_client = FakeClient()
    with pytest.raises(LiveNotFound):
        api.get_room_and_user_from_url("https://example.com/not-tiktok")


def test_check_proxy_configures_both_sessions():
    client = HttpClient.__new__(HttpClient)
    client.proxy = "http://127.0.0.1:8080"
    client.req = MagicMock()
    client.req.proxies = {}
    client.req_stream = MagicMock()
    client.req_stream.proxies = {}

    with patch("requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp

        client.check_proxy()

        expected = {"http": "http://127.0.0.1:8080", "https": "http://127.0.0.1:8080"}
        assert client.req.proxies == expected
        assert client.req_stream.proxies == expected


def test_check_proxy_handles_network_exception():
    client = HttpClient.__new__(HttpClient)
    client.proxy = "http://127.0.0.1:8080"
    client.req = MagicMock()
    client.req.proxies = {}
    client.req_stream = MagicMock()
    client.req_stream.proxies = {}

    with patch("requests.get", side_effect=Exception("Connection refused")):
        # Should not raise exception
        client.check_proxy()

        expected = {"http": "http://127.0.0.1:8080", "https": "http://127.0.0.1:8080"}
        assert client.req.proxies == expected
        assert client.req_stream.proxies == expected


def test_conversion_lock_context_manager():
    lock = _ConversionLock()
    with lock:
        assert lock._fd is not None
    assert lock._fd is None
