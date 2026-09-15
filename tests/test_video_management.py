from unittest.mock import MagicMock, patch

import ffmpeg

from utils.video_management import VideoManagement


def test_convert_segments_empty_list(tmp_path):
    output_file = str(tmp_path / "out.mp4")
    result = VideoManagement.convert_segments_to_mp4([], output_file)
    assert result is False


def test_convert_single_segment_success(tmp_path):
    seg = tmp_path / "part1.flv"
    seg.write_bytes(b"dummy flv content")
    out = tmp_path / "output.mp4"

    with patch("ffmpeg.input") as mock_input:
        mock_output = MagicMock()
        mock_input.return_value.output.return_value = mock_output
        mock_output.run.side_effect = lambda **kwargs: out.write_bytes(b"mp4 content")

        result = VideoManagement.convert_segments_to_mp4([str(seg)], str(out))

        assert result is True
        assert out.exists()
        assert not seg.exists()  # Cleaned up on success


def test_convert_multiple_segments_success(tmp_path):
    seg1 = tmp_path / "part1.flv"
    seg2 = tmp_path / "part2.flv"
    seg1.write_bytes(b"dummy flv part 1")
    seg2.write_bytes(b"dummy flv part 2")
    out = tmp_path / "output.mp4"

    with patch("ffmpeg.input") as mock_input:
        mock_output = MagicMock()
        mock_input.return_value.output.return_value = mock_output
        mock_output.run.side_effect = lambda **kwargs: out.write_bytes(b"mp4 content")

        result = VideoManagement.convert_segments_to_mp4(
            [str(seg1), str(seg2)], str(out)
        )

        assert result is True
        assert out.exists()
        assert not seg1.exists()
        assert not seg2.exists()


