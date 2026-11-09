"""Multi-layered rewarded-ad close detection (UI hierarchy, visual X/>>, and BACK fallback)."""

from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET

import numpy as np
from PIL import Image

from emulator import adb_run


KEYCODE_BACK = 4

_BOUNDS_RE = re.compile(r"^\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]$")

_RESUME_WARNINGS = (
    "lose your reward",
    "lose reward",
    "forfeit",
    "not receive",
    "won't receive",
    "missing out on your reward",
    "close video?",
    "skip video?",
    "mất phần thưởng",
    "không nhận được phần thưởng",
    "chưa nhận được phần thưởng",
    "bỏ phần thưởng",
    "đóng video?",
    "kết thúc video?",
)
_RESUME_ACTIONS = (
    "resume",
    "continue watching",
    "keep watching",
    "continue",
    "watch video",
    "tiếp tục xem",
    "tiếp tục",
    "xem tiếp",
    "ở lại",
)
_REWARD_GRANTED_PHRASES = (
    "reward granted",
    "reward earned",
    "reward unlocked",
    "you've earned",
    "đã trao phần thưởng",
    "đã nhận phần thưởng",
    "đã cấp phần thưởng",
    "nhận thưởng thành công",
    "đã mở khóa phần thưởng",
)
_COUNTDOWN_PATTERNS = (
    re.compile(r"\b(?:reward in|seconds? left|secs? left|seconds? remaining|secs? remaining)\b", re.I),
    re.compile(r"\b\d+\s*(?:seconds?|secs?|s)\s*(?:remaining|left)\b", re.I),
    re.compile(r"(?:còn|phần thưởng sau|nhận thưởng sau|thưởng trong)\s*\d+", re.I),
    re.compile(r"\b\d+\s*giây\s*(?:còn lại|nữa)?\b", re.I),
)
_SHORT_TIMER_RE = re.compile(r"^(?:\d{1,2}|\d{1,2}\s*s|0:\d{2})$", re.I)

_CLOSE_SYMBOLS = {"x", "×", "✕", "✖", "⨯", "╳"}
_SKIP_SYMBOLS = {">>", "»", ">|", "⏭"}
_CLOSE_LABELS = {
    "close",
    "close ad",
    "close button",
    "close video",
    "close advertisement",
    "dismiss",
    "no thanks",
    "no, thanks",
    "return to app",
    "return to game",
    "exit ad",
    "đóng",
    "đóng quảng cáo",
    "nút đóng",
    "tắt",
    "tắt quảng cáo",
    "không, cảm ơn",
    "quay lại ứng dụng",
    "quay lại trò chơi",
    "thoát quảng cáo",
}
_SKIP_LABELS = {
    "skip",
    "skip ad",
    "skip video",
    "next ad",
    "bỏ qua",
    "bỏ qua quảng cáo",
    "bỏ qua video",
    "quảng cáo tiếp theo",
}
_NEXT_AD_LABELS = {"next ad", "quảng cáo tiếp theo"}
_CLOSE_ID_TOKENS = (
    "close_button",
    "btn_close",
    "iv_close",
    "ad_close",
    "close_btn",
    "endcard_close",
    "mbridge_windwv_close",
    "tt_video_ad_close",
    "ia_tv_close",
    "vungle_close",
    "unityads_close",
    "close_wrapper",
    "dismiss_button",
    "btn_dismiss",
    "skip_button",
    "btn_skip",
    "al_skip",
)
_EXCLUDED_KEYWORDS = (
    "mute",
    "unmute",
    "volume",
    "sound",
    "audio",
    "speaker",
    "âm thanh",
    "tắt tiếng",
    "bật tiếng",
    "loa",
    "adchoices",
    "ad_choices",
    "why this ad",
    "privacy",
    "policy",
    "report",
    "feedback",
    "about_ad",
    "google_logo",
    "giới thiệu",
    "báo cáo",
    "quảng cáo của",
    "quyền riêng tư",
    "install",
    "download",
    "learn more",
    "learn_more",
    "watch now",
    "play now",
    "shop now",
    "sign up",
    "get_button",
    "cta",
    "cài đặt",
    "tải xuống",
    "tải về",
    "tìm hiểu thêm",
    "xem ngay",
    "chơi ngay",
    "mua ngay",
    "đăng ký",
)


@dataclass(frozen=True)
class AdSignal:
    kind: str  # "reward_granted", "ad_ui_close", "ad_visual_close", "ad_resume", "ad_back", "countdown_active"
    point: tuple[int, int] | None = None
    raw_point: bool = True
    keyevent: int | None = None


