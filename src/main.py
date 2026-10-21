import multiprocessing
import os
import sys
import time

from utils.enums import Mode

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def record_user(config):
    import time

    from core.tiktok_recorder import TikTokRecorder
    from utils.logger_manager import logger

    ctrl_c_count = 0
    while True:
        try:
            TikTokRecorder(config).run()
            break
        except KeyboardInterrupt:
            ctrl_c_count += 1
            if ctrl_c_count >= 2 or config.mode == Mode.MANUAL:
                logger.info("Quitting TikTok Live Recorder...")
                break
            else:
                logger.info(
                    f"Ctrl-C detected for @{config.user or 'user'}. Press Ctrl-C again to quit."
                )
                time.sleep(1)
        except Exception as e:
            if config.mode == Mode.AUTOMATIC:
                logger.error(
                    f"Unexpected error in automatic mode: {e}. Retrying in {config.retry_delay}s...",
                    exc_info=True,
                )
                time.sleep(config.retry_delay)
            else:
                logger.error(f"{e}", exc_info=True)
                break


def _build_config(args, mode, cookies, user=None):
    from utils.recorder_config import RecorderConfig

    tracked_users = getattr(args, "tracked_users", None)
    if user and tracked_users:
        matched_tu = [
            tu
            for tu in tracked_users
            if tu.username == user or tu.sec_uid == user or tu.user_id == user
        ]
        tracked_users = matched_tu if matched_tu else None

    return RecorderConfig(
        url=args.url,
        user=user,
        users=None if user else (args.user if isinstance(args.user, list) else None),
        tracked_users=tracked_users,
        room_id=args.room_id,
        mode=mode,
        automatic_interval=args.automatic_interval,
        cookies=cookies,
        proxy=args.proxy,
        output=args.output,
        duration=args.duration,
        use_telegram=args.telegram,
        use_youtube=getattr(args, "youtube", False),
        playlist=getattr(args, "playlist", None),
        bitrate=args.bitrate,
        ffmpeg_path=args.ffmpeg_path,
        keep_flv=args.keep_flv,
        move_to_recycle_bin=getattr(args, "move_to_recycle_bin", True),
        retry_delay=getattr(args, "retry_delay", 5),
        disk_space_alert_gb=getattr(args, "disk_space_alert_gb", 5),
        recording_strategy=getattr(args, "recording_strategy", "requests"),
        yt_dlp_path=getattr(args, "yt_dlp_path", None),
        purge_after_upload=getattr(args, "purge_after_upload", False),
        split_video=getattr(args, "split_video", True),
        split_size_mb=getattr(args, "split_size_mb", 1950),
    )


def run_recordings(args, mode, cookies):
    if isinstance(args.user, list):
        processes = []
        for user in args.user:
            config = _build_config(args, mode, cookies, user=user)
            p = multiprocessing.Process(target=record_user, args=(config,))
            p.start()
            processes.append(p)
        ctrl_c_times = []
        while any(p.is_alive() for p in processes):
            try:
                for p in processes:
                    if p.is_alive():
                        p.join(timeout=1.0)
            except KeyboardInterrupt:
                now = time.time()
                ctrl_c_times.append(now)
                if len(ctrl_c_times) >= 2 and (
                    ctrl_c_times[-1] - ctrl_c_times[-2] <= 10.0
                ):
                    print(
                        "\n[!] Ctrl-C detected again. Forcefully terminating all processes."
                    )
                    for p in processes:
                        if p.is_alive():
                            p.terminate()
                    break
                else:
                    print(
                        "\n[!] Ctrl-C detected: stopping active recording(s) and uploading. "
                        "Press Ctrl-C again within 10s to force quit."
                    )
    else:
        config = _build_config(args, mode, cookies, user=args.user)
        record_user(config)


def main():
    from check_updates import check_updates
    from utils.args_handler import validate_and_parse_args
    from utils.custom_exceptions import TikTokRecorderError
    from utils.dependencies import check_ffmpeg, check_yt_dlp
    from utils.logger_manager import logger
    from utils.utils import read_cookies

    try:
        # validate and parse command line arguments
        args, mode = validate_and_parse_args()

        strat = getattr(args, "recording_strategy", "requests").lower()
        logger.info(
            f"Active recording strategy: [{strat}] (available: requests, yt-dlp)\n"
        )

        # check ffmpeg binary (supports custom path via -ffmpeg-path)
        check_ffmpeg(args.ffmpeg_path or "ffmpeg")

        # check yt-dlp binary if yt-dlp strategy is chosen
        if getattr(args, "recording_strategy", "requests") == "yt-dlp":
            check_yt_dlp(args.yt_dlp_path or "yt-dlp")

        # Auto-recovery for interrupted or crashed recordings from previous sessions (runs in background)
        startup_time = time.time()

        def _run_background_recovery():
            try:
                from pathlib import Path

                from utils.video_management import VideoManagement

                dirs_to_scan = set()
                if args.output:
                    dirs_to_scan.add(args.output)
                if Path("output").is_dir():
                    dirs_to_scan.add("output")
                if not dirs_to_scan:
                    dirs_to_scan.add(".")

                for scan_dir in dirs_to_scan:
                    VideoManagement.recover_interrupted_recordings(
                        scan_dir,
                        ffmpeg_path=args.ffmpeg_path or "ffmpeg",
                        max_mtime=startup_time,
                        keep_flv=getattr(args, "keep_flv", False),
                        move_to_recycle_bin=getattr(args, "move_to_recycle_bin", True),
                    )
            except Exception as e:
                logger.warning(
                    f"[Auto-Recovery] Background recovery check encountered an issue: {e}"
                )

        import threading

        recovery_thread = threading.Thread(
            target=_run_background_recovery,
            name="AutoRecoveryThread",
            daemon=True,
        )
        recovery_thread.start()

        # check for updates
        if args.update_check is True:
            logger.info("Checking for updates...\n")
            if check_updates():
                exit()
        else:
            logger.info("Skipped update check\n")

        # read cookies from the config file
        cookies = read_cookies()

        from notify.notifier import Notifier

        notifier = Notifier()
        notifier.notify("app_started", mode=args.mode, interval=args.automatic_interval)

        # run the recordings based on the parsed arguments
        run_recordings(args, mode, cookies)

    except KeyboardInterrupt:
        logger.info("Quitting TikTok Live Recorder...")
        import os

        os._exit(0)

    except TikTokRecorderError as ex:
        logger.error(f"Application Error: {ex}")
        try:
            from notify.notifier import Notifier

            Notifier().notify("app_error", error=str(ex))
        except Exception:
            pass

    except Exception as ex:
        logger.critical(f"Generic Error: {ex}", exc_info=True)
        try:
            from notify.notifier import Notifier

            Notifier().notify("app_error", error=str(ex))
        except Exception:
            pass


if __name__ == "__main__":
    try:
        # print the banner
        from utils.utils import banner

        banner()

        # check and install dependencies
        from utils.dependencies import check_and_install_dependencies

        check_and_install_dependencies()

        # set up signal handling for graceful shutdown
        multiprocessing.freeze_support()

        # run
        main()
    except KeyboardInterrupt:
        print("\n[*] Quitting TikTok Live Recorder...")
        import os

        os._exit(0)
