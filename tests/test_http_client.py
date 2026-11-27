from functools import partial
from unittest.mock import MagicMock, patch

from http_utils.http_client import HttpClient


def test_termux_requests_session_has_default_timeout():
    mock_request = MagicMock(return_value="ok")
    with (
        patch("http_utils.http_client.is_termux", return_value=True),
        patch.object(HttpClient, "check_proxy"),
        patch("requests.Session.request", mock_request),
    ):
        client = HttpClient()
        assert client.req is client.req_stream
        assert isinstance(client.req.request, partial)
        assert client.req.request.keywords["timeout"] == (10, 30)
        client.req.get("https://example.com")

    assert mock_request.call_args.kwargs["timeout"] == (10, 30)
