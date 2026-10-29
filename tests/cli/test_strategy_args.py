import sys
from unittest.mock import patch

import pytest

from utils.args_handler import validate_and_parse_args


def test_strategy_default_requests(monkeypatch):
    monkeypatch.setattr(
        sys, "argv", ["tiktok-live-recorder", "-mode", "manual", "-user", "test"]
    )
    args, _mode = validate_and_parse_args()
    assert args.recording_strategy == "requests"


def test_strategy_cli_flv_alias(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "tiktok-live-recorder",
            "-mode",
            "manual",
            "-user",
            "test",
            "-strategy",
            "flv",
        ],
    )
    args, _mode = validate_and_parse_args()
    assert args.recording_strategy == "requests"


def test_strategy_cli_ffmpeg_rejected(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "tiktok-live-recorder",
            "-mode",
            "manual",
            "-user",
            "test",
            "-strategy",
            "ffmpeg",
        ],
    )
    with pytest.raises(SystemExit):
        validate_and_parse_args()


def test_strategy_config_ffmpeg_fallback(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "tiktok-live-recorder",
            "-mode",
            "manual",
            "-user",
            "test",
        ],
    )
    with patch(
        "utils.utils.read_config", return_value={"recording_strategy": "ffmpeg"}
    ):
        args, _mode = validate_and_parse_args()
        assert args.recording_strategy == "requests"


def test_strategy_cli_ytdlp(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "tiktok-live-recorder",
            "-mode",
            "manual",
            "-user",
            "test",
            "--recording-strategy",
            "yt-dlp",
            "-yt-dlp-path",
            "C:/bin/yt-dlp.exe",
        ],
    )
    args, _mode = validate_and_parse_args()
    assert args.recording_strategy == "yt-dlp"
    assert args.yt_dlp_path == "C:/bin/yt-dlp.exe"


def test_strategy_invalid_choice_rejected(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "tiktok-live-recorder",
            "-mode",
            "manual",
            "-user",
            "test",
            "-strategy",
            "invalid_strat",
        ],
    )
    with pytest.raises(SystemExit):  # argparse raises SystemExit on invalid choices
        validate_and_parse_args()
