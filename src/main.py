import sys
import os
import multiprocessing
from utils.enums import Mode

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def record_user(config):
    import time
    from core.tiktok_recorder import TikTokRecorder
    from utils.logger_manager import logger

    while True:
        try:
            TikTokRecorder(config).run()
            break
        except KeyboardInterrupt:
            logger.info("Quitting TikTok Live Recorder...")
            break
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
        bitrate=args.bitrate,
        ffmpeg_path=args.ffmpeg_path,
        keep_flv=args.keep_flv,
        move_to_recycle_bin=getattr(args, "move_to_recycle_bin", True),
        retry_delay=getattr(args, "retry_delay", 5),
        disk_space_alert_gb=getattr(args, "disk_space_alert_gb", 5),
    )


def run_recordings(args, mode, cookies):
    if isinstance(args.user, list):
        processes = []
        for user in args.user:
            config = _build_config(args, mode, cookies, user=user)
            p = multiprocessing.Process(target=record_user, args=(config,))
            p.start()
            processes.append(p)
        try:
            for p in processes:
                p.join()
        except KeyboardInterrupt:
            print("\n[!] Ctrl-C detected.")
            try:
                for p in processes:
                    p.join()
            except KeyboardInterrupt:
                print("\n[!] Forcefully terminating all processes.")
                for p in processes:
                    if p.is_alive():
                        p.terminate()
    else:
        config = _build_config(args, mode, cookies, user=args.user)
        record_user(config)


def main():
    from utils.args_handler import validate_and_parse_args
    from utils.utils import read_cookies
    from utils.logger_manager import logger
    from utils.custom_exceptions import TikTokRecorderError
    from utils.dependencies import check_ffmpeg
    from check_updates import check_updates

    try:
        # validate and parse command line arguments
        args, mode = validate_and_parse_args()

        # check ffmpeg binary (supports custom path via -ffmpeg-path)
        check_ffmpeg(args.ffmpeg_path or "ffmpeg")

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
