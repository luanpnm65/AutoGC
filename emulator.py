"""Discover, connect, and capture BlueStacks 5 and LDPlayer 9 instances."""

import ctypes as ct
from dataclasses import dataclass
from pathlib import Path
import random
import re
import shutil
import subprocess
import sys
from time import sleep


_SYS_RNG = random.SystemRandom()


_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_DEFAULT_LDCONSOLE = Path(r"D:\LDPlayer\LDPlayer9\ldconsole.exe")
_BLUESTACKS_REG_KEYS = (
    r"SOFTWARE\BlueStacks_nxt",
    r"SOFTWARE\BlueStacks_msi5",
)
_VIEWPORT_CLASSES = ("BlueStacksApp", "RenderWindow", "subWin", "TheRender")
_INPUT_CLASSES = ("plrNativeInputWindow",)
_VIEWPORT_TITLES = ("BlueStacks Android PluginAndroid", "_ctl.Window", "HD-Player", "TheRender")
_WINDOW_FOCUS_RE = re.compile(
    r"mCurrentFocus=Window\{[^\r\n}]*?[\s{]([A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*)/([^\s}]+)"
)
_CURRENT_FOCUS_LINE_RE = re.compile(r"mCurrentFocus=(.+)")
_FOCUSED_APP_WINDOW_RE = re.compile(
    r"mFocusedApp=[^\r\n]*?[\s{]([A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*)/([^\s}]+)"
)
AD_OVERLAY_PACKAGES = frozenset({
    "com.android.vending",
    "com.google.android.finsky",
    "com.android.chrome",
    "com.android.browser",
    "com.sec.android.app.sbrowser",
    "org.mozilla.firefox",
    "com.microsoft.emmx",
    "android",
})
_AD_ACTIVITY_HINTS = (
    "com.google.android.gms.ads",
    "adactivity",
    "adunit",
    "adview",
    "applovin",
    "unity3d.services.ads",
    "ironsource",
    "vungle",
    "mbridge",
    "bytedance",
    "facebook.ads",
    "chartboost",
    "inmobi",
    "fyber",
    "digitalturbine",
    "adcolony",
    "tapjoy",
    "reward",
    "interstitial",
    "fullscreen",
)
_CONF_LINE_RE = re.compile(r'^\s*([A-Za-z0-9_.-]+)\s*=\s*"?(.*?)"?\s*$')
_INSTANCE_KEY_RE = re.compile(r"^bst\.instance\.([A-Za-z0-9_]+)\.(.+)$")
_INSTANCE_SUFFIX_RE = re.compile(r"^(.+?)(?:_(\d+))?$")
_CMDLINE_INSTANCE_RE = re.compile(r'--instance(?:\s+|=)(?:"([^"]+)"|([A-Za-z0-9_]+))', re.IGNORECASE)
_TCP_SERIAL_RE = re.compile(r"^(?:127\.0\.0\.1|localhost|\d{1,3}(?:\.\d{1,3}){3}):(\d+)$", re.IGNORECASE)


@dataclass(frozen=True)
class BlueStacksInstance:
    key: str
    display_name: str
    index: int
    suffix: int | None
    adb_port: int | None
    adb_enabled: bool

    @property
    def serial(self) -> str | None:
        return f"127.0.0.1:{self.adb_port}" if self.adb_port else None


@dataclass(frozen=True)
class RunningWindow:
    pid: int
    root_hwnd: int
    viewport_hwnd: int
    title: str
    viewport_size: tuple[int, int]
    instance_key: str | None = None
    exe_path: Path | None = None
    minimized: bool = False


@dataclass(frozen=True)
class EmulatorTarget:
    emulator: str
    adb: Path
    serial: str
    instance: str
    display_name: str
    index: int = 0
    conf: Path | None = None
    ldconsole: Path | None = None


def run(executable, *arguments, timeout=8):
    return subprocess.run(
        [str(executable), *(str(arg) for arg in arguments)],
        capture_output=True,
        check=True,
        timeout=timeout,
        creationflags=_NO_WINDOW,
    ).stdout


def is_tcp_serial(serial: str) -> bool:
    return bool(_TCP_SERIAL_RE.match(serial or ""))


def _positive_port(value: str | None) -> int | None:
    if value and value.strip().isdigit():
        port = int(value.strip())
        if 1 <= port <= 65535:
            return port
    return None


def parse_bluestacks_conf(path: Path, running_keys=()) -> list[BlueStacksInstance]:
    path = Path(path)
    if not path.is_file():
        return []
    entries = {}
    raw_fields: dict[str, dict[str, str]] = {}
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _CONF_LINE_RE.match(stripped)
        if not match:
            continue
        key, value = match.group(1), match.group(2)
        entries[key] = value
        inst_match = _INSTANCE_KEY_RE.match(key)
        if inst_match:
            raw_fields.setdefault(inst_match.group(1), {})[inst_match.group(2)] = value

    installed_raw = entries.get("bst.installed_images", "")
    installed = [item.strip() for item in installed_raw.split(",") if item.strip()]
    installed_set = set(installed)
    live_keys = set(running_keys)
    if installed_set:
        candidate_keys = [k for k in raw_fields if k in installed_set or k in live_keys]
        for k in installed:
            if k not in candidate_keys:
                candidate_keys.append(k)
    else:
        candidate_keys = [
            k for k, fields in raw_fields.items()
            if any(f in fields for f in ("adb_port", "status.adb_port", "display_name"))
        ]

    family_order: dict[str, int] = {}
    for item in (*installed, *candidate_keys):
        base = _INSTANCE_SUFFIX_RE.match(item).group(1)
        family_order.setdefault(base, len(family_order))

    def sort_key(inst_key: str):
        m = _INSTANCE_SUFFIX_RE.match(inst_key)
        base, suffix_str = m.group(1), m.group(2)
        suffix_num = int(suffix_str) if suffix_str is not None else -1
        return (family_order.get(base, 999), suffix_num, inst_key)

    global_adb = entries.get("bst.enable_adb_access", "0").strip() == "1"
    instances = []
    for idx, inst_key in enumerate(sorted(set(candidate_keys), key=sort_key)):
        fields = raw_fields.get(inst_key, {})
        m = _INSTANCE_SUFFIX_RE.match(inst_key)
        suffix = int(m.group(2)) if m.group(2) is not None else None
        port = _positive_port(fields.get("status.adb_port")) or _positive_port(fields.get("adb_port"))
        inst_adb = fields.get("enable_adb_access")
        adb_enabled = (inst_adb.strip() == "1") if inst_adb is not None else global_adb
        display_name = fields.get("display_name", "").strip() or inst_key
        instances.append(BlueStacksInstance(
            key=inst_key,
            display_name=display_name,
            index=idx,
            suffix=suffix,
            adb_port=port,
            adb_enabled=adb_enabled,
        ))
    return instances


