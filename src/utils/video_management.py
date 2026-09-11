import os
import time
from pathlib import Path

import ffmpeg

from utils.logger_manager import logger


class VideoManagement:
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
    def convert_segments_to_mp4(
        segment_files: list[str],
        output_file: str,
        bitrate: str = None,
        ffmpeg_path: str = None,
        keep_flv: bool = False,
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

        if len(valid_segments) == 1:
            seg_file = valid_segments[0]
            logger.info(f"Converting {Path(seg_file).name} to MP4 format...")
            output_args = {
                "c": "copy",
                "y": "-y",
                "movflags": "+faststart",
            }
            if bitrate:
                output_args["b:v"] = bitrate
                output_args["c:v"] = "libx264"
                output_args["c:a"] = "copy"
                del output_args["c"]

            try:
                ffmpeg.input(seg_file).output(str(target_path), **output_args).run(
                    quiet=True, cmd=cmd, capture_stderr=True
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
                try:
                    fallback_args = {
                        "c:v": "libx264",
                        "c:a": "aac",
                        "y": "-y",
                        "movflags": "+faststart",
                    }
                    if bitrate:
                        fallback_args["b:v"] = bitrate
                    ffmpeg.input(seg_file).output(
                        str(target_path), **fallback_args
                    ).run(quiet=True, cmd=cmd, capture_stderr=True)
                except ffmpeg.Error as transcode_err:
                    err_msg = (
                        transcode_err.stderr.decode(errors="replace")
                        if hasattr(transcode_err, "stderr") and transcode_err.stderr
                        else str(transcode_err)
                    )
                    logger.error(f"ffmpeg conversion failed: {err_msg}")
                    return False

            if target_path.exists() and os.path.getsize(target_path) > 0:
                if keep_flv:
                    logger.info(f"Raw FLV file kept: {Path(seg_file).resolve()}")
                else:
                    try:
                        os.remove(seg_file)
                    except OSError as err:
                        logger.warning(
                            f"Could not remove temporary segment {seg_file}: {err}"
                        )
                logger.info(f"Finished converting {target_path.resolve()}\n")
                return True
            return False

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
            }
            if bitrate:
                output_args["b:v"] = bitrate
                output_args["c:v"] = "libx264"
                output_args["c:a"] = "copy"
                del output_args["c"]

            try:
                ffmpeg.input(str(manifest_file), f="concat", safe=0).output(
                    str(target_path), **output_args
                ).run(quiet=True, cmd=cmd, capture_stderr=True)
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
                try:
                    fallback_args = {
                        "c:v": "libx264",
                        "c:a": "aac",
                        "y": "-y",
                        "movflags": "+faststart",
                    }
                    if bitrate:
                        fallback_args["b:v"] = bitrate
                    ffmpeg.input(str(manifest_file), f="concat", safe=0).output(
                        str(target_path), **fallback_args
                    ).run(quiet=True, cmd=cmd, capture_stderr=True)
                except ffmpeg.Error as transcode_err:
                    err_msg = (
                        transcode_err.stderr.decode(errors="replace")
                        if hasattr(transcode_err, "stderr") and transcode_err.stderr
                        else str(transcode_err)
                    )
                    logger.error(f"ffmpeg segment merge failed: {err_msg}")
                    return False

            if target_path.exists() and os.path.getsize(target_path) > 0:
                if keep_flv:
                    logger.info("Raw FLV segments kept as requested.")
                else:
                    for seg in valid_segments:
                        try:
                            os.remove(seg)
                        except OSError as err:
                            logger.warning(
                                f"Could not remove temporary segment {seg}: {err}"
                            )
                logger.info(f"Finished converting {target_path.resolve()}\n")
                return True
            return False

        finally:
            if manifest_file.exists():
                try:
                    manifest_file.unlink(missing_ok=True)
                except OSError:
                    pass

    @staticmethod
    def convert_flv_to_mp4(
        file, bitrate=None, ffmpeg_path=None, keep_flv: bool = False
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
        )