def test_convert_multiple_segments_fallback_on_copy_error(tmp_path):
    seg1 = tmp_path / "part1.flv"
    seg2 = tmp_path / "part2.flv"
    seg1.write_bytes(b"dummy flv part 1")
    seg2.write_bytes(b"dummy flv part 2")
    out = tmp_path / "output.mp4"

    calls = []

    def mock_run(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            # First call (-c copy) fails
            raise ffmpeg.Error("ffmpeg", "", b"Non-monotonous DTS")
        # Second call (transcode) succeeds
        out.write_bytes(b"transcoded mp4 content")

    with patch("ffmpeg.input") as mock_input:
        mock_output = MagicMock()
        mock_input.return_value.output.return_value = mock_output
        mock_output.run.side_effect = mock_run

        result = VideoManagement.convert_segments_to_mp4(
            [str(seg1), str(seg2)], str(out)
        )

        assert result is True
        assert len(calls) == 2
        assert out.exists()
        assert not seg1.exists()
        assert not seg2.exists()


def test_convert_preserves_segments_on_total_failure(tmp_path):
    seg1 = tmp_path / "part1.flv"
    seg1.write_bytes(b"important study session footage")
    out = tmp_path / "output.mp4"

    with patch("ffmpeg.input") as mock_input:
        mock_output = MagicMock()
        mock_input.return_value.output.return_value = mock_output
        mock_output.run.side_effect = ffmpeg.Error("ffmpeg", "", b"Fatal error")

        result = VideoManagement.convert_segments_to_mp4([str(seg1)], str(out))

        assert result is False
        assert not out.exists()
        # Original footage must be preserved!
        assert seg1.exists()
        assert seg1.read_bytes() == b"important study session footage"


def test_convert_keeps_flv_when_requested(tmp_path):
    seg1 = tmp_path / "part1.flv"
    seg2 = tmp_path / "part2.flv"
    seg1.write_bytes(b"dummy flv part 1")
    seg2.write_bytes(b"dummy flv part 2")
    out = tmp_path / "output.mp4"

    with patch("ffmpeg.input") as mock_input:
        mock_output = MagicMock()
        mock_input.return_value.output.return_value = mock_output
        mock_output.run.side_effect = lambda **kwargs: out.write_bytes(b"mp4 content")

        result = VideoManagement.convert_segments_to_mp4(
            [str(seg1), str(seg2)], str(out), keep_flv=True
        )

        assert result is True
        assert out.exists()
        # Both segments must be retained when keep_flv=True
        assert seg1.exists()
        assert seg2.exists()


def test_convert_preserves_flvs_on_duration_mismatch(tmp_path):
    """When the merged output video duration is less than the indexed duration,
    FLV files MUST NEVER be deleted even when keep_flv is False."""
    seg1 = tmp_path / "part1.flv"
    seg2 = tmp_path / "part2.flv"
    seg1.write_bytes(b"flv part 1 content")
    seg2.write_bytes(b"flv part 2 content")
    out = tmp_path / "output.mp4"

    def mock_get_duration(file_path, **kwargs):
        # seg1 = 50s, seg2 = 50s (Total indexed = 100s)
        # output file = 30s (Severe drop / dropped segment)
        if "part1" in str(file_path):
            return 50.0
        if "part2" in str(file_path):
            return 50.0
        if "output" in str(file_path):
            return 30.0
        return 0.0

    with (
        patch("ffmpeg.input") as mock_input,
        patch.object(
            VideoManagement, "get_segment_duration", side_effect=mock_get_duration
        ),
    ):
        mock_output = MagicMock()
        mock_input.return_value.output.return_value = mock_output
        mock_output.run.side_effect = lambda **kwargs: out.write_bytes(
            b"corrupted short mp4"
        )

        result = VideoManagement.convert_segments_to_mp4(
            [str(seg1), str(seg2)], str(out), keep_flv=False
        )

        # Verification fails due to duration mismatch
        assert result is False
        # FLV files MUST BE PRESERVED
        assert seg1.exists()
        assert seg2.exists()


def test_convert_deletes_flvs_when_duration_matches_and_keep_flv_false(tmp_path):
    """When the merged output video duration matches the indexed duration and keep_flv is False,
    FLVs should be safely cleaned up."""
    seg1 = tmp_path / "part1.flv"
    seg2 = tmp_path / "part2.flv"
    seg1.write_bytes(b"flv part 1 content")
    seg2.write_bytes(b"flv part 2 content")
    out = tmp_path / "output.mp4"

    def mock_get_duration(file_path, **kwargs):
        if "part1" in str(file_path):
            return 60.0
        if "part2" in str(file_path):
            return 40.0
        if "output" in str(file_path):
            return 100.0  # Exact match
        return 0.0

    with (
        patch("ffmpeg.input") as mock_input,
        patch.object(
            VideoManagement, "get_segment_duration", side_effect=mock_get_duration
        ),
    ):
        mock_output = MagicMock()
        mock_input.return_value.output.return_value = mock_output
        mock_output.run.side_effect = lambda **kwargs: out.write_bytes(
            b"healthy full mp4"
        )

        result = VideoManagement.convert_segments_to_mp4(
            [str(seg1), str(seg2)], str(out), keep_flv=False
        )

        assert result is True
        assert out.exists()
        # Cleaned up safely
        assert not seg1.exists()
        assert not seg2.exists()


def test_convert_passes_move_to_recycle_bin(tmp_path):
    seg1 = tmp_path / "part1.flv"
    seg1.write_bytes(b"flv part 1 content")
    out = tmp_path / "output.mp4"

    with (
        patch("ffmpeg.input") as mock_input,
        patch.object(VideoManagement, "remove_or_trash_file") as mock_trash,
    ):
        mock_output = MagicMock()
        mock_input.return_value.output.return_value = mock_output
        mock_output.run.side_effect = lambda **kwargs: out.write_bytes(b"mp4 content")

        result = VideoManagement.convert_segments_to_mp4(
            [str(seg1)], str(out), keep_flv=False, move_to_recycle_bin=True
        )

        assert result is True
        mock_trash.assert_called_once_with(str(seg1), move_to_recycle_bin=True)


def test_remove_or_trash_file_fallback_deletes_file(tmp_path):
    seg = tmp_path / "test.flv"
    seg.write_bytes(b"dummy")
    assert seg.exists()

    # When move_to_recycle_bin is False, directly removes
    success = VideoManagement.remove_or_trash_file(str(seg), move_to_recycle_bin=False)
    assert success is True
    assert not seg.exists()
