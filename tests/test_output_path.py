import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.tiktok_recorder import TikTokRecorder  # noqa: E402
from utils.enums import Mode  # noqa: E402
from utils.recorder_config import RecorderConfig  # noqa: E402


def test_build_output_path_creates_user_subdirectory(tmp_path):
    recorder = TikTokRecorder(
        RecorderConfig(
            mode=Mode.MANUAL,
            user="streamer_xyz",
            output=str(tmp_path),
        )
    )

    path_str = recorder._build_output_path("streamer_xyz")
    out_path = Path(path_str)

    assert out_path.parent == tmp_path / "streamer_xyz"
    assert out_path.parent.is_dir()
    assert out_path.name.startswith("streamer_xyz-")
    assert out_path.suffix == ".mp4"


def test_build_output_path_without_output_dir():
    recorder = TikTokRecorder(
        RecorderConfig(
            mode=Mode.MANUAL,
            user="streamer_xyz",
            output=None,
        )
    )

    path_str = recorder._build_output_path("streamer_xyz")
    assert path_str.startswith("streamer_xyz-")
    assert path_str.endswith(".mp4")
