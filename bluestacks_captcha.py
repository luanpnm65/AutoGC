"""Watch a BlueStacks 5 (or LDPlayer 9) instance for Grow Castle's diamond challenge."""

import argparse
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from queue import Empty, Full, Queue
from shutil import copyfile
import struct
import subprocess
from tempfile import NamedTemporaryFile
from threading import Event, Thread
from time import monotonic, sleep
from uuid import uuid4

import numpy as np
from PIL import Image

from captcha import (
    BOARD,
    BOARD_SIZE,
    CENTER,
    Detector,
    VIEWPORT,
    board_image,
    format_result,
    gem_position,
    upright_layout,
)
from emulator import (
    EmulatorTarget,
    adb_run,
    enable_dpi_awareness,
    ensure_adb_connected,
    foreground_activity,
    format_instances,
    grab_game_window,
    resolve_target,
    run,
    target_window_handle,
)
from windows_video import read_video


START_POINT = (925, 580)
CAPTURE_FPS = 36
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class _RecordingUnavailableError(RuntimeError):
    """Raised when ADB screenrecord fails before CAPTCHA Start is tapped."""


def capture_frames(hwnd, frames, stop, start, label="Emulator"):
    try:
        while not stop.is_set():
            timestamp = monotonic() - start
            try:
                import ctypes as ct

                if not ct.windll.user32.IsWindow(hwnd):
                    raise RuntimeError(f"{label}'s game window closed.")
            except AttributeError:
                pass
            with grab_game_window(hwnd) as image:
                frames.put_nowait((timestamp, board_image(image)))
            # Leave room for the emulator to render on fast capture hosts.
            stop.wait(max(0, start + timestamp + 1 / CAPTURE_FPS - monotonic()))
    except Full:
        stop.set()
    except (OSError, RuntimeError, ValueError) as exc:
        try:
            frames.put_nowait(exc)
        except Full:
            stop.set()


def game_frame(adb, serial):
    if not foreground_activity(adb, serial):
        raise RuntimeError("Grow Castle must be the foreground app on the selected ADB device.")

    screenshot = adb_run(adb, serial, "exec-out", "screencap", "-p")
    with Image.open(BytesIO(screenshot)) as screen:
        return screen.convert("RGB")


def matching_game_frame(adb, serial, captured_board):
    frame = game_frame(adb, serial)
    board = board_image(frame)
    gray = np.asarray(board.convert("L"), dtype=np.float32)
    captured = np.asarray(captured_board.convert("L"), dtype=np.float32)
    if not upright_layout(gray) or np.mean(np.abs(gray - captured)) > 5:
        raise RuntimeError("The selected device no longer shows the same cup layout.")
    return frame, gem_position(board)


def tap_point(adb, serial, frame, point):
    x = round(point[0] * frame.width / VIEWPORT[0])
    y = round(point[1] * frame.height / VIEWPORT[1])
    adb_run(adb, serial, "shell", "input", "tap", str(x), str(y))
    return x, y


def tap_cup(adb, serial, result, captured_board):
    frame, gem = matching_game_frame(adb, serial, captured_board)
    if gem is not None:
        raise RuntimeError("The cups are no longer ready for a selection.")
    x, y = tap_point(adb, serial, frame, result.coordinate)
    print(f"Sent one tap to {serial} at ({x}, {y}).", flush=True)


def verify_start(frame, gem, start_screen):
    if gem is None or np.linalg.norm(gem - CENTER) >= 11 or not start_screen(frame):
        raise RuntimeError("The CAPTCHA Start button or centered diamond could not be verified.")


def keep_window_round(frames):
    try:
        logs = Path(__file__).with_name("logs")
        logs.mkdir(exist_ok=True)
        saved = logs / f"growcastle-captcha-window-{uuid4().hex}.npz"
        np.savez_compressed(
            saved,
            times=[time for time, _ in frames],
            boards=np.stack([np.asarray(board.convert("RGB")) for _, board in frames]),
        )
        print(f"CAPTCHA: kept unselected window round at {saved}", flush=True)
    except OSError as exc:
        print(f"CAPTCHA: could not keep the window recording: {exc}", flush=True)