def _registry_bluestacks_dirs() -> tuple[list[Path], list[Path]]:
    if sys.platform != "win32":
        return [], []
    import winreg

    install_dirs, data_dirs = [], []
    access_modes = [winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0), winreg.KEY_READ]
    roots = [winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER]
    for root in roots:
        for subkey in _BLUESTACKS_REG_KEYS:
            for access in access_modes:
                try:
                    with winreg.OpenKey(root, subkey, 0, access) as handle:
                        for name, bucket in (("InstallDir", install_dirs),
                                             ("UserDefinedDir", data_dirs),
                                             ("DataDir", data_dirs)):
                            try:
                                value, _ = winreg.QueryValueEx(handle, name)
                            except OSError:
                                continue
                            if isinstance(value, str) and value.strip():
                                p = Path(value.strip())
                                if p not in bucket:
                                    bucket.append(p)
                                if name == "DataDir" and p.parent not in bucket:
                                    bucket.append(p.parent)
                except OSError:
                    continue
    return install_dirs, data_dirs


def _drive_candidate_dirs() -> list[Path]:
    if sys.platform != "win32":
        return []
    import os

    candidates = []
    for env_name in ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)", "ProgramData"):
        val = os.environ.get(env_name)
        if val:
            for folder in ("BlueStacks_nxt", "BlueStacks_msi5"):
                candidates.append(Path(val) / folder)
    try:
        bitmask = ct.windll.kernel32.GetLogicalDrives()
    except (AttributeError, OSError):
        bitmask = 0
    for i in range(26):
        if bitmask & (1 << i):
            drive = f"{chr(ord('A') + i)}:\\"
            for rel in (
                "BlueStacks_nxt",
                r"Program Files\BlueStacks_nxt",
                r"ProgramData\BlueStacks_nxt",
                r"Games\BlueStacks_nxt",
                "BlueStacks_msi5",
            ):
                candidates.append(Path(drive) / rel)
    unique = []
    seen = set()
    for p in candidates:
        key = str(p).lower()
        if key not in seen:
            seen.add(key)
            unique.append(p)
    return unique


def _running_bluestacks_exe_dirs() -> list[Path]:
    if sys.platform != "win32":
        return []
    dirs = []
    for _, exe_path, _ in _iter_processes(("hd-player.exe", "hd-multiinstancemanager.exe", "bstksvc.exe")):
        if exe_path is not None and exe_path.parent not in dirs:
            dirs.append(exe_path.parent)
    return dirs


def find_bluestacks_conf(conf_arg: Path | None = None, adb_path: Path | None = None) -> Path | None:
    if conf_arg is not None:
        p = Path(conf_arg)
        if p.is_dir():
            p = p / "bluestacks.conf"
        if not p.is_file():
            raise FileNotFoundError(f"BlueStacks config not found at {p}")
        return p

    _, reg_data_dirs = _registry_bluestacks_dirs()
    search_dirs = list(reg_data_dirs)
    if adb_path is not None:
        adb_dir = Path(adb_path).parent
        search_dirs.extend([adb_dir, adb_dir.parent])
        if adb_dir.drive:
            drive = Path(f"{adb_dir.drive}\\")
            search_dirs.extend([
                drive / "BlueStacks_nxt",
                drive / "ProgramData" / "BlueStacks_nxt",
            ])
    for exe_dir in _running_bluestacks_exe_dirs():
        search_dirs.extend([exe_dir, exe_dir.parent])
        if exe_dir.drive:
            drive = Path(f"{exe_dir.drive}\\")
            search_dirs.extend([
                drive / "BlueStacks_nxt",
                drive / "ProgramData" / "BlueStacks_nxt",
            ])
    search_dirs.extend(_drive_candidate_dirs())

    seen = set()
    for directory in search_dirs:
        key = str(directory).lower()
        if key in seen:
            continue
        seen.add(key)
        candidate = directory / "bluestacks.conf"
        if candidate.is_file():
            return candidate
    return None


def find_bluestacks_adb(adb_arg: Path | None = None, conf_path: Path | None = None) -> Path:
    if adb_arg is not None:
        p = Path(adb_arg)
        if p.is_dir():
            for name in ("HD-Adb.exe", "adb.exe", "adb"):
                if (p / name).is_file():
                    return p / name
            raise FileNotFoundError(f"Neither HD-Adb.exe nor adb.exe was found in {p}")
        if not p.is_file():
            raise FileNotFoundError(f"ADB executable not found at {p}")
        return p

    reg_install_dirs, _ = _registry_bluestacks_dirs()
    search_dirs = [*reg_install_dirs, *_running_bluestacks_exe_dirs()]
    if conf_path is not None:
        conf_dir = Path(conf_path).parent
        search_dirs.extend([conf_dir, conf_dir.parent])
        if conf_dir.drive:
            drive = Path(f"{conf_dir.drive}\\")
            search_dirs.extend([
                drive / "BlueStacks_nxt",
                drive / "Program Files" / "BlueStacks_nxt",
            ])
    search_dirs.extend(_drive_candidate_dirs())

    seen = set()
    for directory in search_dirs:
        key = str(directory).lower()
        if key in seen:
            continue
        seen.add(key)
        for name in ("HD-Adb.exe", "adb.exe"):
            candidate = directory / name
            if candidate.is_file():
                return candidate

    for name in ("HD-Adb.exe", "adb.exe", "adb"):
        found = shutil.which(name)
        if found:
            return Path(found)

    raise FileNotFoundError(
        "Could not locate BlueStacks 5 HD-Adb.exe. Pass --adb <path-to-HD-Adb.exe>."
    )


def _adb_state(adb: Path, serial: str, timeout=4) -> str:
    result = subprocess.run(
        [str(adb), "-s", serial, "get-state"],
        capture_output=True,
        timeout=timeout,
        creationflags=_NO_WINDOW,
    )
    if result.returncode != 0:
        return ""
    return result.stdout.decode(errors="replace").strip()


