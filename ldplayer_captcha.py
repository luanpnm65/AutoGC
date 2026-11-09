"""Watch one LDPlayer 9 instance for Grow Castle's diamond challenge."""

import argparse
from pathlib import Path
import subprocess

from bluestacks_captcha import CAPTURE_FPS, START_POINT, watch_target
from emulator import EmulatorTarget, grab_game_window, ldplayer_window_handle as window_handle, run


def watch(console, index, serial, duration, tap, start_screen=None):
    console = Path(console)
    target = EmulatorTarget(
        emulator="ldplayer",
        adb=console.with_name("adb.exe"),
        serial=serial,
        instance=str(index),
        display_name=f"LDPlayer {index}",
        index=index,
        ldconsole=console,
    )
    return watch_target(target, duration, tap, start_screen=start_screen)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ldconsole", type=Path, default=Path(r"D:\LDPlayer\LDPlayer9\ldconsole.exe"),
                        help="path to ldconsole.exe (adb.exe must be beside it for --tap)")
    parser.add_argument("--index", type=int, default=0, help="LDPlayer instance index (default 0)")
    parser.add_argument("--serial", help="ADB serial (default emulator-5554 for instance 0)")
    parser.add_argument("--seconds", type=float, default=0, help="stop after N seconds (default 0, wait)")
    parser.add_argument("--tap", action="store_true", help="send one verified ADB tap and exit")
    args = parser.parse_args()
    if args.index < 0 or args.seconds < 0:
        parser.error("--index and --seconds must be nonnegative")
    serial = args.serial or f"emulator-{5554 + 2 * args.index}"
    try:
        watch(args.ldconsole, args.index, serial, args.seconds, args.tap)
    except KeyboardInterrupt:
        pass
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.decode(errors="replace").strip() or str(exc)
        parser.exit(1, f"{detail}\n")
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