def solve_from_adb_recording(adb, serial, start_screen):
    # Record inside Android, where occluding Windows apps cannot hide the game.
    initial = game_frame(adb, serial)
    initial_board = board_image(initial)
    verify_start(initial, gem_position(initial_board), start_screen)
    remote = f"/data/local/tmp/growcastle-captcha-{uuid4().hex}.mp4"
    recording = subprocess.Popen(
        [str(adb), "-s", serial, "shell", "screenrecord", "--size", "960x540",
         "--time-limit", "7", remote],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        creationflags=_NO_WINDOW,
    )
    local = None
    selected = False
    tapped_start = False
    try:
        deadline = monotonic() + 2
        while recording.poll() is None and monotonic() < deadline:
            try:
                size = adb_run(adb, serial, "shell", "stat", "-c", "%s", remote, timeout=2)
                if size.strip().isdigit() and int(size) > 0:
                    break
            except subprocess.CalledProcessError:
                pass
            sleep(0.1)
        else:
            raise _RecordingUnavailableError("ADB screen recording did not start.")

        frame, gem = matching_game_frame(adb, serial, initial_board)
        verify_start(frame, gem, start_screen)
        if recording.poll() is not None:
            raise _RecordingUnavailableError("ADB screen recording ended before CAPTCHA Start.")
        tap_point(adb, serial, frame, START_POINT)
        tapped_start = True
        print("CAPTCHA: started during ADB screen recording.", flush=True)
        _, stderr = recording.communicate(timeout=9)
        if recording.returncode:
            raise RuntimeError(stderr.decode(errors="replace").strip() or "ADB screen recording failed.")

        data = adb_run(adb, serial, "exec-out", "cat", remote)
        with NamedTemporaryFile(suffix=".mp4", delete=False) as target:
            local = Path(target.name)
            target.write(data)
        detector = Detector(sample_interval=0.017)
        video = read_video(local)
        try:
            for _, time, image in video:
                board = board_image(image)
                result = detector.feed_board(time, board)
                if result is not None:
                    print(f"Round 1: {format_result(result)}", flush=True)
                    if result.coordinate is None:
                        return False
                    tap_cup(adb, serial, result, board)
                    selected = True
                    return True
        finally:
            video.close()
        return False
    finally:
        if recording.poll() is None:
            recording.kill()
            recording.communicate()
        if local is not None:
            if tapped_start and not selected:
                try:
                    logs = Path(__file__).with_name("logs")
                    logs.mkdir(exist_ok=True)
                    saved = logs / Path(remote).name
                    copyfile(local, saved)
                    print(f"CAPTCHA: kept unselected round at {saved}", flush=True)
                except OSError as exc:
                    print(f"CAPTCHA: could not keep the round recording: {exc}", flush=True)
            local.unlink(missing_ok=True)
        try:
            adb_run(adb, serial, "shell", "rm", "-f", remote, timeout=3)
        except (OSError, subprocess.SubprocessError):
            pass


def parse_raw_screencap_header(raw: bytes) -> tuple[int, int, int, int]:
    if len(raw) < 16:
        raise RuntimeError("Raw screencap output is truncated.")
    width, height, fmt = struct.unpack_from("<III", raw, 0)
    if width < 320 or height < 180 or abs((width / height) / (16 / 9) - 1) > 0.03:
        raise RuntimeError(f"Expected a 16:9 game display, got {width}x{height}.")
    if fmt not in (1, 2, 5):
        raise RuntimeError(f"Unsupported raw screencap pixel format: {fmt}.")
    pixel_bytes = width * height * 4
    header_bytes = len(raw) - pixel_bytes
    if not 12 <= header_bytes <= 32:
        raise RuntimeError("Unexpected raw screencap frame size.")
    return width, height, fmt, header_bytes


