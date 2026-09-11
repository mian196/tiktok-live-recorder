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