@dataclass(frozen=True)
class _UiNode:
    text: str
    desc: str
    res_id: str
    cls: str
    clickable: bool
    bounds: tuple[int, int, int, int]

    @property
    def width(self) -> int:
        return self.bounds[2] - self.bounds[0]

    @property
    def height(self) -> int:
        return self.bounds[3] - self.bounds[1]

    @property
    def center(self) -> tuple[int, int]:
        x1, y1, x2, y2 = self.bounds
        return (x1 + x2) // 2, (y1 + y2) // 2


def _norm(text: str) -> str:
    return " ".join(text.strip().lower().split())


def _is_excluded(node: _UiNode) -> bool:
    combined = f"{node.text} {node.desc} {node.res_id}".lower()
    if any(token in combined for token in _EXCLUDED_KEYWORDS):
        return True
    # Standalone "info" or "i" icon in ad chrome
    for label in (_norm(node.text), _norm(node.desc)):
        if label in {"i", "info", "ad", "ads", "quảng cáo", "sponsored", "được tài trợ"}:
            return True
    return False


def parse_ui_nodes(xml_text: str, screen_w: int, screen_h: int) -> list[_UiNode]:
    start = xml_text.find("<hierarchy")
    end = xml_text.rfind("</hierarchy>")
    if start < 0 or end < start:
        return []
    xml_body = xml_text[start:end + len("</hierarchy>")]
    try:
        root = ET.fromstring(xml_body)
    except ET.ParseError:
        return []

    nodes = []
    for elem in root.iter("node"):
        if elem.attrib.get("enabled", "true") == "false":
            continue
        m = _BOUNDS_RE.match(elem.attrib.get("bounds", ""))
        if not m:
            continue
        x1, y1, x2, y2 = (int(v) for v in m.groups())
        x1 = max(0, min(screen_w, x1))
        y1 = max(0, min(screen_h, y1))
        x2 = max(0, min(screen_w, x2))
        y2 = max(0, min(screen_h, y2))
        if x2 - x1 < 6 or y2 - y1 < 6:
            continue
        nodes.append(_UiNode(
            text=elem.attrib.get("text", ""),
            desc=elem.attrib.get("content-desc", ""),
            res_id=elem.attrib.get("resource-id", ""),
            cls=elem.attrib.get("class", ""),
            clickable=elem.attrib.get("clickable", "false") == "true",
            bounds=(x1, y1, x2, y2),
        ))
    return nodes