def raw_screencap_to_image(buf: bytes | bytearray | memoryview, width: int, height: int, fmt: int, header_bytes: int):
    pixels = np.frombuffer(buf, dtype=np.uint8, offset=header_bytes, count=width * height * 4)
    rgba = pixels.reshape((height, width, 4))
    rgb = rgba[:, :, 2::-1] if fmt == 5 else rgba[:, :, :3]
    return Image.fromarray(np.ascontiguousarray(rgb), "RGB")


def raw_screencap_to_board(buf: bytes | bytearray | memoryview, width: int, height: int, fmt: int, header_bytes: int):
    pixels = np.frombuffer(buf, dtype=np.uint8, offset=header_bytes, count=width * height * 4)
    rgba = pixels.reshape((height, width, 4))
    fx0 = BOARD[0] * width / VIEWPORT[0]
    fy0 = BOARD[1] * height / VIEWPORT[1]
    fx1 = BOARD[2] * width / VIEWPORT[0]
    fy1 = BOARD[3] * height / VIEWPORT[1]
    ix0 = max(0, int(fx0) - 1)
    iy0 = max(0, int(fy0) - 1)
    ix1 = min(width, int(fx1) + 2)
    iy1 = min(height, int(fy1) + 2)
    patch = rgba[iy0:iy1, ix0:ix1, 2::-1] if fmt == 5 else rgba[iy0:iy1, ix0:ix1, :3]
    crop_img = Image.fromarray(np.ascontiguousarray(patch), "RGB")
    try:
        return crop_img.resize(
            BOARD_SIZE,
            Image.Resampling.BILINEAR,
            box=(fx0 - ix0, fy0 - iy0, fx1 - ix0, fy1 - iy0),
        )
    finally:
        crop_img.close()


def _read_exact(pipe, buf: bytearray) -> bool:
    view = memoryview(buf)
    offset = 0
    total = len(buf)
    while offset < total:
        chunk = pipe.readinto(view[offset:])
        if not chunk:
            return False
        offset += chunk
    return True


def _stream_raw_boards(pipe, frame_size, expected_header, converter, out_queue, stop, start):
    buf = bytearray(frame_size)
    try:
        while not stop.is_set():
            if not _read_exact(pipe, buf):
                break
            if struct.unpack_from("<III", buf, 0) != expected_header:
                raise RuntimeError("Raw screencap stream lost frame alignment.")
            timestamp = monotonic() - start
            board = converter(buf)
            try:
                out_queue.put_nowait((timestamp, board))
            except Full:
                # Drop oldest pre-start frame or signal overload.
                stop.set()
                break
    except (OSError, RuntimeError, ValueError) as exc:
        try:
            out_queue.put_nowait(exc)
        except Full:
            stop.set()