def _connect_tcp_adb(adb: Path, serial: str) -> bool:
    if _adb_state(adb, serial) == "device":
        return True
    connect_out = subprocess.run(
        [str(adb), "connect", serial],
        capture_output=True,
        timeout=8,
        creationflags=_NO_WINDOW,
    )
    combined = (connect_out.stdout + connect_out.stderr).decode(errors="replace").lower()
    state = _adb_state(adb, serial)
    if state == "device":
        return True
    if state == "offline" or "offline" in combined:
        subprocess.run(
            [str(adb), "disconnect", serial],
            capture_output=True,
            timeout=5,
            creationflags=_NO_WINDOW,
        )
        sleep(0.25)
        subprocess.run(
            [str(adb), "connect", serial],
            capture_output=True,
            timeout=8,
            creationflags=_NO_WINDOW,
        )
        return _adb_state(adb, serial) == "device"
    return False


def ensure_adb_connected(
    adb: Path,
    serial: str,
    *,
    conf: Path | None = None,
    instance_key: str | None = None,
    allow_port_refresh: bool = False,
) -> str:
    if _adb_state(adb, serial) == "device":
        return serial
    if is_tcp_serial(serial):
        if _connect_tcp_adb(adb, serial):
            return serial
        if allow_port_refresh and conf is not None and instance_key:
            for inst in parse_bluestacks_conf(conf):
                if inst.key == instance_key and inst.serial and inst.serial != serial:
                    if _connect_tcp_adb(adb, inst.serial):
                        return inst.serial
        if conf is not None:
            instances = parse_bluestacks_conf(conf)
            matched = next(
                (i for i in instances if i.key == instance_key or i.serial == serial),
                None,
            )
            if matched is not None and not matched.adb_enabled:
                raise RuntimeError(
                    f"ADB is disabled for BlueStacks instance '{matched.display_name}' ({matched.key}). "
                    "Enable 'Android Debug Bridge' in BlueStacks 5 Settings -> Advanced."
                )
        label = f" ({instance_key})" if instance_key else ""
        raise RuntimeError(
            f"ADB device {serial}{label} is unavailable. Make sure the BlueStacks 5 instance is "
            "running and 'Android Debug Bridge' is enabled in Settings -> Advanced."
        )
    raise RuntimeError(f"ADB device {serial} is unavailable.")


def adb_run(adb: Path, serial: str, *arguments, timeout=8) -> bytes:
    try:
        return run(adb, "-s", serial, *arguments, timeout=timeout)
    except subprocess.CalledProcessError as exc:
        err = exc.stderr.decode(errors="replace").lower()
        if is_tcp_serial(serial) and ("offline" in err or "not found" in err or "closed" in err):
            if _connect_tcp_adb(adb, serial):
                return run(adb, "-s", serial, *arguments, timeout=timeout)
        raise


def _jitter_offset(rng, radius: float) -> float:
    if radius <= 0:
        return 0.0
    for _ in range(4):
        val = rng.gauss(0.0, radius / 2.2)
        if -radius <= val <= radius:
            return val
    return max(-radius, min(radius, rng.uniform(-radius * 0.7, radius * 0.7)))


