import sys
import pytest

from utils.args_handler import validate_and_parse_args


def test_strategy_default_requests(monkeypatch):
    monkeypatch.setattr(
        sys, "argv", ["tiktok-live-recorder", "-mode", "manual", "-user", "test"]
    )
    args, mode = validate_and_parse_args()
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
    args, mode = validate_and_parse_args()
    assert args.recording_strategy == "requests"


def test_strategy_cli_ffmpeg(monkeypatch):
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
    args, mode = validate_and_parse_args()
    assert args.recording_strategy == "ffmpeg"


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
    args, mode = validate_and_parse_args()
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
