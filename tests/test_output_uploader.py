import os
from unittest.mock import MagicMock

import pytest

from upload.output_uploader import (
    infer_username_from_path,
    list_output_videos,
    parse_selection,
    upload_selected_videos,
)
from upload.youtube import YouTube


def test_infer_username_from_path(tmp_path):
    # Subfolder pattern: output/<user>/<user>-YYYY-MM-DD-HH-MM-SS.mp4
    sub = tmp_path / "alice_live" / "alice_live-2026-11-20-12-00-00.mp4"
    assert infer_username_from_path(sub, tmp_path) == "alice_live"

    # Root pattern: output/<user>-YYYY-MM-DD-HH-MM-SS.mp4
    root_vid = tmp_path / "bob.stream-2026-11-20-12-00-00.mp4"
    assert infer_username_from_path(root_vid, tmp_path) == "bob.stream"


def test_list_output_videos_filters_and_sorts(tmp_path):
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "ignored.mp4").write_bytes(b"123")
    (tmp_path / ".test_tmp").mkdir()
    (tmp_path / ".test_tmp" / "ignored2.mp4").write_bytes(b"123")

    user_dir = tmp_path / "streamer1"
    user_dir.mkdir()
    old_vid = user_dir / "streamer1-2026-11-19-10-00-00.mp4"
    old_vid.write_bytes(b"a" * 1024)
    os.utime(old_vid, (1_700_000_000, 1_700_000_000))

    new_vid = tmp_path / "streamer2-2026-11-20-10-00-00.mp4"
    new_vid.write_bytes(b"b" * 2048)
    os.utime(new_vid, (1_700_010_000, 1_700_010_000))

    (tmp_path / "notes.txt").write_text("not a video", encoding="utf-8")
    (tmp_path / "partial.mp4.tmp.123").write_bytes(b"tmp")

    videos = list_output_videos(tmp_path)
    assert len(videos) == 2
    assert videos[0].index == 1
    assert videos[0].username == "streamer2"
    assert videos[1].index == 2
    assert videos[1].username == "streamer1"


def test_parse_selection():
    assert parse_selection("1", 5) == [1]
    assert parse_selection("1, 3, 5", 5) == [1, 3, 5]
    assert parse_selection("2-4, 1, 3", 5) == [2, 3, 4, 1]
    assert parse_selection("all", 3) == [1, 2, 3]

    with pytest.raises(ValueError):
        parse_selection("", 5)
    with pytest.raises(ValueError):
        parse_selection("6", 5)
    with pytest.raises(ValueError):
        parse_selection("4-2", 5)
    with pytest.raises(ValueError):
        parse_selection("abc", 5)


def test_upload_selected_videos_uses_youtube_template(tmp_path):
    user_dir = tmp_path / "streamer1"
    user_dir.mkdir()
    vid1 = user_dir / "streamer1-2026-11-20-10-00-00.mp4"
    vid1.write_bytes(b"video-bytes")

    videos = list_output_videos(tmp_path)
    assert len(videos) == 1

    yt = YouTube(
        config_override={
            "title_template": "VOD: {username}",
            "privacy_status": "unlisted",
        }
    )
    yt.upload = MagicMock(return_value=True)

    summary = upload_selected_videos(videos, yt=yt, purge_after=False)
    assert summary["total"] == 1
    assert summary["uploaded"] == 1
    assert summary["failed_or_queued"] == 0
    yt.upload.assert_called_once_with(
        file_path=str(vid1),
        user="streamer1",
        playlist=None,
        purge_after=False,
    )