def human_tap(
    adb: Path,
    serial: str,
    point: tuple[float, float],
    *,
    frame_size: tuple[int, int] | None = None,
    viewport_size: tuple[int, int] = (1280, 720),
    raw_point: bool = False,
    jitter: tuple[float, float] = (6.0, 6.0),
    rng=None,
) -> tuple[int, int]:
    """Send a humanized touch press with safe button jitter, hold duration, and micro-drift."""
    gen = rng if rng is not None else _SYS_RNG
    px = point[0] + _jitter_offset(gen, jitter[0])
    py = point[1] + _jitter_offset(gen, jitter[1])
    if not raw_point and frame_size is not None:
        width, height = frame_size
        x1 = round(px * width / viewport_size[0])
        y1 = round(py * height / viewport_size[1])
        max_x, max_y = width - 4, height - 4
    else:
        x1 = round(px)
        y1 = round(py)
        max_x = (frame_size[0] - 4) if frame_size else max(x1 + 4, 320)
        max_y = (frame_size[1] - 4) if frame_size else max(y1 + 4, 180)
    x1 = max(4, min(max_x, x1))
    y1 = max(4, min(max_y, y1))

    drift_choices = (-1, 0, 0, 0, 1, 2 if gen.random() < 0.2 else 0)
    x2 = max(4, min(max_x, x1 + gen.choice(drift_choices)))
    y2 = max(4, min(max_y, y1 + gen.choice(drift_choices)))
    if gen.random() < 0.12:
        duration_ms = gen.randint(115, 162)
    else:
        duration_ms = round(max(46.0, min(118.0, gen.gauss(74.0, 16.0))))
    adb_run(adb, serial, "shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), str(duration_ms))
    return x1, y1


def parse_foreground_window(dumpsys_text: str) -> tuple[str | None, str | None]:
    match = _WINDOW_FOCUS_RE.search(dumpsys_text)
    if match:
        return match.group(1), match.group(2)
    focus_line = _CURRENT_FOCUS_LINE_RE.search(dumpsys_text)
    if focus_line:
        raw_focus = focus_line.group(1).strip()
        if raw_focus.startswith("null") or "PopupWindow:" in raw_focus:
            app_match = _FOCUSED_APP_WINDOW_RE.search(dumpsys_text)
            if app_match:
                return app_match.group(1), app_match.group(2)
    return None, None


def foreground_window(adb: Path, serial: str) -> tuple[str | None, str | None]:
    focus = adb_run(adb, serial, "shell", "dumpsys", "window").decode(errors="replace")
    return parse_foreground_window(focus)


def parse_foreground_activity(dumpsys_text: str) -> str | None:
    package, activity = parse_foreground_window(dumpsys_text)
    return activity if package == "com.raongames.growcastle" else None


def foreground_activity(adb: Path, serial: str) -> str | None:
    package, activity = foreground_window(adb, serial)
    return activity if package == "com.raongames.growcastle" else None


def is_ad_activity(activity: str | None) -> bool:
    if not activity:
        return False
    lowered = activity.lower()
    if lowered.startswith(("org.cocos2dx.", "com.raongames.growcastle.")):
        return False
    return any(hint in lowered for hint in _AD_ACTIVITY_HINTS)


# --- Win32 process, window discovery, and screen capture helpers ---

class _BITMAPINFOHEADER(ct.Structure):
    _fields_ = [
        ("biSize", ct.c_uint32),
        ("biWidth", ct.c_int32),
        ("biHeight", ct.c_int32),
        ("biPlanes", ct.c_uint16),
        ("biBitCount", ct.c_uint16),
        ("biCompression", ct.c_uint32),
        ("biSizeImage", ct.c_uint32),
        ("biXPelsPerMeter", ct.c_int32),
        ("biYPelsPerMeter", ct.c_int32),
        ("biClrUsed", ct.c_uint32),
        ("biClrImportant", ct.c_uint32),
    ]


class _PROCESSENTRY32W(ct.Structure):
    _fields_ = [
        ("dwSize", ct.c_uint32),
        ("cntUsage", ct.c_uint32),
        ("th32ProcessID", ct.c_uint32),
        ("th32DefaultHeapID", ct.c_size_t),
        ("th32ModuleID", ct.c_uint32),
        ("cntThreads", ct.c_uint32),
        ("th32ParentProcessID", ct.c_uint32),
        ("pcPriClassBase", ct.c_int32),
        ("dwFlags", ct.c_uint32),
        ("szExeFile", ct.c_wchar * 260),
    ]


class _PROCESS_BASIC_INFORMATION(ct.Structure):
    _fields_ = [
        ("Reserved1", ct.c_void_p),
        ("PebBaseAddress", ct.c_void_p),
        ("Reserved2", ct.c_void_p * 2),
        ("UniqueProcessId", ct.c_void_p),
        ("Reserved3", ct.c_void_p),
    ]


class _UNICODE_STRING(ct.Structure):
    _fields_ = [
        ("Length", ct.c_uint16),
        ("MaximumLength", ct.c_uint16),
        ("Buffer", ct.c_void_p),
    ]


_WIN32_BOUND = False


def _bind_win32():
    global _WIN32_BOUND
    from ctypes import wintypes

    user32 = ct.windll.user32
    gdi32 = ct.windll.gdi32
    kernel32 = ct.windll.kernel32
    if not _WIN32_BOUND:
        user32.IsWindow.argtypes = (wintypes.HWND,)
        user32.IsWindow.restype = wintypes.BOOL
        user32.IsWindowVisible.argtypes = (wintypes.HWND,)
        user32.IsWindowVisible.restype = wintypes.BOOL
        user32.IsIconic.argtypes = (wintypes.HWND,)
        user32.IsIconic.restype = wintypes.BOOL
        user32.GetForegroundWindow.argtypes = ()
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.GetAncestor.argtypes = (wintypes.HWND, ct.c_uint)
        user32.GetAncestor.restype = wintypes.HWND
        user32.GetWindowRect.argtypes = (wintypes.HWND, ct.POINTER(wintypes.RECT))
        user32.GetWindowRect.restype = wintypes.BOOL
        user32.GetClientRect.argtypes = (wintypes.HWND, ct.POINTER(wintypes.RECT))
        user32.GetClientRect.restype = wintypes.BOOL
        user32.ClientToScreen.argtypes = (wintypes.HWND, ct.POINTER(wintypes.POINT))
        user32.ClientToScreen.restype = wintypes.BOOL
        user32.WindowFromPoint.argtypes = (wintypes.POINT,)
        user32.WindowFromPoint.restype = wintypes.HWND
        user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ct.POINTER(wintypes.DWORD))
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        user32.GetWindowTextLengthW.argtypes = (wintypes.HWND,)
        user32.GetWindowTextLengthW.restype = ct.c_int
        user32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ct.c_int)
        user32.GetWindowTextW.restype = ct.c_int
        user32.GetClassNameW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ct.c_int)
        user32.GetClassNameW.restype = ct.c_int
        user32.GetWindowLongW.argtypes = (wintypes.HWND, ct.c_int)
        user32.GetWindowLongW.restype = ct.c_long
        user32.GetSystemMetrics.argtypes = (ct.c_int,)
        user32.GetSystemMetrics.restype = ct.c_int
        user32.GetDC.argtypes = (wintypes.HWND,)
        user32.GetDC.restype = wintypes.HDC
        user32.ReleaseDC.argtypes = (wintypes.HWND, wintypes.HDC)
        user32.ReleaseDC.restype = ct.c_int
        user32.PrintWindow.argtypes = (wintypes.HWND, wintypes.HDC, ct.c_uint)
        user32.PrintWindow.restype = wintypes.BOOL

        gdi32.CreateCompatibleDC.argtypes = (wintypes.HDC,)
        gdi32.CreateCompatibleDC.restype = wintypes.HDC
        gdi32.DeleteDC.argtypes = (wintypes.HDC,)
        gdi32.DeleteDC.restype = wintypes.BOOL
        gdi32.CreateDIBSection.argtypes = (
            wintypes.HDC, ct.POINTER(_BITMAPINFOHEADER), ct.c_uint,
            ct.POINTER(ct.c_void_p), wintypes.HANDLE, wintypes.DWORD,
        )
        gdi32.CreateDIBSection.restype = wintypes.HBITMAP
        gdi32.SelectObject.argtypes = (wintypes.HDC, wintypes.HGDIOBJ)
        gdi32.SelectObject.restype = wintypes.HGDIOBJ
        gdi32.DeleteObject.argtypes = (wintypes.HGDIOBJ,)
        gdi32.DeleteObject.restype = wintypes.BOOL

        kernel32.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
        kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        kernel32.Process32FirstW.argtypes = (wintypes.HANDLE, ct.POINTER(_PROCESSENTRY32W))
        kernel32.Process32FirstW.restype = wintypes.BOOL
        kernel32.Process32NextW.argtypes = (wintypes.HANDLE, ct.POINTER(_PROCESSENTRY32W))
        kernel32.Process32NextW.restype = wintypes.BOOL
        kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.QueryFullProcessImageNameW.argtypes = (
            wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ct.POINTER(wintypes.DWORD),
        )
        kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
        kernel32.ReadProcessMemory.argtypes = (
            wintypes.HANDLE, ct.c_void_p, ct.c_void_p, ct.c_size_t, ct.POINTER(ct.c_size_t),
        )
        kernel32.ReadProcessMemory.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL
        _WIN32_BOUND = True
    return user32, gdi32, kernel32


def enable_dpi_awareness():
    if sys.platform != "win32":
        return
    user32 = ct.windll.user32
    try:
        set_context = user32.SetProcessDpiAwarenessContext
        set_context.argtypes = (ct.c_void_p,)
        set_context.restype = ct.c_int
        if set_context(ct.c_void_p(-4)):  # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
            return
    except AttributeError:
        pass
    user32.SetProcessDPIAware()


