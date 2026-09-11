import json
import sys
from unittest.mock import patch

from utils.args_handler import validate_and_parse_args
from utils.enums import Mode


def test_read_config_from_file(tmp_path, monkeypatch):
    config_data = {
        "user": "config_user",
        "mode": "automatic",
        "automatic_interval": 15,
        "keep_flv": True,
    }
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps(config_data), encoding="utf-8")

    with patch("utils.utils._get_config_path", return_value=str(cfg_file)):
        # Run without CLI args, should pick up from config.json
        monkeypatch.setattr(sys, "argv", ["tiktok-live-recorder"])
        args, mode = validate_and_parse_args()

        assert args.user == "config_user"
        assert mode == Mode.AUTOMATIC
        assert args.automatic_interval == 15
        assert args.keep_flv is True


def test_cli_args_override_config_file(tmp_path, monkeypatch):
    config_data = {
        "user": "config_user",
        "mode": "automatic",
        "automatic_interval": 15,
    }
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps(config_data), encoding="utf-8")

    with patch("utils.utils._get_config_path", return_value=str(cfg_file)):
        # Provide CLI args that override config.json
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "tiktok-live-recorder",
                "-user",
                "cli_user",
                "-mode",
                "manual",
                "-automatic_interval",
                "20",
            ],
        )
        args, mode = validate_and_parse_args()

        assert args.user == "cli_user"
        assert mode == Mode.MANUAL
        assert args.automatic_interval == 20