def solve_from_adb_screencap_stream(adb, serial, start_screen):
    if not foreground_activity(adb, serial):
        raise RuntimeError("Grow Castle must be the foreground app on the selected ADB device.")
    probe = adb_run(adb, serial, "exec-out", "screencap", timeout=6)
    width, height, fmt, header_bytes = parse_raw_screencap_header(probe)
    initial_frame = raw_screencap_to_image(probe, width, height, fmt, header_bytes)
    initial_board = board_image(initial_frame)
    verify_start(initial_frame, gem_position(initial_board), start_screen)

    frame_size = header_bytes + width * height * 4
    expected_header = (width, height, fmt)
    stream = subprocess.Popen(
        [str(adb), "-s", serial, "exec-out", "while :; do screencap; done"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        creationflags=_NO_WINDOW,
    )
    frames: Queue = Queue(maxsize=CAPTURE_FPS * 10)
    stop = Event()
    start = monotonic()
    converter = lambda b: raw_screencap_to_board(b, width, height, fmt, header_bytes)
    reader = Thread(
        target=_stream_raw_boards,
        args=(stream.stdout, frame_size, expected_header, converter, frames, stop, start),
        daemon=True,
    )
    reader.start()
    started = False
    selected = False
    round_frames = []
    detector = Detector(sample_interval=0.025)
    try:
        warmup_times = []
        last_board = None
        warmup_deadline = monotonic() + 2.5
        while len(warmup_times) < 3 and monotonic() < warmup_deadline:
            try:
                item = frames.get(timeout=0.4)
            except Empty:
                continue
            if isinstance(item, Exception):
                raise item
            ts, board = item
            warmup_times.append(ts)
            last_board = board
            detector.feed_board(ts, board)

        if len(warmup_times) < 3 or last_board is None:
            raise RuntimeError("ADB raw screencap stream did not produce frames.")
        avg_dt = (warmup_times[-1] - warmup_times[0]) / (len(warmup_times) - 1)
        if avg_dt > 0.085:
            raise RuntimeError(
                f"ADB raw screencap stream is too slow ({1 / avg_dt:.1f} FPS); "
                "keep the BlueStacks window visible on screen for CAPTCHA."
            )
        if detector.reference is None:
            raise RuntimeError("Centered diamond was not observed in raw screencap stream.")

        check_frame, gem = matching_game_frame(adb, serial, last_board)
        verify_start(check_frame, gem, start_screen)
        tap_point(adb, serial, check_frame, START_POINT)
        started = True
        round_frames.append((warmup_times[-1], last_board))
        print("CAPTCHA: started during ADB raw screencap stream.", flush=True)

        deadline = monotonic() + 6.5
        while monotonic() < deadline:
            if stop.is_set():
                break
            try:
                item = frames.get(timeout=0.15)
            except Empty:
                continue
            if isinstance(item, Exception):
                raise item
            timestamp, board = item
            if len(round_frames) < CAPTURE_FPS * 7:
                round_frames.append((timestamp, board))
            result = detector.feed_board(timestamp, board)
            if result is not None:
                print(f"Round 1: {format_result(result)}", flush=True)
                if result.coordinate is None:
                    return False
                if monotonic() - start - result.end_time > 4:
                    raise RuntimeError("Prediction is stale. Run the detector again.")
                tap_cup(adb, serial, result, board)
                selected = True
                return True
        return False
    finally:
        stop.set()
        if stream.poll() is None:
            stream.kill()
            stream.communicate()
        reader.join(timeout=1)
        if started and round_frames and not selected:
            keep_window_round(round_frames)


def solve_from_adb(adb, serial, start_screen):
    try:
        return solve_from_adb_recording(adb, serial, start_screen)
    except _RecordingUnavailableError as exc:
        print(f"CAPTCHA: {exc} Falling back to raw ADB screencap stream.", flush=True)
        return solve_from_adb_screencap_stream(adb, serial, start_screen)


def watch_target(target: EmulatorTarget, duration: float, tap: bool, start_screen=None) -> bool:
    if start_screen is not None and not tap:
        raise ValueError("Automatic CAPTCHA start requires tap mode.")
    enable_dpi_awareness()
    if tap:
        connected_serial = ensure_adb_connected(
            target.adb,
            target.serial,
            conf=target.conf,
            instance_key=target.instance if target.emulator == "bluestacks" else None,
            allow_port_refresh=(target.emulator == "bluestacks"),
        )
        target = replace(target, serial=connected_serial)

    try:
        hwnd = target_window_handle(target)
    except RuntimeError:
        if start_screen is not None and (not duration or duration >= 12):
            print("CAPTCHA: window capture unavailable; using ADB capture.", flush=True)
            return solve_from_adb(target.adb, target.serial, start_screen)
        raise

    detector = Detector(sample_interval=0.025 if start_screen is not None else 0.043)
    frames = Queue(maxsize=CAPTURE_FPS * 5)
    stop = Event()
    start = monotonic()
    emu_label = "LDPlayer" if target.emulator == "ldplayer" else "BlueStacks 5"
    capture = Thread(
        target=capture_frames,
        args=(hwnd, frames, stop, start, emu_label),
        daemon=True,
    )
    print(
        f"Watching {emu_label} '{target.display_name}' ({target.instance}) "
        f"[{'one tap enabled' if tap else 'preview only'}].",
        flush=True,
    )
    capture.start()
    rounds = 0
    started = False
    selected = False
    round_frames = []
    try:
        while not duration or monotonic() - start < duration:
            if start_screen is not None and not started and monotonic() - start >= 1.25:
                break
            if stop.is_set():
                raise RuntimeError(f"Capture is ahead of analysis. Restart {emu_label} at 1280x720.")
            try:
                item = frames.get(timeout=0.1)
            except Empty:
                continue
            if isinstance(item, Exception):
                if start_screen is not None and not started:
                    break
                raise item
            timestamp, board = item
            if started and len(round_frames) < CAPTURE_FPS * 7:
                round_frames.append((timestamp, board))
            result = detector.feed_board(timestamp, board)
            if start_screen is not None and not started and detector.reference is not None:
                frame, gem = matching_game_frame(target.adb, target.serial, board)
                verify_start(frame, gem, start_screen)
                tap_point(target.adb, target.serial, frame, START_POINT)
                started = True
                round_frames.append((timestamp, board))
                print("CAPTCHA: started after observing the centered diamond.", flush=True)
            if result is not None:
                rounds += 1
                print(f"Round {rounds}: {format_result(result)}", flush=True)
                if tap and result.coordinate is not None:
                    if monotonic() - start - result.end_time > 4:
                        raise RuntimeError("Prediction is stale. Run the detector again.")
                    tap_cup(target.adb, target.serial, result, board)
                    selected = True
                    return True
                if start_screen is not None:
                    return False
    finally:
        stop.set()
        capture.join(timeout=2)
        if round_frames and not selected:
            keep_window_round(round_frames)
    if start_screen is not None and not started and (not duration or duration >= 12):
        print("CAPTCHA: window capture unavailable; using ADB capture.", flush=True)
        return solve_from_adb(target.adb, target.serial, start_screen)
    print(f"Stopped after {rounds} completed challenge(s).", flush=True)
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--emulator", choices=("bluestacks", "ldplayer"),
                        help="target emulator (default: bluestacks, or ldplayer when --ldconsole is given)")
    parser.add_argument("--instance", help="BlueStacks 5 instance key or window title (e.g. Pie64, Pie64_1)")
    parser.add_argument("--index", type=int, help="emulator instance index (0, 1, 2, ...)")
    parser.add_argument("--serial", help="ADB serial override (e.g. 127.0.0.1:5555 or emulator-5554)")
    parser.add_argument("--adb", type=Path, help="path to HD-Adb.exe or adb.exe (auto-detected by default)")
    parser.add_argument("--conf", type=Path, help="path to bluestacks.conf (auto-detected by default)")
    parser.add_argument("--ldconsole", type=Path, help="path to ldconsole.exe (for LDPlayer 9)")
    parser.add_argument("--list", action="store_true", help="list detected emulator instances and exit")
    parser.add_argument("--seconds", type=float, default=0, help="stop after N seconds (default 0, wait)")
    parser.add_argument("--tap", action="store_true", help="send one verified ADB tap and exit")
    args = parser.parse_args()
    if (args.index is not None and args.index < 0) or args.seconds < 0:
        parser.error("--index and --seconds must be nonnegative")

    try:
        if args.list:
            emu = args.emulator or ("ldplayer" if args.ldconsole else "bluestacks")
            print(format_instances(emulator=emu, adb=args.adb, conf=args.conf, ldconsole=args.ldconsole))
            return
        target = resolve_target(
            emulator=args.emulator,
            instance=args.instance,
            index=args.index,
            serial=args.serial,
            adb=args.adb,
            conf=args.conf,
            ldconsole=args.ldconsole,
        )
        watch_target(target, args.seconds, args.tap)
    except KeyboardInterrupt:
        pass
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.decode(errors="replace").strip() or str(exc)
        parser.exit(1, f"{detail}\n")
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