def _read_process_cmdline_and_path(kernel32, pid: int) -> tuple[Path | None, str | None]:
    from ctypes import wintypes

    exe_path = None
    cmdline = None
    # PROCESS_QUERY_LIMITED_INFORMATION = 0x1000, PROCESS_VM_READ = 0x0010, PROCESS_QUERY_INFORMATION = 0x0400
    handle = kernel32.OpenProcess(0x1000, False, pid)
    if handle:
        try:
            buf = ct.create_unicode_buffer(1024)
            size = wintypes.DWORD(len(buf))
            if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ct.byref(size)):
                exe_path = Path(buf.value)
        finally:
            kernel32.CloseHandle(handle)

    if ct.sizeof(ct.c_void_p) == 8:
        vm_handle = kernel32.OpenProcess(0x0400 | 0x0010, False, pid)
        if vm_handle:
            try:
                ntdll = ct.windll.ntdll
                pbi = _PROCESS_BASIC_INFORMATION()
                ret_len = ct.c_ulong(0)
                status = ntdll.NtQueryInformationProcess(
                    wintypes.HANDLE(vm_handle), 0, ct.byref(pbi), ct.sizeof(pbi), ct.byref(ret_len)
                )
                if status == 0 and pbi.PebBaseAddress:
                    params_ptr = ct.c_void_p()
                    read = ct.c_size_t()
                    if (kernel32.ReadProcessMemory(
                            vm_handle, ct.c_void_p(pbi.PebBaseAddress + 0x20),
                            ct.byref(params_ptr), ct.sizeof(params_ptr), ct.byref(read))
                            and params_ptr.value):
                        ustr = _UNICODE_STRING()
                        if (kernel32.ReadProcessMemory(
                                vm_handle, ct.c_void_p(params_ptr.value + 0x70),
                                ct.byref(ustr), ct.sizeof(ustr), ct.byref(read))
                                and 0 < ustr.Length <= 32768 and ustr.Buffer):
                            chars = ustr.Length // 2
                            wbuf = ct.create_unicode_buffer(chars + 1)
                            if kernel32.ReadProcessMemory(
                                    vm_handle, ct.c_void_p(ustr.Buffer),
                                    wbuf, ustr.Length, ct.byref(read)):
                                cmdline = wbuf.value
            except (AttributeError, OSError):
                pass
            finally:
                kernel32.CloseHandle(vm_handle)
    return exe_path, cmdline


def _iter_processes(names_lower: tuple[str, ...]):
    if sys.platform != "win32":
        return
    _, _, kernel32 = _bind_win32()
    invalid = ct.c_void_p(-1).value
    snap = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)  # TH32CS_SNAPPROCESS
    if not snap or snap == invalid:
        return
    try:
        entry = _PROCESSENTRY32W()
        entry.dwSize = ct.sizeof(entry)
        ok = kernel32.Process32FirstW(snap, ct.byref(entry))
        while ok:
            exe_name = entry.szExeFile.lower()
            if exe_name in names_lower:
                pid = int(entry.th32ProcessID)
                exe_path, cmdline = _read_process_cmdline_and_path(kernel32, pid)
                yield pid, exe_path, cmdline
            ok = kernel32.Process32NextW(snap, ct.byref(entry))
    finally:
        kernel32.CloseHandle(snap)


def _window_text(user32, hwnd: int) -> str:
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buf = ct.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def _class_name(user32, hwnd: int) -> str:
    buf = ct.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def _client_size(user32, hwnd: int) -> tuple[int, int]:
    from ctypes import wintypes

    rect = wintypes.RECT()
    if user32.GetClientRect(hwnd, ct.byref(rect)):
        return int(rect.right), int(rect.bottom)
    return 0, 0


