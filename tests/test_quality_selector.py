import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.tiktok_api import TikTokAPI  # noqa: E402


class FakeResponse:
    def __init__(self, data=None, text="", status_code=200):
        self._data = data
        self.text = text
        self.status_code = status_code

    def json(self):
        return self._data


class FakeHttpClient:
    def __init__(self, responses):
        self.responses = responses
        self.urls = []

    def get(self, url):
        self.urls.append(url)
        return self.responses.pop(0)


def test_quality_best_orders_highest_level_first():
    stream_data = {
        "data": {
            "SD1": {"main": {"flv": "https://cdn.example.com/sd1.flv"}},
            "HD1": {"main": {"flv": "https://cdn.example.com/hd1.flv"}},
            "FULL_HD1": {"main": {"flv": "https://cdn.example.com/fhd.flv"}},
        }
    }
    options = {
        "qualities": [
            {"sdk_key": "SD1", "level": 1},
            {"sdk_key": "HD1", "level": 2},
            {"sdk_key": "FULL_HD1", "level": 3},
        ]
    }
    api_response = {
        "data": {
            "status": 2,
            "stream_url": {
                "live_core_sdk_data": {
                    "pull_data": {
                        "stream_data": json.dumps(stream_data),
                        "options": options,
                    }
                },
                "flv_pull_url": {},
            },
        },
        "status_code": 0,
    }

    api = TikTokAPI.__new__(TikTokAPI)
    api.WEBCAST_URL = "https://webcast.tiktok.com"
    api.BASE_URL = "https://www.tiktok.com"
    api.http_client = FakeHttpClient([FakeResponse(data=api_response)])

    urls = api.get_live_urls("123", quality="best")
    assert urls[0] == "https://cdn.example.com/fhd.flv"
    assert urls[1] == "https://cdn.example.com/hd1.flv"
    assert urls[2] == "https://cdn.example.com/sd1.flv"


def test_quality_worst_orders_lowest_level_first():
    stream_data = {
        "data": {
            "SD1": {"main": {"flv": "https://cdn.example.com/sd1.flv"}},
            "HD1": {"main": {"flv": "https://cdn.example.com/hd1.flv"}},
            "FULL_HD1": {"main": {"flv": "https://cdn.example.com/fhd.flv"}},
        }
    }
    options = {
        "qualities": [
            {"sdk_key": "SD1", "level": 1},
            {"sdk_key": "HD1", "level": 2},
            {"sdk_key": "FULL_HD1", "level": 3},
        ]
    }
    api_response = {
        "data": {
            "status": 2,
            "stream_url": {
                "live_core_sdk_data": {
                    "pull_data": {
                        "stream_data": json.dumps(stream_data),
                        "options": options,
                    }
                },
                "flv_pull_url": {},
            },
        },
        "status_code": 0,
    }

    api = TikTokAPI.__new__(TikTokAPI)
    api.WEBCAST_URL = "https://webcast.tiktok.com"
    api.BASE_URL = "https://www.tiktok.com"
    api.http_client = FakeHttpClient([FakeResponse(data=api_response)])

    urls = api.get_live_urls("123", quality="worst")
    assert urls[0] == "https://cdn.example.com/sd1.flv"
    assert urls[1] == "https://cdn.example.com/hd1.flv"
    assert urls[2] == "https://cdn.example.com/fhd.flv"


def test_quality_specific_preference():
    stream_data = {
        "data": {
            "SD1": {"main": {"flv": "https://cdn.example.com/sd1.flv"}},
            "HD1": {"main": {"flv": "https://cdn.example.com/hd1.flv"}},
            "FULL_HD1": {"main": {"flv": "https://cdn.example.com/fhd.flv"}},
        }
    }
    options = {
        "qualities": [
            {"sdk_key": "SD1", "level": 1},
            {"sdk_key": "HD1", "level": 2},
            {"sdk_key": "FULL_HD1", "level": 3},
        ]
    }
    api_response = {
        "data": {
            "status": 2,
            "stream_url": {
                "live_core_sdk_data": {
                    "pull_data": {
                        "stream_data": json.dumps(stream_data),
                        "options": options,
                    }
                },
                "flv_pull_url": {},
            },
        },
        "status_code": 0,
    }

    api = TikTokAPI.__new__(TikTokAPI)
    api.WEBCAST_URL = "https://webcast.tiktok.com"
    api.BASE_URL = "https://www.tiktok.com"
    api.http_client = FakeHttpClient([FakeResponse(data=api_response)])

    urls = api.get_live_urls("123", quality="HD1")
    assert urls[0] == "https://cdn.example.com/hd1.flv"
    assert urls[1] == "https://cdn.example.com/fhd.flv"
    assert urls[2] == "https://cdn.example.com/sd1.flv"


def test_page_scrape_fallback_respects_quality():
    page_html = (
        '<html><body>'
        '<script>var s1 = "https://pull.tiktok.com/stream_or4.flv"; '
        'var s2 = "https://pull.tiktok.com/stream_sd.flv";</script>'
        '</body></html>'
    )
    api = TikTokAPI.__new__(TikTokAPI)
    api.BASE_URL = "https://www.tiktok.com"
    api.http_client = FakeHttpClient([FakeResponse(text=page_html)])

    best_url = api._get_stream_url_from_page("testuser", quality="best")
    assert "_or4" in best_url

    api.http_client = FakeHttpClient([FakeResponse(text=page_html)])
    worst_url = api._get_stream_url_from_page("testuser", quality="worst")
    assert "_sd" in worst_url
