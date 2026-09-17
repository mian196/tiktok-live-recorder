from pathlib import Path
from unittest.mock import MagicMock, patch

from utils.video_management import VideoManagement


def test_sanitize_mp4_timestamps_in_place(tmp_path):
    video_file = tmp_path / "stream.mp4"
    video_file.write_bytes(b"DATA" * 2000)

    def fake_subprocess_run(cmd, **kwargs):
        out_file = Path(cmd[-1])
        out_file.write_bytes(b"SANITIZED_DATA" * 2000)
        return MagicMock(returncode=0)

    with patch("subprocess.run", side_effect=fake_subprocess_run):
        success = VideoManagement.sanitize_mp4_timestamps(str(video_file))

    assert success is True
    assert video_file.exists()
    assert video_file.read_bytes() == b"SANITIZED_DATA" * 2000


def test_sanitize_mp4_timestamps_too_small(tmp_path):
    small_file = tmp_path / "tiny.mp4"
    small_file.write_bytes(b"small")

    success = VideoManagement.sanitize_mp4_timestamps(str(small_file))
    assert success is False


def test_recover_interrupted_with_in_progress_marker(tmp_path):
    user_dir = tmp_path / "creator1"
    user_dir.mkdir()
    video_file = user_dir / "creator1-stream.mp4"
    marker_file = user_dir / "creator1-stream.mp4.in_progress"

    video_file.write_bytes(b"FRAMES" * 2000)
    marker_file.touch()

    with patch(
        "utils.video_management.VideoManagement.sanitize_mp4_timestamps",
        return_value=True,
    ) as mock_sanitize:
        recovered = VideoManagement.recover_interrupted_recordings(str(tmp_path))

    assert recovered == 1
    assert not marker_file.exists()
    assert video_file.exists()
    mock_sanitize.assert_called_once_with(str(video_file), ffmpeg_path="ffmpeg")


def test_recover_interrupted_truncated_file_cleanup(tmp_path):
    video_file = tmp_path / "truncated.mp4"
    marker_file = tmp_path / "truncated.mp4.in_progress"

    video_file.write_bytes(b"EMPTY")  # < 4KB
    marker_file.touch()

    recovered = VideoManagement.recover_interrupted_recordings(str(tmp_path))
    assert recovered == 0
    assert not video_file.exists()
    assert not marker_file.exists()


def test_recover_unfinalized_part_file(tmp_path):
    part_file = tmp_path / "stream.mp4.part"
    part_file.write_bytes(b"YTDLP_PARTIAL" * 1000)
    final_mp4 = tmp_path / "stream.mp4"

    def fake_sanitize(in_f, output_file=None, ffmpeg_path=None):
        if output_file:
            Path(output_file).write_bytes(b"FINAL_MP4" * 1000)
            return True
        return False

    with patch(
        "utils.video_management.VideoManagement.sanitize_mp4_timestamps",
        side_effect=fake_sanitize,
    ):
        recovered = VideoManagement.recover_interrupted_recordings(str(tmp_path))

    assert recovered == 1
    assert final_mp4.exists()
    assert not part_file.exists()


def test_recover_orphaned_flv_segments(tmp_path):
    seg1 = tmp_path / "user-2026-09-17-part1.flv"
    seg2 = tmp_path / "user-2026-09-17-part2.flv"
    seg1.write_bytes(b"FLV1" * 1000)
    seg2.write_bytes(b"FLV2" * 1000)

    target_mp4 = tmp_path / "user-2026-09-17.mp4"

    def fake_convert(segments, out_mp4, **kwargs):
        Path(out_mp4).write_bytes(b"MERGED_MP4" * 2000)
        return True

    with patch(
        "utils.video_management.VideoManagement.convert_segments_to_mp4",
        side_effect=fake_convert,
    ) as mock_conv:
        recovered = VideoManagement.recover_interrupted_recordings(str(tmp_path))

    assert recovered == 1
    assert target_mp4.exists()
    mock_conv.assert_called_once()
    called_segments = mock_conv.call_args[0][0]
    assert len(called_segments) == 2
    assert str(seg1) in called_segments[0]
    assert str(seg2) in called_segments[1]


def test_recover_skips_already_finalized(tmp_path):
    seg1 = tmp_path / "user-2026-09-17-part1.flv"
    seg1.write_bytes(b"FLV1" * 1000)
    target_mp4 = tmp_path / "user-2026-09-17.mp4"
    target_mp4.write_bytes(b"ALREADY_FINALIZED" * 1000)

    with patch(
        "utils.video_management.VideoManagement.convert_segments_to_mp4"
    ) as mock_conv:
        recovered = VideoManagement.recover_interrupted_recordings(str(tmp_path))

    assert recovered == 0
    mock_conv.assert_not_called()