def _find_viewport_hwnd(user32, top_hwnd: int) -> tuple[int, tuple[int, int]]:
    from ctypes import wintypes

    candidates = []
    enum_proc_type = ct.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def on_child(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        w, h = _client_size(user32, hwnd)
        if w < 320 or h < 180:
            return True
        aspect_err = abs((w / h) / (16 / 9) - 1)
        cls = _class_name(user32, hwnd)
        title = _window_text(user32, hwnd)
        if aspect_err <= 0.035:
            rank = (
                2 if cls in _VIEWPORT_CLASSES else
                1 if (cls in _INPUT_CLASSES or title in _VIEWPORT_TITLES) else
                0
            )
            candidates.append((rank, w * h, -aspect_err, int(hwnd), (w, h)))
        return True

    cb = enum_proc_type(on_child)
    user32.EnumChildWindows(top_hwnd, cb, 0)
    if candidates:
        candidates.sort(reverse=True)
        _, _, _, best_hwnd, best_size = candidates[0]
        return best_hwnd, best_size

    w, h = _client_size(user32, top_hwnd)
    return int(top_hwnd), (w, h)


def list_bluestacks_windows(instances: list[BlueStacksInstance] = ()) -> list[RunningWindow]:
    if sys.platform != "win32":
        return []
    from ctypes import wintypes

    user32, _, _ = _bind_win32()
    hd_procs: dict[int, tuple[Path | None, str | None]] = {}
    for pid, exe_path, cmdline in _iter_processes(("hd-player.exe",)):
        inst_key = None
        if cmdline:
            m = _CMDLINE_INSTANCE_RE.search(cmdline)
            if m:
                inst_key = m.group(1) or m.group(2)
        hd_procs[pid] = (exe_path, inst_key)
    if not hd_procs:
        return []

    by_title_exact = {inst.display_name: inst.key for inst in instances}
    by_title_lower = {inst.display_name.lower(): inst.key for inst in instances}

    per_pid: dict[int, list[tuple[tuple, RunningWindow]]] = {}
    enum_proc_type = ct.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def on_top(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        pid_dword = wintypes.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ct.byref(pid_dword))
        pid = int(pid_dword.value)
        if pid not in hd_procs:
            return True
        ex_style = user32.GetWindowLongW(hwnd, -20)  # GWL_EXSTYLE
        if ex_style & 0x00000080:  # WS_EX_TOOLWINDOW
            return True
        title = _window_text(user32, hwnd).strip()
        minimized = bool(user32.IsIconic(hwnd))
        if minimized:
            if not title:
                return True
            vp_hwnd, vp_size = int(hwnd), (0, 0)
            has_16_9 = False
        else:
            vp_hwnd, vp_size = _find_viewport_hwnd(user32, hwnd)
            w, h = vp_size
            if w < 320 or h < 180:
                return True
            has_16_9 = abs((w / h) / (16 / 9) - 1) <= 0.035

        exe_path, cmd_inst_key = hd_procs[pid]
        matched_key = (
            cmd_inst_key
            or by_title_exact.get(title)
            or by_title_lower.get(title.lower())
        )
        score = (
            1 if has_16_9 else 0,
            1 if matched_key else 0,
            1 if title else 0,
            vp_size[0] * vp_size[1],
        )
        win = RunningWindow(
            pid=pid,
            root_hwnd=int(hwnd),
            viewport_hwnd=int(vp_hwnd),
            title=title,
            viewport_size=vp_size,
            instance_key=matched_key,
            exe_path=exe_path,
            minimized=minimized,
        )
        per_pid.setdefault(pid, []).append((score, win))
        return True

    cb = enum_proc_type(on_top)
    user32.EnumWindows(cb, 0)
    windows = []
    for candidates in per_pid.values():
        candidates.sort(key=lambda item: item[0], reverse=True)
        windows.append(candidates[0][1])
    if len(windows) == 1 and len(instances) == 1 and windows[0].instance_key is None:
        w = windows[0]
        windows[0] = RunningWindow(
            pid=w.pid,
            root_hwnd=w.root_hwnd,
            viewport_hwnd=w.viewport_hwnd,
            title=w.title,
            viewport_size=w.viewport_size,
            instance_key=instances[0].key,
            exe_path=w.exe_path,
            minimized=w.minimized,
        )
    return windows


def ldplayer_window_handle(console: Path, index: int) -> int:
    user32, _, _ = _bind_win32()
    output = run(console, "list2").decode(errors="replace")
    for line in output.splitlines():
        columns = line.split(",")
        if len(columns) >= 7 and columns[0] == str(index):
            hwnd = int(columns[3])
            if columns[4] == "1" and hwnd and user32.IsWindow(hwnd):
                return hwnd
            break
    raise RuntimeError(f"LDPlayer instance {index} has no running game window.")


def bluestacks_window_handle(
    *,
    instance_key: str | None = None,
    display_name: str | None = None,
    conf: Path | None = None,
) -> int:
    instances = parse_bluestacks_conf(conf) if conf else []
    windows = list_bluestacks_windows(instances)
    if not windows:
        raise RuntimeError("No running BlueStacks 5 game window was found.")

    matched = None
    if instance_key:
        matched = next(
            (w for w in windows if w.instance_key and w.instance_key.lower() == instance_key.lower()),
            None,
        )
    if matched is None and display_name:
        matched = next((w for w in windows if w.title == display_name), None)
        if matched is None:
            matched = next((w for w in windows if w.title.lower() == display_name.lower()), None)
    if matched is None and instance_key and display_name is None:
        matched = next((w for w in windows if w.title.lower() == instance_key.lower()), None)
    if matched is None and len(windows) == 1 and (
        not instance_key or is_tcp_serial(instance_key)
    ):
        matched = windows[0]

    if matched is None:
        label = display_name or instance_key or "selected instance"
        raise RuntimeError(f"BlueStacks 5 window for '{label}' is not open.")
    if matched.minimized:
        raise RuntimeError(f"BlueStacks 5 window '{matched.title}' is minimized.")
    # Refresh viewport HWND in case the user toggled fullscreen or sidebar since lookup.
    user32, _, _ = _bind_win32()
    vp_hwnd, _ = _find_viewport_hwnd(user32, matched.root_hwnd)
    return vp_hwnd


def target_window_handle(target: EmulatorTarget) -> int:
    if target.emulator == "ldplayer":
        if target.ldconsole is None:
            raise RuntimeError("LDPlayer console path is required for window capture.")
        return ldplayer_window_handle(target.ldconsole, target.index)
    return bluestacks_window_handle(
        instance_key=target.instance,
        display_name=target.display_name,
        conf=target.conf,
    )


def _is_viewport_unoccluded(user32, root_hwnd: int, x0: int, y0: int, w: int, h: int) -> bool:
    from ctypes import wintypes

    vx = user32.GetSystemMetrics(76)  # SM_XVIRTUALSCREEN
    vy = user32.GetSystemMetrics(77)  # SM_YVIRTUALSCREEN
    vw = user32.GetSystemMetrics(78)  # SM_CXVIRTUALSCREEN
    vh = user32.GetSystemMetrics(79)  # SM_CYVIRTUALSCREEN
    if vw > 0 and vh > 0:
        if x0 < vx or y0 < vy or x0 + w > vx + vw or y0 + h > vy + vh:
            return False

    # Check viewport corners + CAPTCHA board corners and center.
    bx0, by0 = x0 + int(w * 0.33), y0 + int(h * 0.16)
    bx1, by1 = x0 + int(w * 0.66), y0 + int(h * 0.74)
    bcx, bcy = (bx0 + bx1) // 2, (by0 + by1) // 2
    sample_points = (
        (bcx, bcy),
        (bx0, by0),
        (bx1, by0),
        (bx0, by1),
        (bx1, by1),
        (x0 + 8, y0 + 8),
        (x0 + w - 9, y0 + 8),
        (x0 + 8, y0 + h - 9),
        (x0 + w - 9, y0 + h - 9),
    )
    for px, py in sample_points:
        hit = user32.WindowFromPoint(wintypes.POINT(px, py))
        if not hit:
            return False
        if hit != root_hwnd and user32.GetAncestor(hit, 2) != root_hwnd:
            return False
    return True


def _print_window_crop(user32, gdi32, root_hwnd: int, vp_hwnd: int, vx: int, vy: int, vw: int, vh: int):
    from ctypes import wintypes
    from PIL import Image

    if root_hwnd == vp_hwnd:
        target_hwnd = vp_hwnd
        bw, bh = vw, vh
        flags = 1 | 2  # PW_CLIENTONLY | PW_RENDERFULLCONTENT
        crop_box = None
    else:
        root_rect = wintypes.RECT()
        if not user32.GetWindowRect(root_hwnd, ct.byref(root_rect)):
            return None
        bw = int(root_rect.right - root_rect.left)
        bh = int(root_rect.bottom - root_rect.top)
        cx0 = vx - int(root_rect.left)
        cy0 = vy - int(root_rect.top)
        if bw <= 0 or bh <= 0 or cx0 < 0 or cy0 < 0 or cx0 + vw > bw or cy0 + vh > bh:
            return None
        target_hwnd = root_hwnd
        flags = 2  # PW_RENDERFULLCONTENT
        crop_box = (cx0, cy0, cx0 + vw, cy0 + vh)

    wnd_dc = user32.GetDC(target_hwnd)
    if not wnd_dc:
        return None
    mem_dc = dib = old_obj = None
    try:
        mem_dc = gdi32.CreateCompatibleDC(wnd_dc)
        if not mem_dc:
            return None
        bmi = _BITMAPINFOHEADER()
        bmi.biSize = ct.sizeof(_BITMAPINFOHEADER)
        bmi.biWidth = bw
        bmi.biHeight = -bh  # top-down DIB
        bmi.biPlanes = 1
        bmi.biBitCount = 32
        bmi.biCompression = 0  # BI_RGB
        bits = ct.c_void_p()
        dib = gdi32.CreateDIBSection(wnd_dc, ct.byref(bmi), 0, ct.byref(bits), None, 0)
        if not dib or not bits.value:
            return None
        old_obj = gdi32.SelectObject(mem_dc, dib)
        if not user32.PrintWindow(target_hwnd, mem_dc, flags):
            return None
        raw = ct.string_at(bits.value, bw * bh * 4)
        # Skip solid-black captures produced when an OpenGL surface cannot be redirected.
        if not any(raw[::97]):
            return None
        image = Image.frombytes("RGB", (bw, bh), raw, "raw", "BGRX")
        if crop_box is not None:
            cropped = image.crop(crop_box)
            image.close()
            return cropped
        return image
    finally:
        if old_obj and mem_dc:
            gdi32.SelectObject(mem_dc, old_obj)
        if dib:
            gdi32.DeleteObject(dib)
        if mem_dc:
            gdi32.DeleteDC(mem_dc)
        user32.ReleaseDC(target_hwnd, wnd_dc)


def grab_game_window(hwnd: int):
    from ctypes import wintypes
    from PIL import ImageGrab

    user32, gdi32, _ = _bind_win32()
    root_hwnd = user32.GetAncestor(hwnd, 2) or hwnd
    if user32.IsIconic(root_hwnd):
        raise RuntimeError("Emulator window is minimized.")

    origin, bounds = wintypes.POINT(0, 0), wintypes.RECT()
    if (user32.ClientToScreen(hwnd, ct.byref(origin))
            and user32.GetClientRect(hwnd, ct.byref(bounds))
            and bounds.right > 0 and bounds.bottom > 0):
        vw, vh = int(bounds.right), int(bounds.bottom)
        if _is_viewport_unoccluded(user32, root_hwnd, int(origin.x), int(origin.y), vw, vh):
            return ImageGrab.grab(
                bbox=(origin.x, origin.y, origin.x + vw, origin.y + vh),
                all_screens=True,
            )
        printed = _print_window_crop(user32, gdi32, root_hwnd, hwnd, int(origin.x), int(origin.y), vw, vh)
        if printed is not None:
            return printed

    return ImageGrab.grab(window=hwnd)


# --- Instance selection & CLI listing ---

def _match_bluestacks_instance(
    instances: list[BlueStacksInstance],
    *,
    instance: str | None = None,
    index: int | None = None,
    serial: str | None = None,
) -> BlueStacksInstance | None:
    if instance is not None:
        query = instance.strip()
        q_lower = query.lower()
        for inst in instances:
            if inst.key.lower() == q_lower:
                return inst
        for inst in instances:
            if inst.display_name.lower() == q_lower:
                return inst
        if query.isdigit():
            num = int(query)
            suffix_matches = [
                inst for inst in instances
                if (inst.suffix == num) or (num == 0 and inst.suffix is None)
            ]
            if len(suffix_matches) == 1:
                return suffix_matches[0]
            for inst in instances:
                if inst.index == num:
                    return inst
        return None

    if index is not None:
        suffix_matches = [
            inst for inst in instances
            if (inst.suffix == index) or (index == 0 and inst.suffix is None)
        ]
        if len(suffix_matches) == 1:
            return suffix_matches[0]
        for inst in instances:
            if inst.index == index:
                return inst
        return None

    if serial is not None:
        m = _TCP_SERIAL_RE.match(serial.strip())
        if m:
            port = int(m.group(1))
            for inst in instances:
                if inst.adb_port == port:
                    return inst
    return None


def resolve_target(
    *,
    emulator: str | None = None,
    instance: str | None = None,
    index: int | None = None,
    serial: str | None = None,
    adb: Path | None = None,
    conf: Path | None = None,
    ldconsole: Path | None = None,
) -> EmulatorTarget:
    chosen = emulator
    if chosen is None:
        if ldconsole is not None or (serial and serial.startswith("emulator-")):
            chosen = "ldplayer"
        else:
            chosen = "bluestacks"

    if chosen == "ldplayer":
        console_path = Path(ldconsole) if ldconsole is not None else _DEFAULT_LDCONSOLE
        adb_path = Path(adb) if adb is not None else console_path.with_name("adb.exe")
        idx = 0 if index is None else index
        resolved_serial = serial or f"emulator-{5554 + 2 * idx}"
        return EmulatorTarget(
            emulator="ldplayer",
            adb=adb_path,
            serial=resolved_serial,
            instance=str(idx),
            display_name=f"LDPlayer {idx}",
            index=idx,
            ldconsole=console_path,
        )

    conf_path = find_bluestacks_conf(conf, adb)
    adb_path = find_bluestacks_adb(adb, conf_path)
    if conf_path is None:
        conf_path = find_bluestacks_conf(None, adb_path)

    windows_prelim = list_bluestacks_windows()
    running_keys = [w.instance_key for w in windows_prelim if w.instance_key]
    instances = parse_bluestacks_conf(conf_path, running_keys=running_keys) if conf_path else []
    windows = list_bluestacks_windows(instances) if instances else windows_prelim

    if instance is not None:
        matched = _match_bluestacks_instance(instances, instance=instance)
        if matched is None:
            win_match = next(
                (w for w in windows if w.title.lower() == instance.strip().lower()
                 or (w.instance_key and w.instance_key.lower() == instance.strip().lower())),
                None,
            )
            if win_match is not None and serial:
                return EmulatorTarget(
                    emulator="bluestacks",
                    adb=adb_path,
                    serial=serial,
                    instance=win_match.instance_key or win_match.title,
                    display_name=win_match.title or instance,
                    index=0,
                    conf=conf_path,
                )
            available = ", ".join(f"{i.key} ('{i.display_name}')" for i in instances) or "none found"
            raise ValueError(
                f"BlueStacks 5 instance '{instance}' not found. Available instances: {available}."
            )
        resolved_serial = serial or matched.serial
        if not resolved_serial:
            raise RuntimeError(
                f"BlueStacks 5 instance '{matched.key}' has no configured ADB port in {conf_path}."
            )
        return EmulatorTarget(
            emulator="bluestacks",
            adb=adb_path,
            serial=resolved_serial,
            instance=matched.key,
            display_name=matched.display_name,
            index=matched.index,
            conf=conf_path,
        )

    if index is not None:
        matched = _match_bluestacks_instance(instances, index=index)
        if matched is not None:
            resolved_serial = serial or matched.serial or f"127.0.0.1:{5555 + 10 * index}"
            return EmulatorTarget(
                emulator="bluestacks",
                adb=adb_path,
                serial=resolved_serial,
                instance=matched.key,
                display_name=matched.display_name,
                index=matched.index,
                conf=conf_path,
            )
        if instances:
            available = ", ".join(f"--index {i.index} ({i.key}, '{i.display_name}')" for i in instances)
            raise ValueError(f"BlueStacks 5 index {index} not found. Available: {available}.")
        resolved_serial = serial or f"127.0.0.1:{5555 + 10 * index}"
        return EmulatorTarget(
            emulator="bluestacks",
            adb=adb_path,
            serial=resolved_serial,
            instance=str(index),
            display_name=f"BlueStacks {index}",
            index=index,
            conf=conf_path,
        )

    if serial is not None:
        matched = _match_bluestacks_instance(instances, serial=serial)
        if matched is not None:
            return EmulatorTarget(
                emulator="bluestacks",
                adb=adb_path,
                serial=serial,
                instance=matched.key,
                display_name=matched.display_name,
                index=matched.index,
                conf=conf_path,
            )
        return EmulatorTarget(
            emulator="bluestacks",
            adb=adb_path,
            serial=serial,
            instance=serial,
            display_name=f"BlueStacks ({serial})",
            index=0,
            conf=conf_path,
        )

    # Auto-select when neither --instance, --index, nor --serial was passed.
    if len(windows) == 1:
        win = windows[0]
        matched = (
            _match_bluestacks_instance(instances, instance=win.instance_key)
            if win.instance_key else None
        ) or (
            _match_bluestacks_instance(instances, instance=win.title)
            if win.title else None
        )
        if matched is not None and matched.serial:
            return EmulatorTarget(
                emulator="bluestacks",
                adb=adb_path,
                serial=matched.serial,
                instance=matched.key,
                display_name=matched.display_name,
                index=matched.index,
                conf=conf_path,
            )
        if not instances:
            port = 5555
            if win.instance_key:
                m = _INSTANCE_SUFFIX_RE.match(win.instance_key)
                if m and m.group(2) is not None:
                    port = 5555 + 10 * int(m.group(2))
            return EmulatorTarget(
                emulator="bluestacks",
                adb=adb_path,
                serial=f"127.0.0.1:{port}",
                instance=win.instance_key or "",
                display_name=win.title or "BlueStacks App Player",
                index=0,
                conf=conf_path,
            )
    elif len(windows) > 1:
        by_key = {i.key: i for i in instances}
        descriptions = []
        for w in windows:
            inst = by_key.get(w.instance_key) if w.instance_key else None
            if inst is not None:
                descriptions.append(f"--instance {inst.key} ('{inst.display_name}', {inst.serial})")
            else:
                descriptions.append(f"--instance \"{w.title}\"")
        joined = "; ".join(descriptions)
        raise RuntimeError(
            f"Multiple BlueStacks 5 instances are running ({joined}). "
            "Specify --instance, --index, or --serial."
        )

    if len(instances) == 1 and instances[0].serial:
        inst = instances[0]
        return EmulatorTarget(
            emulator="bluestacks",
            adb=adb_path,
            serial=inst.serial,
            instance=inst.key,
            display_name=inst.display_name,
            index=inst.index,
            conf=conf_path,
        )
    if len(instances) > 1:
        first = instances[0]
        if first.serial:
            return EmulatorTarget(
                emulator="bluestacks",
                adb=adb_path,
                serial=first.serial,
                instance=first.key,
                display_name=first.display_name,
                index=first.index,
                conf=conf_path,
            )

    return EmulatorTarget(
        emulator="bluestacks",
        adb=adb_path,
        serial="127.0.0.1:5555",
        instance="",
        display_name="BlueStacks App Player",
        index=0,
        conf=conf_path,
    )


def format_instances(
    *,
    emulator: str = "bluestacks",
    adb: Path | None = None,
    conf: Path | None = None,
    ldconsole: Path | None = None,
) -> str:
    if emulator == "ldplayer":
        console_path = Path(ldconsole) if ldconsole is not None else _DEFAULT_LDCONSOLE
        if not console_path.is_file():
            return f"LDPlayer console not found at {console_path}"
        output = run(console_path, "list2").decode(errors="replace")
        lines = [f"LDPlayer ({console_path}):"]
        for row in output.splitlines():
            cols = row.split(",")
            if len(cols) >= 5 and cols[0].isdigit():
                idx = int(cols[0])
                status = "running" if cols[4] == "1" else "stopped"
                lines.append(f"  --index {idx}  title='{cols[1]}'  serial=emulator-{5554 + 2 * idx}  [{status}]")
        return "\n".join(lines)

    conf_path = find_bluestacks_conf(conf, adb)
    try:
        adb_path = find_bluestacks_adb(adb, conf_path)
    except FileNotFoundError as exc:
        adb_path = Path(f"<not found: {exc}>")
    windows = list_bluestacks_windows()
    instances = parse_bluestacks_conf(conf_path, [w.instance_key for w in windows if w.instance_key]) if conf_path else []
    if instances:
        windows = list_bluestacks_windows(instances)
    win_by_key = {w.instance_key: w for w in windows if w.instance_key}
    win_by_title = {w.title.lower(): w for w in windows if w.title}

    lines = [
        f"BlueStacks 5 ADB:    {adb_path}",
        f"BlueStacks 5 config: {conf_path or 'not found'}",
    ]
    if not instances and not windows:
        lines.append("  No BlueStacks 5 instances detected.")
        return "\n".join(lines)

    for inst in instances:
        win = win_by_key.get(inst.key) or win_by_title.get(inst.display_name.lower())
        if win is None:
            state = "stopped"
        elif win.minimized:
            state = "running, minimized"
        else:
            w, h = win.viewport_size
            state = f"running, viewport {w}x{h}"
        adb_note = "" if inst.adb_enabled else " (ADB disabled in config)"
        lines.append(
            f"  --index {inst.index}  --instance {inst.key:<10}  "
            f"title='{inst.display_name}'  serial={inst.serial or 'none'}{adb_note}  [{state}]"
        )
    known_pids = {
        (win_by_key.get(i.key) or win_by_title.get(i.display_name.lower())).pid
        for i in instances
        if (win_by_key.get(i.key) or win_by_title.get(i.display_name.lower())) is not None
    }
    for win in windows:
        if win.pid not in known_pids:
            w, h = win.viewport_size
            lines.append(f"  --instance \"{win.title}\"  pid={win.pid}  [running, viewport {w}x{h}]")
    return "\n".join(lines)
