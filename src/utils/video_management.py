import os
import sys
import time
from pathlib import Path

import ffmpeg

from utils.logger_manager import logger


class VideoManagement:
    @staticmethod
    def remove_or_trash_file(file_path: str, move_to_recycle_bin: bool = True) -> bool:
        """
        Safely remove a file by moving it to the system Recycle Bin (Windows) or Trash (macOS/Linux),
        falling back to permanent deletion if trash operation is unavailable or disabled.
        """
        path = Path(file_path)
        if not path.exists():
            return True

        if move_to_recycle_bin:
            try:
                if sys.platform == "win32":
                    import ctypes
                    from ctypes import wintypes

                    class SHFILEOPSTRUCTW(ctypes.Structure):
                        _fields_ = [
                            ("hwnd", wintypes.HWND),
                            ("wFunc", wintypes.UINT),
                            ("pFrom", wintypes.LPCWSTR),
                            ("pTo", wintypes.LPCWSTR),
                            ("fFlags", wintypes.WORD),
                            ("fAnyOperationsAborted", wintypes.BOOL),
                            ("hNameMappings", wintypes.LPVOID),
                            ("lpszProgressTitle", wintypes.LPCWSTR),
                        ]

                    FO_DELETE = 0x0003
                    FOF_ALLOWUNDO = (
                        0x0040  # Move to Recycle Bin instead of permanent deletion
                    )
                    FOF_NOCONFIRMATION = 0x0010  # Don't ask user for confirmation
                    FOF_SILENT = 0x0004  # Don't show progress dialog
                    FOF_NOERRORUI = 0x0400  # Don't display error UI

                    # Windows SHFileOperation requires double null-terminated string
                    p_from = str(path.resolve()) + "\0\0"
                    fileop = SHFILEOPSTRUCTW(
                        hwnd=None,
                        wFunc=FO_DELETE,
                        pFrom=p_from,
                        pTo=None,
                        fFlags=(
                            FOF_ALLOWUNDO
                            | FOF_NOCONFIRMATION
                            | FOF_SILENT
                            | FOF_NOERRORUI
                        ),
                        fAnyOperationsAborted=False,
                        hNameMappings=None,
                        lpszProgressTitle=None,
                    )
                    res = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(fileop))
                    if (
                        res == 0
                        and not fileop.fAnyOperationsAborted
                        and not path.exists()
                    ):
                        logger.info(f"Moved {path.name} to Recycle Bin.")
                        return True
                elif sys.platform == "darwin":
                    import subprocess

                    cmd = [
                        "osascript",
                        "-e",
                        f'tell application "Finder" to delete POSIX file "{path.resolve()}"',
                    ]
                    proc = subprocess.run(cmd, capture_output=True, text=True)
                    if proc.returncode == 0 and not path.exists():
                        logger.info(f"Moved {path.name} to Trash.")
                        return True
                else:
                    import subprocess

                    for tool in [
                        ["gio", "trash", str(path.resolve())],
                        ["trash-put", str(path.resolve())],
                    ]:
                        try:
                            proc = subprocess.run(tool, capture_output=True, text=True)
                            if proc.returncode == 0 and not path.exists():
                                logger.info(f"Moved {path.name} to Trash.")
                                return True
                        except Exception:
                            continue
            except Exception as e:
                logger.warning(
                    f"Could not move {file_path} to Recycle Bin/Trash: {e}. Falling back to standard removal."
                )

        # Standard deletion fallback
        try:
            os.remove(file_path)
            logger.info(f"Removed temporary file: {path.name}")
            return True
        except OSError as err:
            logger.warning(f"Could not remove temporary file {file_path}: {err}")
            return False

    @staticmethod
    def wait_for_file_release(file, timeout=10):
        """
        Wait until the file is released (not locked anymore) or timeout is reached.
        """
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                with open(file, "ab"):
                    return True
            except PermissionError:
                time.sleep(0.5)
        return False

    @staticmethod
    def get_segment_duration(file_path: str, ffprobe_cmd: str = "ffprobe") -> float:
        """Probe the duration of a video segment in seconds."""
        try:
            probe = ffmpeg.probe(str(file_path), cmd=ffprobe_cmd)
            fmt = probe.get("format", {})
            duration = float(fmt.get("duration", 0) or 0)
            if duration > 0:
                return duration
            for stream in probe.get("streams", []):
                if stream.get("codec_type") == "video":
                    s_dur = float(stream.get("duration", 0) or 0)
                    if s_dur > 0:
                        return s_dur
        except Exception:
            pass
        return 0.0

    @staticmethod
    def validate_video_integrity(
        file_path: str, ffmpeg_path: str = None, min_expected_duration: float = None
    ) -> bool:
        """
        Validate that the converted MP4 file exists, has data,
        contains a valid playable video stream, and meets expected duration if provided.
        """
        try:
            path = Path(file_path)
            if not path.exists() or path.stat().st_size < 1024:
                return False

            cmd = "ffprobe"
            if ffmpeg_path:
                ffprobe_candidate = Path(ffmpeg_path).with_name(
                    "ffprobe.exe" if os.name == "nt" else "ffprobe"
                )
                if ffprobe_candidate.exists():
                    cmd = str(ffprobe_candidate)

            probe = ffmpeg.probe(str(path), cmd=cmd)
            streams = probe.get("streams", [])
            video_streams = [s for s in streams if s.get("codec_type") == "video"]
            if not video_streams:
                return False

            if min_expected_duration and min_expected_duration > 0:
                fmt = probe.get("format", {})
                duration = float(
                    fmt.get("duration", 0)
                    or (video_streams[0].get("duration", 0) if video_streams else 0)
                    or 0
                )
                # If output duration is significantly less than expected (>20% drop), reject copy
                if duration > 0 and duration < (min_expected_duration * 0.80):
                    logger.warning(
                        f"Converted video duration ({duration:.1f}s) is significantly less than expected total ({min_expected_duration:.1f}s)."
                    )
                    return False

            return True
        except Exception as e:
            logger.warning(f"Integrity check failed on {file_path}: {e}")
            return False

    @staticmethod
    def convert_segments_to_mp4(
        segment_files: list[str],
        output_file: str,
        bitrate: str = None,
        ffmpeg_path: str = None,
        keep_flv: bool = False,
        move_to_recycle_bin: bool = True,
    ) -> bool:
        """
        Convert one or multiple recorded FLV segments into a single cohesive MP4 file.
        Uses fast stream copy when possible, with automatic fallback to transcoding
        if stream parameters or timestamps differ across reconnections.
        """
        valid_segments = [
            s
            for s in segment_files
            if s and Path(s).exists() and os.path.getsize(s) > 0
        ]
        if not valid_segments:
            logger.error("No valid recorded segments found to convert.")
            return False

        cmd = ffmpeg_path or "ffmpeg"
        target_path = Path(output_file)

        # Ensure parent directory exists
        target_path.parent.mkdir(parents=True, exist_ok=True)

        # Wait for all segment files to be released
        for seg in valid_segments:
            if not VideoManagement.wait_for_file_release(seg):
                logger.error(
                    f"File {seg} is still locked after waiting. Skipping conversion."
                )
                return False

        ffprobe_cmd = "ffprobe"
        if ffmpeg_path:
            cand = Path(ffmpeg_path).with_name(
                "ffprobe.exe" if os.name == "nt" else "ffprobe"
            )
            if cand.exists():
                ffprobe_cmd = str(cand)

        # Build in-memory index of duration and file size for all valid segments
        segment_index = {}
        for seg in valid_segments:
            dur = VideoManagement.get_segment_duration(seg, ffprobe_cmd=ffprobe_cmd)
            size_mb = os.path.getsize(seg) / (1024 * 1024)
            segment_index[seg] = {
                "duration": dur,
                "size_mb": size_mb,
                "filename": Path(seg).name,
            }

        total_expected_duration = sum(
            info["duration"] for info in segment_index.values()
        )
        total_input_size_mb = sum(info["size_mb"] for info in segment_index.values())

        indexed_summary = ", ".join(
            f"[{info['filename']}: {info['duration']:.1f}s, {info['size_mb']:.1f}MB]"
            for info in segment_index.values()
        )
        logger.info(
            f"Indexed {len(valid_segments)} recorded video segment(s) "
            f"(Expected total duration: ~{total_expected_duration:.1f}s, total size: {total_input_size_mb:.1f}MB): {indexed_summary}"
        )

        conversion_succeeded = False

        if len(valid_segments) == 1:
            seg_file = valid_segments[0]
            logger.info(f"Converting {Path(seg_file).name} to MP4 format...")
            output_args = {
                "c": "copy",
                "y": "-y",
                "movflags": "+faststart",
                "avoid_negative_ts": "make_zero",
            }
            if bitrate:
                output_args["b:v"] = bitrate
                output_args["c:v"] = "libx264"
                output_args["c:a"] = "copy"
                del output_args["c"]

            copy_success = False
            try:
                ffmpeg.input(seg_file, fflags="+genpts+discardcorrupt").output(
                    str(target_path), **output_args
                ).run(quiet=True, cmd=cmd, capture_stderr=True)
                if VideoManagement.validate_video_integrity(
                    str(target_path),
                    ffmpeg_path=cmd,
                    min_expected_duration=total_expected_duration,
                ):
                    copy_success = True
                else:
                    logger.warning(
                        "Stream copy produced incomplete video track. Falling back to transcoding..."
                    )
            except ffmpeg.Error as e:
                err_text = (
                    e.stderr.decode(errors="replace")
                    if hasattr(e, "stderr") and e.stderr
                    else str(e)
                )
                logger.warning(
                    f"Stream copy failed ({err_text[:120]}...). "
                    "Retrying with video transcoding to prevent corruption..."
                )

            if not copy_success:
                try:
                    fallback_args = {
                        "c:v": "libx264",
                        "c:a": "aac",
                        "pix_fmt": "yuv420p",
                        "af": "aresample=async=1000",
                        "y": "-y",
                        "movflags": "+faststart",
                        "avoid_negative_ts": "make_zero",
                    }
                    if bitrate:
                        fallback_args["b:v"] = bitrate
                    ffmpeg.input(seg_file, fflags="+genpts+discardcorrupt").output(
                        str(target_path), **fallback_args
                    ).run(quiet=True, cmd=cmd, capture_stderr=True)
                    conversion_succeeded = True
                except ffmpeg.Error as transcode_err:
                    err_msg = (
                        transcode_err.stderr.decode(errors="replace")
                        if hasattr(transcode_err, "stderr") and transcode_err.stderr
                        else str(transcode_err)
                    )
                    logger.error(f"ffmpeg conversion failed: {err_msg}")
                    return False
            else:
                conversion_succeeded = True
        else:
            # Multiple segments (reconnected stream parts)
            logger.info(
                f"Merging {len(valid_segments)} recorded segments into {target_path.name}..."
            )
            manifest_file = (
                target_path.parent
                / f"concat_{target_path.stem}_{int(time.time() * 1000)}.txt"
            )
            try:
                with open(manifest_file, "w", encoding="utf-8") as f:
                    for seg in valid_segments:
                        safe_path = (
                            str(Path(seg).resolve())
                            .replace("\\", "/")
                            .replace("'", "'\\''")
                        )
                        f.write(f"file '{safe_path}'\n")

                output_args = {
                    "c": "copy",
                    "y": "-y",
                    "movflags": "+faststart",
                    "avoid_negative_ts": "make_zero",
                }
                if bitrate:
                    output_args["b:v"] = bitrate
                    output_args["c:v"] = "libx264"
                    output_args["c:a"] = "copy"
                    del output_args["c"]

                concat_copy_success = False
                try:
                    ffmpeg.input(
                        str(manifest_file),
                        f="concat",
                        safe=0,
                        fflags="+genpts+discardcorrupt",
                    ).output(str(target_path), **output_args).run(
                        quiet=True, cmd=cmd, capture_stderr=True
                    )
                    if VideoManagement.validate_video_integrity(
                        str(target_path),
                        ffmpeg_path=cmd,
                        min_expected_duration=total_expected_duration,
                    ):
                        concat_copy_success = True
                    else:
                        logger.warning(
                            "Concat copy produced incomplete video track or dropped segments. Falling back to transcoding..."
                        )
                except ffmpeg.Error as e:
                    err_text = (
                        e.stderr.decode(errors="replace")
                        if hasattr(e, "stderr") and e.stderr
                        else str(e)
                    )
                    logger.warning(
                        f"Concat stream copy failed ({err_text[:120]}...). "
                        "Retrying with video transcoding to merge all segments cleanly..."
                    )

                if not concat_copy_success:
                    try:
                        fallback_args = {
                            "c:v": "libx264",
                            "c:a": "aac",
                            "pix_fmt": "yuv420p",
                            "af": "aresample=async=1000",
                            "y": "-y",
                            "movflags": "+faststart",
                            "avoid_negative_ts": "make_zero",
                        }
                        if bitrate:
                            fallback_args["b:v"] = bitrate
                        ffmpeg.input(
                            str(manifest_file),
                            f="concat",
                            safe=0,
                            fflags="+genpts+discardcorrupt",
                        ).output(str(target_path), **fallback_args).run(
                            quiet=True, cmd=cmd, capture_stderr=True
                        )
                        conversion_succeeded = True
                    except ffmpeg.Error as transcode_err:
                        err_msg = (
                            transcode_err.stderr.decode(errors="replace")
                            if hasattr(transcode_err, "stderr") and transcode_err.stderr
                            else str(transcode_err)
                        )
                        logger.error(f"ffmpeg segment merge failed: {err_msg}")
                        return False
                else:
                    conversion_succeeded = True

            finally:
                if manifest_file.exists():
                    try:
                        manifest_file.unlink(missing_ok=True)
                    except OSError:
                        pass

        # Strict duration and file verification before any deletion
        if (
            not conversion_succeeded
            or not target_path.exists()
            or os.path.getsize(target_path) == 0
        ):
            logger.error(
                f"Merged output file {target_path} is missing or empty. "
                f"PRESERVING ALL {len(valid_segments)} RAW FLV FILES to prevent data loss."
            )
            return False

        actual_output_duration = VideoManagement.get_segment_duration(
            str(target_path), ffprobe_cmd=ffprobe_cmd
        )
        output_size_mb = os.path.getsize(target_path) / (1024 * 1024)

        duration_matched = True
        if total_expected_duration > 0:
            if actual_output_duration > 0:
                # Tolerance: duration is at least 95% of expected duration or within 2.0 seconds
                if (
                    actual_output_duration < (total_expected_duration * 0.95)
                    and (total_expected_duration - actual_output_duration) > 2.0
                ):
                    duration_matched = False
            else:
                # If output duration could not be determined via probe, check stream integrity
                if not VideoManagement.validate_video_integrity(
                    str(target_path), ffmpeg_path=cmd
                ):
                    duration_matched = False

        if not duration_matched:
            logger.error(
                f"DURATION MISMATCH: Merged MP4 duration ({actual_output_duration:.1f}s) "
                f"does not match indexed total duration ({total_expected_duration:.1f}s). "
                f"PRESERVING ALL {len(valid_segments)} RAW FLV FILES TO PREVENT DATA LOSS."
            )
            return False

        logger.info(
            f"Video verification PASSED: Merged MP4 duration: {actual_output_duration:.1f}s "
            f"({output_size_mb:.1f}MB) matches indexed total (~{total_expected_duration:.1f}s)."
        )

        if keep_flv:
            logger.info(
                "Raw FLV segments kept as requested in configuration (keep_flv=True)."
            )
        else:
            logger.info(
                f"Safely cleaning up {len(valid_segments)} raw FLV segment(s) after verified merge (keep_flv=False, move_to_recycle_bin={move_to_recycle_bin})..."
            )
            for seg in valid_segments:
                VideoManagement.remove_or_trash_file(
                    seg, move_to_recycle_bin=move_to_recycle_bin
                )

        logger.info(f"Finished converting {target_path.resolve()}\n")
        return True

    @staticmethod
    def convert_flv_to_mp4(
        file,
        bitrate=None,
        ffmpeg_path=None,
        keep_flv: bool = False,
        move_to_recycle_bin: bool = True,
    ):
        """
        Convert the video from flv format to mp4 format (backwards compatibility).
        """
        output_file = file.replace("_flv.mp4", ".mp4")
        if output_file == file:
            output_file = str(Path(file).with_suffix(".mp4"))
        return VideoManagement.convert_segments_to_mp4(
            [file],
            output_file,
            bitrate=bitrate,
            ffmpeg_path=ffmpeg_path,
            keep_flv=keep_flv,
            move_to_recycle_bin=move_to_recycle_bin,
        )