def analyze_ad_xml(
    xml_text: str,
    screen_w: int,
    screen_h: int,
    *,
    ad_elapsed: float = 0.0,
    static_duration: float = 0.0,
) -> AdSignal | None:
    nodes = parse_ui_nodes(xml_text, screen_w, screen_h)
    if not nodes:
        return None

    # 1. Safety guard: if an early close triggered "Lose reward? / Resume", tap Resume!
    has_warning = any(
        any(w in f"{n.text} {n.desc}".lower() for w in _RESUME_WARNINGS)
        for n in nodes
    )
    if has_warning:
        resume_candidates = []
        for n in nodes:
            for field in (_norm(n.text), _norm(n.desc)):
                if field and any(act == field or act in field for act in _RESUME_ACTIONS):
                    if n.width <= int(0.85 * screen_w) and n.height <= int(0.25 * screen_h):
                        resume_candidates.append((0 if n.clickable else 1, n.width * n.height, n))
                        break
        if resume_candidates:
            resume_candidates.sort(key=lambda item: item[:2])
            return AdSignal("ad_resume", resume_candidates[0][2].center, raw_point=True)
        return AdSignal("countdown_active")

    # 2. Check reward-granted status vs active countdown.
    reward_nodes = [
        n for n in nodes
        if any(p in f"{n.text} {n.desc}".lower() for p in _REWARD_GRANTED_PHRASES)
    ]
    reward_granted = bool(reward_nodes)

    next_ad_candidates = []
    for n in nodes:
        if _is_excluded(n):
            continue
        if n.width <= int(0.45 * screen_w) and n.height <= int(0.16 * screen_h):
            if _norm(n.text) in _NEXT_AD_LABELS or _norm(n.desc) in _NEXT_AD_LABELS:
                next_ad_candidates.append(n)
    if next_ad_candidates:
        target = next_ad_candidates[0]
        x1, y1, x2, y2 = target.bounds
        tap_x = min(screen_w - 10, x2 + 16) if x2 < screen_w - 28 else (x1 + x2) // 2
        return AdSignal("ad_ui_close", (tap_x, (y1 + y2) // 2), raw_point=True)

    if not reward_granted:
        for n in nodes:
            combined = f"{n.text} {n.desc}".strip()
            if not combined:
                continue
            if any(pat.search(combined) for pat in _COUNTDOWN_PATTERNS):
                return AdSignal("countdown_active")
            if (ad_elapsed < 32.0
                    and n.bounds[3] <= int(0.18 * screen_h)
                    and n.width <= int(0.25 * screen_w)
                    and _SHORT_TIMER_RE.match(_norm(n.text))):
                return AdSignal("countdown_active")

    # 3A. Explicit close / dismiss / skip controls by text, content-desc, or resource-id.
    max_btn_w = max(160, int(0.36 * screen_w))
    max_btn_h = max(110, int(0.16 * screen_h))
    explicit = []
    for n in nodes:
        if n.width > max_btn_w or n.height > max_btn_h or _is_excluded(n):
            continue
        t_norm, d_norm = _norm(n.text), _norm(n.desc)
        res_tail = n.res_id.rsplit("/", 1)[-1].lower()
        priority = None
        if t_norm in _CLOSE_SYMBOLS or d_norm in _CLOSE_SYMBOLS:
            priority = 0
        elif t_norm in _CLOSE_LABELS or d_norm in _CLOSE_LABELS:
            priority = 1
        elif any(tok in res_tail for tok in _CLOSE_ID_TOKENS) and "confirm" not in res_tail:
            priority = 1 if "skip" not in res_tail else 2
        elif t_norm in _SKIP_SYMBOLS or d_norm in _SKIP_SYMBOLS:
            priority = 2
        elif t_norm in _SKIP_LABELS or d_norm in _SKIP_LABELS:
            priority = 2
        if priority is not None:
            cx, cy = n.center
            in_top = 0 if cy <= int(0.22 * screen_h) else 1
            explicit.append((priority, in_top, 0 if n.clickable else 1, n.width * n.height, n))

    if explicit:
        explicit.sort(key=lambda item: item[:4])
        best = explicit[0][4]
        kind = "reward_granted" if reward_granted else "ad_ui_close"
        return AdSignal(kind, best.center, raw_point=True)

    # 3B. Adjoining X button next to "Reward granted" / "Đã trao phần thưởng" pill.
    for r_node in reward_nodes:
        rx1, ry1, rx2, ry2 = r_node.bounds
        if ry2 > int(0.24 * screen_h):
            continue
        rcy = (ry1 + ry2) // 2
        siblings = []
        for n in nodes:
            if n is r_node or _is_excluded(n):
                continue
            if not (10 <= n.width <= 110 and 10 <= n.height <= 110):
                continue
            ncx, ncy = n.center
            if abs(ncy - rcy) <= max(r_node.height, 38) and rx1 - 60 <= ncx <= rx2 + 100:
                siblings.append((0 if ncx >= rx2 - 20 else 1, -ncx, n))
        if siblings:
            siblings.sort(key=lambda item: item[:2])
            return AdSignal("reward_granted", siblings[0][2].center, raw_point=True)
        if 80 <= r_node.width <= int(0.55 * screen_w) and r_node.height <= 80:
            tap_x = min(screen_w - 10, rx2 - max(14, r_node.height // 2))
            return AdSignal("reward_granted", (tap_x, rcy), raw_point=True)

    # 3C. Unlabeled compact corner icon button when reward is granted or ad finished playing.
    if reward_granted or ad_elapsed >= 16.0 or (ad_elapsed >= 6.0 and static_duration >= 1.2):
        corner_btns = []
        for n in nodes:
            if _is_excluded(n) or n.text.strip() or n.desc.strip():
                continue
            if not (16 <= n.width <= 108 and 16 <= n.height <= 108):
                continue
            ratio = n.width / n.height
            if not (0.55 <= ratio <= 1.85):
                continue
            cx, cy = n.center
            if cy > int(0.15 * screen_h):
                continue
            in_right = cx >= int(0.85 * screen_w)
            in_left = cx <= int(0.15 * screen_w)
            if not (in_right or in_left):
                continue
            is_button_cls = any(
                 n.cls.endswith(suffix)
                 for suffix in ("Button", "ImageButton", "ImageView")
            )
            if not (n.clickable or is_button_cls):
                continue
            # Prefer top-right over top-left, clickable over non-clickable, rightmost/topmost.
            side_rank = 0 if in_right else 1
            click_rank = 0 if n.clickable else 1
            edge_dist = (screen_w - cx) if in_right else cx
            corner_btns.append((side_rank, click_rank, edge_dist + cy, n))
        if corner_btns:
            corner_btns.sort(key=lambda item: item[:3])
            kind = "reward_granted" if reward_granted else "ad_ui_close"
            return AdSignal(kind, corner_btns[0][3].center, raw_point=True)

    return None


def dump_ui_xml(adb: Path, serial: str, timeout: float = 3.0) -> str:
    try:
        out = adb_run(adb, serial, "exec-out", "uiautomator", "dump", "/dev/tty", timeout=timeout)
        text = out.decode(errors="replace")
        if "<hierarchy" in text and "</hierarchy>" in text:
            return text
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        remote = "/data/local/tmp/autogc-ui.xml"
        out = adb_run(
            adb, serial, "shell",
            f"uiautomator dump {remote} >/dev/null 2>&1 && cat {remote}",
            timeout=timeout + 1.0,
        )
        return out.decode(errors="replace")
    except (OSError, subprocess.SubprocessError):
        return ""


def _box_sum(integral: np.ndarray, kh: int, kw: int) -> np.ndarray:
    return (
        integral[kh:, kw:]
        - integral[:-kh, kw:]
        - integral[kh:, :-kw]
        + integral[:-kh, :-kw]
    )


def _zncc_search(patch_gray: np.ndarray, kernel: np.ndarray) -> tuple[float, int, int]:
    kh, kw = kernel.shape
    ph, pw = patch_gray.shape
    if ph < kh or pw < kw:
        return -1.0, 0, 0
    k = kernel.astype(np.float32)
    k_zero = k - k.mean()
    k_norm = float(np.sqrt(np.sum(k_zero * k_zero)))
    if k_norm < 1e-3:
        return -1.0, 0, 0

    p64 = patch_gray.astype(np.float64)
    sat = np.pad(p64, ((1, 0), (1, 0))).cumsum(axis=0).cumsum(axis=1)
    sat2 = np.pad(p64 * p64, ((1, 0), (1, 0))).cumsum(axis=0).cumsum(axis=1)
    n_pix = float(kh * kw)
    w_sum = _box_sum(sat, kh, kw)
    w_sum2 = _box_sum(sat2, kh, kw)
    w_var_sum = np.maximum(0.0, w_sum2 - (w_sum * w_sum) / n_pix)
    w_std = np.sqrt(w_var_sum)
    # Require meaningful local contrast (>= 16 gray std across the icon patch).
    min_norm = 16.0 * np.sqrt(n_pix)
    valid = w_std >= min_norm
    if not np.any(valid):
        return -1.0, 0, 0
    windows = np.lib.stride_tricks.sliding_window_view(patch_gray, (kh, kw))
    numer = np.tensordot(windows, k_zero, axes=((-2, -1), (0, 1)))
    scores = np.where(valid, numer / (w_std * k_norm + 1e-6), -1.0)
    iy, ix = np.unravel_index(np.argmax(scores), scores.shape)
    return float(scores[iy, ix]), int(ix), int(iy)


def _synthetic_x_kernel(size: int, stroke: float = 2.0) -> np.ndarray:
    c = (size - 1) / 2.0
    yy, xx = np.mgrid[0:size, 0:size]
    dx = xx - c
    dy = yy - c
    r = np.hypot(dx, dy)
    arm_len = size * 0.34
    d1 = np.abs(dx - dy) / np.sqrt(2.0)
    d2 = np.abs(dx + dy) / np.sqrt(2.0)
    on_x = ((d1 <= stroke * 0.55) | (d2 <= stroke * 0.55)) & (np.maximum(np.abs(dx), np.abs(dy)) <= arm_len)
    in_disc = r <= size * 0.46
    kernel = np.zeros((size, size), dtype=np.float32)
    kernel[in_disc] = -0.35
    kernel[on_x] = 1.0
    return kernel


def _verify_x_geometry(patch_gray: np.ndarray, cx: int, cy: int, arm_radius: int) -> bool:
    h, w = patch_gray.shape
    r = arm_radius
    if cx - r < 1 or cx + r >= w - 1 or cy - r < 1 or cy + r >= h - 1:
        return False
    diag_vals = []
    for d in range(2, r + 1):
        diag_vals.extend((
            patch_gray[cy - d, cx - d],
            patch_gray[cy - d, cx + d],
            patch_gray[cy + d, cx - d],
            patch_gray[cy + d, cx + d],
        ))
    diag_vals.append(patch_gray[cy, cx])
    wedges = [
        [patch_gray[cy - d, cx] for d in range(3, r + 1)],
        [patch_gray[cy + d, cx] for d in range(3, r + 1)],
        [patch_gray[cy, cx - d] for d in range(3, r + 1)],
        [patch_gray[cy, cx + d] for d in range(3, r + 1)],
    ]
    if any(not w_list for w_list in wedges):
        return False
    diag_mean = float(np.mean(diag_vals))
    wedge_means = [float(np.mean(w_list)) for w_list in wedges]
    wedge_std = float(np.std([v for w_list in wedges for v in w_list]))
    if wedge_std > 30.0:
        return False
    # Either bright X on all 4 darker wedges, or dark X on all 4 brighter wedges.
    bright_x = all(diag_mean - wm >= 30.0 for wm in wedge_means)
    dark_x = all(wm - diag_mean >= 30.0 for wm in wedge_means)
    return bright_x or dark_x


class VisualCloseDetector:
    """Detect standalone X close buttons in top corners on both 16:9 and 9:16 screens."""

    def __init__(self, atlas_path: Path | None = None):
        path = atlas_path or Path(__file__).with_name("play_templates.npz")
        self.icon_templates: list[tuple[np.ndarray, tuple[int, int], float]] = []
        if path.is_file():
            with np.load(path, allow_pickle=False) as atlas:
                specs = (
                    ("ad_end_close", slice(None), slice(None), (20, 20), 0.80),
                    ("ad_sheet_close", slice(None), slice(None), (20, 20), 0.80),
                    ("reward", slice(None), slice(168, None), (14, 14), 0.81),
                    ("reward_mixed", slice(None), slice(168, 198), (15, 16), 0.81),
                    ("reward_light", slice(None), slice(142, None), (14, 12), 0.82),
                )
                for name, ys, xs, center, threshold in specs:
                    if name not in atlas:
                        continue
                    base = atlas[name][ys, xs].mean(axis=2).astype(np.float32)
                    pil_base = Image.fromarray(np.clip(base, 0, 255).astype(np.uint8), "L")
                    for scale in (1.0, 0.85, 1.15):
                        sw = max(14, round(pil_base.width * scale))
                        sh = max(14, round(pil_base.height * scale))
                        resized = np.asarray(pil_base.resize((sw, sh), Image.Resampling.BILINEAR), dtype=np.float32)
                        sc = (round(center[0] * scale), round(center[1] * scale))
                        self.icon_templates.append((resized, sc, threshold))

        self.synthetic_kernels = []
        for size, arm_r in ((21, 6), (27, 8), (33, 10)):
            kern = _synthetic_x_kernel(size)
            c = size // 2
            self.synthetic_kernels.append((kern, c, arm_r))
            self.synthetic_kernels.append((-kern, c, arm_r))

    def find_close(self, image: Image.Image) -> tuple[int, int] | None:
        orig_w, orig_h = image.size
        if orig_w < 240 or orig_h < 240:
            return None
        short_side = min(orig_w, orig_h)
        scale = 720.0 / short_side
        norm_w = round(orig_w * scale)
        norm_h = round(orig_h * scale)
        gray_img = image.convert("L")
        if (norm_w, norm_h) != (orig_w, orig_h):
            gray_img = gray_img.resize((norm_w, norm_h), Image.Resampling.BILINEAR)
        gray = np.asarray(gray_img, dtype=np.float32)

        # Search top-right first, then top-left.
        corners = (
            (max(0, norm_w - 136), 4, norm_w - 2, min(norm_h, 108)),
            (2, 4, min(norm_w, 136), min(norm_h, 108)),
        )
        for x0, y0, x1, y1 in corners:
            patch = gray[y0:y1, x0:x1]
            best_score = -1.0
            best_pt = None
            for tmpl, (cx_off, cy_off), threshold in self.icon_templates:
                score, ix, iy = _zncc_search(patch, tmpl)
                if score >= threshold and score > best_score:
                    best_score = score
                    best_pt = (x0 + ix + cx_off, y0 + iy + cy_off)
            if best_pt is not None:
                return (
                    round(best_pt[0] / scale),
                    round(best_pt[1] / scale),
                )

        for x0, y0, x1, y1 in corners:
            patch = gray[y0:y1, x0:x1]
            for kern, half, arm_r in self.synthetic_kernels:
                score, ix, iy = _zncc_search(patch, kern)
                if score >= 0.78:
                    cx, cy = ix + half, iy + half
                    if _verify_x_geometry(patch, cx, cy, arm_r):
                        return (
                            round((x0 + cx) / scale),
                            round((y0 + cy) / scale),
                        )
        return None


class AdCloser:
    """Coordinate motion tracking, uiautomator inspection, visual X matching, and BACK fallback."""

    def __init__(self, atlas_path: Path | None = None):
        self.visual = VisualCloseDetector(atlas_path)
        self._prev_thumb: np.ndarray | None = None
        self._static_since: float | None = None
        self._ad_started_at: float | None = None
        self._last_xml_check: float = float("-inf")
        self._last_xml_signal: AdSignal | None = None
        self._last_visual_check: float = float("-inf")
        self._last_visual_point: tuple[int, int] | None = None
        self._resume_cooldown_until: float = float("-inf")

    def reset(self):
        self._prev_thumb = None
        self._static_since = None
        self._ad_started_at = None
        self._last_xml_check = float("-inf")
        self._last_xml_signal = None
        self._last_visual_check = float("-inf")
        self._last_visual_point = None
        self._resume_cooldown_until = float("-inf")

    def _update_motion(self, time: float, image: Image.Image) -> tuple[float, float]:
        if self._ad_started_at is None:
            self._ad_started_at = time
        w, h = image.size
        thumb_size = (120, 68) if w >= h else (68, 120)
        thumb = np.asarray(
            image.convert("L").resize(thumb_size, Image.Resampling.BILINEAR),
            dtype=np.float32,
        )
        if self._prev_thumb is None or self._prev_thumb.shape != thumb.shape:
            self._prev_thumb = thumb
            self._static_since = time
            self._last_xml_signal = None
            self._last_visual_check = float("-inf")
            self._last_visual_point = None
        else:
            p80_diff = float(np.percentile(np.abs(thumb - self._prev_thumb), 80))
            self._prev_thumb = thumb
            if p80_diff >= 3.5:
                self._static_since = time
                self._last_xml_signal = None
                self._last_visual_check = float("-inf")
                self._last_visual_point = None
            elif self._static_since is None:
                self._static_since = time
        ad_elapsed = max(0.0, time - self._ad_started_at)
        static_duration = max(0.0, time - (self._static_since if self._static_since is not None else time))
        return ad_elapsed, static_duration

    def inspect(
        self,
        time: float,
        original: Image.Image | None,
        *,
        adb: Path | None = None,
        serial: str | None = None,
        ad_foreground: bool = False,
    ) -> AdSignal | None:
        if original is None:
            return None
        ad_elapsed, static_duration = self._update_motion(time, original)
        if time < self._resume_cooldown_until:
            return None

        # Layer 2: Android UI hierarchy (accurate across all languages and portrait/landscape).
        countdown_active = False
        if adb is not None and serial is not None:
            should_poll_xml = (
                (time - self._last_xml_check >= 1.6)
                and ((ad_elapsed >= 4.5 and static_duration >= 0.75) or ad_elapsed >= 14.0)
            )
            if should_poll_xml:
                self._last_xml_check = time
                xml_text = dump_ui_xml(adb, serial)
                self._last_xml_signal = analyze_ad_xml(
                    xml_text,
                    original.width,
                    original.height,
                    ad_elapsed=ad_elapsed,
                    static_duration=static_duration,
                )
            sig = self._last_xml_signal
            if sig is not None:
                if sig.kind == "ad_resume":
                    self._last_xml_signal = None
                    self._resume_cooldown_until = time + 5.0
                    return sig
                if sig.kind == "countdown_active":
                    countdown_active = True
                else:
                    return sig

        if countdown_active:
            return None

        # Layer 3: Visual standalone corner X detector (handles WebGL/MRAID/Canvas & offline preview).
        if (ad_elapsed >= 5.5 and static_duration >= 1.1) or ad_elapsed >= 20.0:
            if time - self._last_visual_check >= 0.45:
                self._last_visual_check = time
                self._last_visual_point = self.visual.find_close(original)
            if self._last_visual_point is not None:
                return AdSignal("ad_visual_close", self._last_visual_point, raw_point=True)

        # Layer 4: Safe KEYCODE_BACK fallback when an ad activity stays frozen after completion.
        if ad_foreground and ad_elapsed >= 32.0 and static_duration >= 3.0:
            return AdSignal("ad_back", None, raw_point=True, keyevent=KEYCODE_BACK)

        return None
