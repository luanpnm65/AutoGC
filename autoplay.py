"""Play Grow Castle waves, cast ready skills, and collect gold ads on BlueStacks 5 or LDPlayer 9."""

import argparse
import base64
from dataclasses import dataclass, replace
from io import BytesIO
from hashlib import sha256
from pathlib import Path
import subprocess
from time import monotonic, sleep
import zlib

import numpy as np
from PIL import Image, ImageOps

from ad_closer import AdCloser, KEYCODE_BACK
from bluestacks_captcha import watch_target
from captcha import VIEWPORT
from emulator import (
    AD_OVERLAY_PACKAGES,
    adb_run,
    ensure_adb_connected,
    foreground_activity,
    foreground_window,
    format_instances,
    is_ad_activity,
    resolve_target,
)
from tower_upgrade import Action, TowerUpgrade, lock_journal
from tower_vision import load_gem_templates, read_white_gems
from windows_video import read_video


TEMPLATES = {
    "hud": ((0, 6, 29, 36), 17),
    "hud_dim": ((0, 6, 29, 36), 10),
    "upgrade": ((924, 94, 1217, 129), 25),
    "battle": ((1126, 673, 1256, 702), 20),
    "replay": ((951, 673, 1083, 702), 20),
    "wave": ((615, 40, 707, 68), 13),
    "wave_late": ((615, 40, 707, 68), 0),
    "speed": ((25, 634, 96, 680), 17),
    "gold_coin": ((253, 617, 322, 681), 14),
    "gold_get": ((565, 620, 688, 655), 14),
    "gold_get_centered": ((562, 625, 690, 678), 17),
    "replay_100": ((804, 633, 919, 669), 19),
    "replay_80": ((957, 633, 1072, 669), 19),
    "skip_title": ((475, 242, 797, 294), 16),
    "skip_close": ((866, 194, 911, 238), 17),
    "victory": ((457, 232, 827, 310), 18),
    "processing": ((466, 260, 831, 311), 20),
    "captcha": ((407, 91, 867, 129), 16),
    "captcha_start": ((847, 536, 1003, 623), 14),
    "hp_zero": ((918, 7, 938, 29), 0),
    "reward": ((1068, 26, 1266, 56), 0),
    "reward_light": ((1098, 30, 1268, 54), 0),
    "reward_mixed": ((1060, 22, 1262, 53), 0),
    "ad_end_close": ((1237, 22, 1277, 62), 15),
    "ad_end_cta": ((247, 651, 393, 680), 15),
    "ad_sheet_close": ((1237, 19, 1277, 59), 14),
    "ad_sheet_chevron": ((1219, 136, 1245, 159), 15),
    "ad_sheet_cta": ((958, 535, 1162, 589), 16),
}
GOLD_HUD = (36, 4, 194, 39)
BOSS_BAR_REGION = (360, 30, 780, 78)
BOSS_FFT_SHAPE = (64, 512)
# Invariant white strokes ('#') and dark outline ('@') of the BOSS health bar label;
# '.' marks the HP fill area so matching succeeds whether Boss HP is full red or empty black.
BOSS_GLYPH = (
    ".@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@",
    "@@.........@@@@@.......@@@@@.........@@@@........",
    "@.########.@@@@@.#####.@@@@@.#######.@@@.########",
    "@.########...@@..#####...@...#######.@@..########",
    "@.##......##.@.##.....##.@.##........@.##........",
    "@.##.@..@.##.@.##@...@##.@.##@.........##.@......",
    "@.##.@....##.@.##@...@##.@.##@.........##.@......",
    "@.##......##.@.##@...@##.@.#.......@...##......@.",
    "@.########..@@.##@...@##.@...#####.@.....######.@",
    "@.########...@.##@...@##...@.#####...@...######..",
    "@.##.@@@@.##.@.##@...@##....@@@@@@.#.@..@@@@@@.##",
    "@.##.@....##.@.##@...@##.........@.#.@.........##",
    "@.##.@@@@.##.@.##@...@##.@@@@@@@@@.#.@@@@@@@@@.##",
    "@.##......##.@.##.....##.@.........#.@.........##",
    "@.########..@@...#####...@.#######...@.########..",
    "@.########.@@@@@.#####.@@@.#######.@@@.########.@",
    "@@.........@@@@@......@@@@.........@@@.........@@",
    "..@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@",
)
ARCHER_SKILLS = (
    ("archer skill 1", 135, 363, 405),
    ("archer skill 2", 135, 480, 522),
)
HERO_SKILLS = tuple(
    (f"skill {idx}", x, bar_y, hero_y)
    for idx, (x, bar_y, hero_y) in enumerate(
        ((x, bar_y, hero_y) for bar_y, hero_y in ((146, 184), (241, 277), (331, 370))
         for x in (293, 373, 453)),
        start=1,
    )
)
SKILLS = ARCHER_SKILLS + HERO_SKILLS
GAME_SCREENS = {"home", "gold", "replay_menu", "battle", "skip"}
RETURN_SCREENS = GAME_SCREENS | {"victory", "defeat", "tower", "castles", "captcha"}
AD_CLOSE_SCREENS = {
    "reward_granted",
    "ad_end_card",
    "ad_end_sheet",
    "ad_ui_close",
    "ad_visual_close",
    "ad_back",
    "ad_external_overlay",
}
SKIP_CLOSE_POINT = (888, 216)
SKIP_30_POINT = (809, 365)
SKIP_GEM_THRESHOLD = 30
SKIP_30_MASK_SHAPE = (35, 72)
SKIP_30_MASK_B85 = (
    "c-muNfPwn|e;De2fEoW7fNboHKP><MgH$sg;0I!y40aI1hJl~K9>k~tGU`znHZTVJ0e<H9P+jcp="
    "#2JeFyjG#KbXN_$Nz&FKcfQ3Xn-*oFc~0+)uh+3?`LlSTK@k4#9!DM^?w-f0RY<jPOk"
)
# Background-masked 28x28 RGB + 1-bit mask of the open Mimic chest (mouth, fangs, tongue, lid).
MIMIC_TEMPLATE_B85 = (
    "c-pO%Eo|FB6vtmwsU4V<0|z`Q+6o2+3IYraPMRlKnn8epfx&?T2Mi1h3<9j~fPsOf83Ysr1Ox;G1"
    "QY}m1QY}m1Qc{q!6p?H6a*IR>s{KdYn9ebvZs@B@%es!U-v(NCFVQSV<cdNGa@V^ZITEI8<=oOCP"
    "@*JoRi!qS&O6&!RK8;V|N{L5s^uGZ{tyH^a6U|({X5wLZj`hj6Ll=+%k!cqsSNvIuH~m<H&%`3_a"
    "{~dKenx#X#n9VxZ@^#7(j`7MVCkl8zTn4khh!3L9Hr&{3$FIO%ZGkz{jb$w^mdfFiTNPVoK%6HR%"
    "v6VSpVZHE+|jvd{`gxsvg_R3#L7?+k6+KseDN}rYsrY_u{9%!>_X58}s{hPItuqi^;R0s@o9<WmA"
    "BsN&rr<p^L*|yhA$fQF@+3ntrPji<lo1|>PWNR{eDV_H2_9|B&+tjXL9`k(V^0jo}$V}ZkY`~iOR"
    "LbI1mP4<-es8p1-U*TA90lq;EKfwyaU!i7K{oW#12<lq-)8<yXeTl7k(W+*e(0;*4wtutRedl;(9"
    "CUdCQHOld5&0QcHKmp-qQC&^I5u7I1-sBnyCi{zMN+53UdXaLnkYlYuM(@fm)Jk%qKD@L3ZH8e9w"
    "ujM#3s8l6VbW6lR2shEE=)*bJm;c7sO$zWid*qes4yIB(-emUz?RdsbvMJN_;z4~_>f;APhhj2<@"
    "z;<@z_0pZrIlpRWaYYeJxirH*7pU<b$<LU<UP|A!OH7i<AVF!c$#l^+d)m62_s0<E<N&8RwsoX{y"
    "1~|FAynI$3JR%uUu2$VgnKp^tcQ^CD*xGl1_aoSTqu|3ePG^fJ^$7s}?0f<EQP%3e6ui2I+Gk}0;"
    "{YGe0X`{JzkUJxTd?&N;5C5#6L{^Ln(WtMd%mUW%7Xc}+EMa1j!_zi"
)


def viewport(image):
    width, height = image.size
    if abs(width / height / (16 / 9) - 1) > 0.03:
        return None
    return image.convert("RGB").resize(VIEWPORT, Image.Resampling.BILINEAR)


def region(array, box):
    left, top, right, bottom = box
    return array[top:bottom, left:right]


def pale_pixels(rgb, minimum):
    return (rgb.max(axis=2) > minimum) & (np.ptp(rgb, axis=2) < 38)


def _box_sum_2d(integral, height, width):
    return (
        integral[height:, width:]
        - integral[:-height, width:]
        - integral[height:, :-width]
        + integral[:-height, :-width]
    )


@dataclass(frozen=True)
class Screen:
    name: str
    point: tuple[int, int] | None = None
    ready: tuple[int, ...] = ()
    gold: np.ndarray | None = None
    gems: int | None = None
    layout: str | None = None
    level: int | None = None
    cost: int | None = None
    mimic: tuple[int, int] | None = None
    skip_30: bool = False
    raw_point: bool = False
    keyevent: int | None = None


class Vision:
    def __init__(self, upgrade_tower=False):
        atlas_path = Path(__file__).with_name("play_templates.npz")
        with np.load(atlas_path, allow_pickle=False) as atlas:
            self.templates = {name: atlas[name].astype(np.int16) for name in TEMPLATES}
        self.zero = pale_pixels(self.templates["hp_zero"], 145)
        # The progress bar behind the WAVE label changes from white to black.
        self.wave_text = np.mean(np.abs(self.templates["wave"] - self.templates["wave_late"]),
                                 axis=2) < 14
        self.reward = Image.fromarray(self.templates["reward"].astype(np.uint8)).convert("L")
        light_reward = Image.fromarray(self.templates["reward_light"].astype(np.uint8)).convert("L")
        self.reward_light = ImageOps.invert(light_reward)
        self.reward_mixed = Image.fromarray(self.templates["reward_mixed"].astype(np.uint8)).convert("L")
        self.boss_kernels = self._build_boss_kernels()
        self.mimic_templates = self._build_mimic_templates()
        self.gem_templates = load_gem_templates()
        self.skip_30_mask = self._build_skip_30_mask()
        self.ad_closer = AdCloser(atlas_path)
        self.tower = None
        if upgrade_tower:
            from tower_vision import TowerVision

            self.tower = TowerVision()

    @staticmethod
    def _build_skip_30_mask():
        raw = zlib.decompress(base64.b85decode(SKIP_30_MASK_B85))
        total = SKIP_30_MASK_SHAPE[0] * SKIP_30_MASK_SHAPE[1]
        return np.unpackbits(np.frombuffer(raw, dtype=np.uint8))[:total].reshape(SKIP_30_MASK_SHAPE).astype(bool)

    def white_gems(self, rgb):
        return read_white_gems(rgb, self.gem_templates)

    def matches_skip_30(self, rgb):
        button = rgb[316:415, 758:862]
        red, green, blue = button[:, :, 0], button[:, :, 1], button[:, :, 2]
        gold = (red > 180) & (green > 115) & (blue < 75) & (red - blue > 120)
        if gold.mean() < 0.42:
            return False
        height, width = self.skip_30_mask.shape
        for dy in range(-3, 4):
            for dx in range(-3, 4):
                sub = rgb[335 + dy:335 + dy + height, 774 + dx:774 + dx + width]
                observed = (sub.min(axis=2) > 175) & (np.ptp(sub, axis=2) < 42)
                denom = np.count_nonzero(observed | self.skip_30_mask)
                if denom > 0 and np.count_nonzero(observed & self.skip_30_mask) / denom >= 0.65:
                    return True
        return False

    @staticmethod
    def _build_boss_kernels():
        white_base = Image.fromarray(
            np.array([[255 if ch == "#" else 0 for ch in row] for row in BOSS_GLYPH], dtype=np.uint8),
            "L",
        )
        dark_base = Image.fromarray(
            np.array([[255 if ch == "@" else 0 for ch in row] for row in BOSS_GLYPH], dtype=np.uint8),
            "L",
        )
        kernels = []
        for scale in (0.95, 1.10, 1.25, 1.38, 1.48):
            size = (round(white_base.width * scale), round(white_base.height * scale))
            white = np.asarray(white_base.resize(size, Image.Resampling.BILINEAR), dtype=np.float32) / 255.0
            dark = np.asarray(dark_base.resize(size, Image.Resampling.BILINEAR), dtype=np.float32) / 255.0
            mask = ((white > 0.45) | (dark > 0.45)).astype(np.float32)
            target = np.where(white > dark, 1.0, 0.0).astype(np.float32)
            m_sum = float(mask.sum())
            t_mean = float((target * mask).sum() / m_sum)
            k_zero = (target - t_mean) * mask
            k_norm = float(np.sqrt(np.sum(k_zero * k_zero)))
            k_fft = np.fft.rfft2(k_zero[::-1, ::-1], s=BOSS_FFT_SHAPE)
            m_fft = np.fft.rfft2(mask[::-1, ::-1], s=BOSS_FFT_SHAPE)
            kernels.append((size[1], size[0], k_fft, m_fft, m_sum, k_norm))
        return tuple(kernels)

    def matches_boss(self, rgb):
        # min(R, G, B) maps white BOSS strokes high (~250) and both black outline (~15)
        # and red/empty HP fill (~20..77) low, while ignoring unmasked fill pixels.
        patch = region(rgb, BOSS_BAR_REGION).min(axis=2).astype(np.float32)
        if patch.max() - patch.min() < 70:
            return False
        p_fft = np.fft.rfft2(patch, s=BOSS_FFT_SHAPE)
        p2_fft = np.fft.rfft2(patch * patch, s=BOSS_FFT_SHAPE)
        ph, pw = patch.shape
        for kh, kw, k_fft, m_fft, m_sum, k_norm in self.boss_kernels:
            numer = np.fft.irfft2(p_fft * k_fft, s=BOSS_FFT_SHAPE)[kh - 1:ph, kw - 1:pw]
            w_sum = np.fft.irfft2(p_fft * m_fft, s=BOSS_FFT_SHAPE)[kh - 1:ph, kw - 1:pw]
            w_sum2 = np.fft.irfft2(p2_fft * m_fft, s=BOSS_FFT_SHAPE)[kh - 1:ph, kw - 1:pw]
            w_std = np.sqrt(np.maximum(0.0, w_sum2 - (w_sum * w_sum) / m_sum))
            valid = w_std >= 28.0 * np.sqrt(m_sum)
            if not np.any(valid):
                continue
            corr = np.where(valid, numer / (w_std * k_norm + 1e-6), -1.0)
            if corr.max() >= 0.78:
                return True
        return False

    @staticmethod
    def _build_mimic_templates():
        raw = zlib.decompress(base64.b85decode(MIMIC_TEMPLATE_B85))
        rgb28 = np.frombuffer(raw[:28 * 28 * 3], dtype=np.uint8).reshape((28, 28, 3))
        mask28 = np.unpackbits(np.frombuffer(raw[28 * 28 * 3:], dtype=np.uint8))[:28 * 28].reshape((28, 28))
        pil_rgb = Image.fromarray(rgb28, "RGB")
        pil_msk = Image.fromarray((mask28 * 255).astype(np.uint8), "L")
        templates = []
        for scale in (0.78, 0.92, 1.08, 1.25, 1.45):
            sz = max(14, round((56.0 / 3.0) * scale))
            trgb = np.asarray(pil_rgb.resize((sz, sz), Image.Resampling.BILINEAR), dtype=np.float32)
            tmsk = (np.asarray(pil_msk.resize((sz, sz), Image.Resampling.BILINEAR)) > 175).astype(np.float32)
            tm = trgb * tmsk[:, :, None]
            tm_norm2 = float(np.sum(tm * tm))
            m_count = float(tmsk.sum() * 3.0)
            templates.append((sz, tmsk, tm, tm_norm2, m_count))
        return tuple(templates)

    def find_mimic(self, rgb):
        y0, x0 = 88, 24
        sub = rgb[y0:685:3, x0:1257:3]
        r, g, b = sub[:, :, 0], sub[:, :, 1], sub[:, :, 2]
        tongue = (r > 155) & (g > 65) & (g < 160) & (r - g > 48) & (r - b > 15) & (b - g > 8)
        gums = (r > 90) & (b > 100) & (g < 85) & (b - g > 38) & (r - g > 30)
        win = 22
        s_gums = _box_sum_2d(np.pad(gums.astype(np.int32), ((1, 0), (1, 0))).cumsum(0).cumsum(1), win, win)
        if s_gums.max() < 2:
            return None
        s_tongue = _box_sum_2d(np.pad(tongue.astype(np.int32), ((1, 0), (1, 0))).cumsum(0).cumsum(1), win, win)
        if s_tongue.max() < 3:
            return None
        wood = (r > 118) & (g > 52) & (b < 75) & (r - b > 75) & (g - b > 18)
        s_wood = _box_sum_2d(np.pad(wood.astype(np.int32), ((1, 0), (1, 0))).cumsum(0).cumsum(1), win, win)
        mx = np.maximum(np.maximum(r, g), b)
        mn = np.minimum(np.minimum(r, g), b)
        white = (mn > 185) & (mx - mn < 40)
        s_white = _box_sum_2d(np.pad(white.astype(np.int32), ((1, 0), (1, 0))).cumsum(0).cumsum(1), win, win)
        hand_shifted = np.pad(s_white, ((0, 8), (0, 8)))[4:4 + s_tongue.shape[0], 4:4 + s_tongue.shape[1]]

        cand = (s_gums >= 2) & (s_tongue >= 3) & (s_wood >= 14) & (hand_shifted >= 4)
        if not np.any(cand):
            return None

        ys, xs = np.where(cand)
        scores = (s_tongue[ys, xs] + s_gums[ys, xs]) * 3 + s_wood[ys, xs]
        order = np.argsort(scores)[::-1]
        checked = []
        best_rmse = 36.0
        best_pt = None
        sh, sw, _ = sub.shape
        sub_f = sub.astype(np.float32)
        sub_f2 = np.sum(sub_f * sub_f, axis=2)
        for idx in order:
            cy, cx = int(ys[idx]), int(xs[idx])
            if any(abs(cy - py) < 12 and abs(cx - px) < 12 for py, px in checked):
                continue
            checked.append((cy, cx))
            for sz, tmsk, tm, tm_norm2, m_count in self.mimic_templates:
                ry0 = max(0, cy - 7)
                rx0 = max(0, cx - 7)
                ry1 = min(sh, cy + 8 + sz)
                rx1 = min(sw, cx + 8 + sz)
                if ry1 - ry0 < sz or rx1 - rx0 < sz:
                    continue
                roi = sub_f[ry0:ry1, rx0:rx1]
                roi2 = sub_f2[ry0:ry1, rx0:rx1]
                w_rgb = np.lib.stride_tricks.sliding_window_view(roi, (sz, sz, 3))[:, :, 0]
                w_p2 = np.lib.stride_tricks.sliding_window_view(roi2, (sz, sz))
                p_energy = np.tensordot(w_p2, tmsk, axes=((-2, -1), (0, 1)))
                cross = np.tensordot(w_rgb, tm, axes=((-3, -2, -1), (0, 1, 2)))
                mse = np.maximum(0.0, (p_energy - 2.0 * cross + tm_norm2) / m_count)
                min_idx = np.unravel_index(np.argmin(mse), mse.shape)
                rmse = float(np.sqrt(mse[min_idx]))
                if rmse < best_rmse:
                    best_rmse = rmse
                    py = ry0 + int(min_idx[0])
                    px = rx0 + int(min_idx[1])
                    best_pt = (x0 + (px + sz // 2) * 3, y0 + (py + sz // 2) * 3)
            if len(checked) >= 3:
                break
        return best_pt

    def matches(self, rgb, name, offset_y=0):
        box, tolerance = TEMPLATES[name]
        if offset_y:
            left, top, right, bottom = box
            box = (left, top + offset_y, right, bottom + offset_y)
        template = self.templates[name]
        difference = np.abs(region(rgb, box) - template)
        if name != "wave":
            return np.mean(difference) < tolerance
        if np.mean(difference[self.wave_text]) < tolerance:
            return True
        # The top HUD text in native ADB captures is one pixel below the
        # recorded MP4 samples and has sharper edges.
        left, top, right, bottom = box
        shifted = region(rgb, (left, top + 1, right, bottom + 1))
        return np.mean(np.abs(shifted - template)[self.wave_text]) < 20

    def hp_empty(self, rgb, dim):
        threshold = 53 if dim else 145
        left, top, right, bottom = TEMPLATES["hp_zero"][0]
        if not any(np.count_nonzero(pale_pixels(rgb[top + dy:bottom + dy, left:right],
                                                threshold) ^ self.zero) <= 42
                   for dy in (0, 1)):
            return False
        bar = rgb[8:28, 657:917]
        red, green, blue = bar.transpose(2, 0, 1)
        health = (red > (65 if dim else 130)) & (red - blue > (35 if dim else 80))
        return health.sum() < 6 and pale_pixels(bar, threshold).sum() < 8

    def reward_close(self, image):
        # Search only the player chrome for the full label and the adjoining X.
        left, top = 902, 8
        chrome = image.crop((left, top, 1280, 106)).convert("L")
        point = self.match_reward(chrome, self.reward, 168, (182, 14))
        if point is None:
            point = self.match_reward(ImageOps.invert(chrome), self.reward_light, 143, (156, 12))
        if point is None:
            point = self.match_reward(chrome, self.reward_mixed, 163, (183, 16), dark_x=True)
        if point is not None:
            return left + point[0], top + point[1]
        return None

    @staticmethod
    def match_reward(chrome, template, close_start, close_center, dark_x=False):
        field = np.asarray(chrome) > 165
        fft_size = (128, 640)
        field_fft = np.fft.rfft2(field.astype(np.float32), s=fft_size, axes=(0, 1))
        integral = np.pad(field.cumsum(axis=0).cumsum(axis=1), ((1, 0), (1, 0)))
        for scale in (1.0, 0.85, 1.15):
            size = (round(template.width * scale), round(template.height * scale))
            mask = np.asarray(template.resize(size, Image.Resampling.BILINEAR)) > 165
            height, width = mask.shape
            kernel = np.fft.rfft2(mask.astype(np.float32), s=fft_size, axes=(0, 1))
            overlap = np.fft.irfft2(field_fft * kernel.conj(), s=fft_size, axes=(0, 1))
            count = (integral[height:, width:] - integral[:-height, width:]
                     - integral[height:, :-width] + integral[:-height, :-width])
            score = 2 * overlap[:count.shape[0], :count.shape[1]] / (count + mask.sum())
            y, x = np.unravel_index(score.argmax(), score.shape)
            if score[y, x] < 0.83:
                continue
            x_start = round(close_start * scale)
            close = field[y:y + height, x + x_start:x + width]
            expected = mask[:, x_start:]
            if 2 * (close & expected).sum() < 0.76 * (close.sum() + expected.sum()):
                continue
            cx, cy = (round(coordinate * scale) for coordinate in close_center)
            if dark_x:
                # The bright circle alone is a match. Check the dark X inside it.
                radius = round(8 * scale)
                glyph = ~field[y + cy-radius:y + cy+radius+1, x + cx-radius:x + cx+radius+1]
                expected_x = ~mask[cy-radius:cy+radius+1, cx-radius:cx+radius+1]
                if 2 * (glyph & expected_x).sum() < 0.76 * (glyph.sum() + expected_x.sum()):
                    continue
            return int(x + cx), int(y + cy)
        return None

    def ad_end_close(self, rgb):
        # The two-card end screen replaces the playback progress and ad count
        # with an empty header and a standalone close button.
        if not self.matches(rgb, "ad_end_close"):
            return None
        header = rgb[:69, :1228]
        if np.max(np.mean(np.abs(header - header[0, 0]), axis=(1, 2))) > 8:
            return None
        template = self.templates["ad_end_cta"]
        height, width, _ = template.shape
        tolerance = TEMPLATES["ad_end_cta"][1]
        for left in (247, 888):
            if not any(np.mean(np.abs(rgb[top:top + height, left:left + width] - template))
                       < tolerance for top in range(578, 680)):
                return None
        return 1257, 42

    def home_screen(self, rgb):
        gold = region(rgb, GOLD_HUD)
        gems, layout = self.tower.home(rgb) if self.tower else (None, None)
        mimic = self.find_mimic(rgb)
        # The offer slides a few pixels as it appears after the results screen.
        for offset in (0, *range(-6, 0), *range(1, 7)):
            if self.matches(rgb, "gold_coin", offset) and (
                    self.matches(rgb, "gold_get", offset)
                    or self.matches(rgb, "gold_get_centered", offset)):
                return Screen(
                    "gold", (626, 649 + offset),
                    gold=gold, gems=gems, layout=layout, mimic=mimic,
                )
        return Screen("home", gold=gold, gems=gems, layout=layout, mimic=mimic)

    def captcha_start_visible(self, image):
        frame = viewport(image)
        if frame is None:
            return False
        rgb = np.asarray(frame, dtype=np.int16)
        return self.matches(rgb, "captcha") and self.matches(rgb, "captcha_start")

    def _classify_game_screen(self, rgb):
        if self.matches(rgb, "captcha"):
            return Screen("captcha")
        if self.matches(rgb, "processing"):
            return Screen("processing")
        if self.matches(rgb, "victory"):
            return Screen("victory")
        if self.tower is not None and (panel := self.tower.panel(rgb)):
            kind, gems, level, cost = panel
            return Screen(kind, gems=gems, level=level, cost=cost)
        hud = self.matches(rgb, "hud")
        dim = not hud and self.matches(rgb, "hud_dim")
        if (hud or dim) and self.hp_empty(rgb, dim):
            return Screen("defeat")
        if hud and self.matches(rgb, "skip_title") and self.matches(rgb, "skip_close"):
            return Screen(
                "skip",
                SKIP_CLOSE_POINT,
                gems=self.white_gems(rgb),
                skip_30=self.matches_skip_30(rgb),
            )
        if hud and self.matches(rgb, "upgrade"):
            if self.matches(rgb, "replay_100") and self.matches(rgb, "replay_80"):
                return Screen("replay_menu", (857, 623))
            if self.matches(rgb, "battle") and self.matches(rgb, "replay"):
                return self.home_screen(rgb)
        if self.tower is not None and self.tower.is_home(rgb):
            return self.home_screen(rgb)
        if hud and self.matches(rgb, "speed") and (
                self.matches(rgb, "wave") or self.matches_boss(rgb)):
            ready = []
            for index, (_, x, y, _) in enumerate(SKILLS):
                red, green, blue = rgb[y-2:y+3, x-24:x+25].transpose(2, 0, 1)
                cyan = (blue > 164) & (green > 105) & (blue - red > 65) & (green - red > 50)
                if cyan.mean() >= 0.92:
                    ready.append(index)
            return Screen("battle", ready=tuple(ready), mimic=self.find_mimic(rgb))
        return Screen("unknown")

    def classify(
        self,
        image,
        watching_ad=False,
        ad_foreground=False,
        *,
        original=None,
        time=0.0,
        adb=None,
        serial=None,
    ):
        rgb = np.asarray(image, dtype=np.int16) if image is not None else None
        if rgb is not None and (watching_ad or ad_foreground):
            if point := self.reward_close(image):
                return Screen("reward_granted", point)
            if point := self.ad_end_close(rgb):
                return Screen("ad_end_card", point)
            if all(self.matches(rgb, name)
                   for name in ("ad_sheet_close", "ad_sheet_chevron", "ad_sheet_cta")):
                return Screen("ad_end_sheet", (1257, 39))

        if not ad_foreground and rgb is not None:
            game = self._classify_game_screen(rgb)
            if game.name != "unknown":
                self.ad_closer.reset()
                return game

        if watching_ad or ad_foreground:
            raw_frame = original if original is not None else image
            sig = self.ad_closer.inspect(
                time,
                raw_frame,
                adb=adb,
                serial=serial,
                ad_foreground=ad_foreground,
            )
            if sig is not None:
                return Screen(sig.kind, sig.point, raw_point=sig.raw_point, keyevent=sig.keyevent)
            return Screen("ad_playing" if ad_foreground else "unknown")

        self.ad_closer.reset()
        return Screen("unknown")


class Player:
    def __init__(self, mode, report, tower=None, auto_captcha=False, *, watch_ads=True, skip_waves=False):
        if mode == "skip":
            mode = "wave"
            skip_waves = True
        self.mode = mode
        self.skip_waves = skip_waves
        self.report = report
        self.tower = tower
        self.auto_captcha = auto_captcha
        self.watch_ads = watch_ads
        self.screen = "unknown"
        self.screen_target = None
        self.since = 0
        self.acted = False
        self.wait_notified = False
        self.paused = False
        self.ad = None
        self.ad_since = 0
        self.ad_warned = False
        self.reward_label_seen = False
        self.ad_close_attempts = {}
        self.ad_taps = 0
        self.skip_offer = False
        self.gold_before = None
        self.after_victory = False
        self.skills_used = {}
        self.last_skill = float("-inf")
        self.last_mimic = float("-inf")
        self.mimic_taps = 0

    def collect_mimic(self, time, point):
        if point is None or self.mimic_taps >= 3 or time - self.last_mimic < 1.2:
            return None
        self.last_mimic = time
        self.mimic_taps += 1
        return Action("collect Mimic chest", point)

    def start_ad(self, time, gold=None):
        self.ad, self.ad_since, self.ad_warned = "watch", time, False
        self.gold_before = gold
        self.reward_label_seen = False
        self.ad_close_attempts.clear()
        self.ad_taps = 0

    def feed_ad(self, time, screen, age):
        name = screen.name
        if name == "ad_playing":
            if self.ad == "watch":
                self.ad = "playing"
            if age >= 1.5:
                self.ad_close_attempts.clear()
        elif name == "ad_resume":
            if age >= 0.15 and self.ad_taps < 12:
                self.ad = "playing"
                self.ad_close_attempts.clear()
                self.ad_taps += 1
                return Action("resume ad for reward", screen.point, raw_point=screen.raw_point)
        elif name in AD_CLOSE_SCREENS:
            self.ad = "return"
            self.reward_label_seen |= name == "reward_granted"
            if screen.keyevent is not None:
                attempt_key = (name, "key", screen.keyevent)
            elif screen.point is not None and name in {"ad_ui_close", "ad_visual_close"}:
                attempt_key = (name, screen.point[0] // 24, screen.point[1] // 24)
            else:
                attempt_key = name
            max_attempts = 2 if name == "ad_back" else 3
            cooldown = 4.0 if name == "ad_back" else (2.0 if name == "ad_external_overlay" else 1.5)
            min_age = 0.60 if name == "ad_external_overlay" else 0.20
            attempts, last_tap = self.ad_close_attempts.get(attempt_key, (0, float("-inf")))
            if age >= min_age and attempts < max_attempts and self.ad_taps < 12 and time - last_tap >= cooldown:
                self.ad_close_attempts[attempt_key] = (attempts + 1, time)
                self.ad_taps += 1
                if name == "reward_granted":
                    label = "close granted ad"
                elif name == "ad_external_overlay":
                    label = "dismiss ad overlay (BACK)"
                elif name == "ad_back":
                    label = "close finished ad (BACK)"
                else:
                    label = "close ad end card"
                return Action(
                    label,
                    screen.point,
                    raw_point=screen.raw_point,
                    keyevent=screen.keyevent,
                )
        elif name in RETURN_SCREENS and age >= 0.55:
            if self.ad == "return":
                changed = (screen.gold is not None and self.gold_before is not None
                           and np.mean(np.abs(screen.gold - self.gold_before)) > 6)
                message = "gold HUD changed" if changed else "gold HUD change unconfirmed"
                result = "Reward granted" if self.reward_label_seen else "Ad end card closed"
                self.report(time, f"{result}, returned to game ({message})")
                self.ad = None
            elif self.ad == "playing" or time - self.ad_since >= 12:
                self.report(time, "Game returned without a recognized reward")
                self.ad = None
                self.acted = False
        if self.ad and not self.ad_warned and time - self.ad_since >= 90:
            self.report(time, "Ad still open: waiting for recognized reward or manual close")
            self.ad_warned = True
        return None

    def feed(self, time, screen):
        if screen.name == "gold" and not self.watch_ads:
            # The inline offer leaves the home controls and tower slots available.
            screen = replace(screen, name="home")
        name = screen.name
        target_bucket = (
            (screen.point[0] // 24, screen.point[1] // 24)
            if screen.point is not None and name in AD_CLOSE_SCREENS
            else None
        )
        if name != self.screen or target_bucket != self.screen_target:
            self.screen, self.screen_target, self.since = name, target_bucket, time
            self.acted = False
            self.wait_notified = False
        age = time - self.since
        if self.ad is None and (name in {"ad_playing", "ad_resume"} or name in AD_CLOSE_SCREENS):
            self.start_ad(time)
            self.skip_offer = True
        if self.ad:
            if self.tower is not None:
                self.tower.suspend()
            action = self.feed_ad(time, screen, age)
            if self.ad:
                return action
        if name == "captcha":
            if self.tower is not None:
                self.tower.suspend()
            if not self.paused:
                message = "automatic attempt" if self.auto_captcha else "manual solution"
                self.report(time, f"CAPTCHA: paused for {message}")
                self.paused = True
            return None
        if self.paused:
            if name not in RETURN_SCREENS or age < 0.45:
                return None
            self.report(time, "Game screen restored: resumed")
            self.paused = False
        if name == "defeat" and self.mode == "wave":
            self.mode = "replay"
            self.report(time, "Castle HP reached zero: switched to Replay")
        if name == "victory":
            self.skills_used.clear()
            self.after_victory = self.watch_ads
        elif name == "battle":
            self.after_victory = False
        if name in {"home", "gold", "battle"} and screen.mimic is None:
            self.mimic_taps = 0
        if name in {"home", "battle"} and age >= 0.45:
            self.skip_offer = False
        if name in {"home", "gold"} and screen.mimic is not None and age >= 0.20:
            if action := self.collect_mimic(time, screen.mimic):
                return action
        if name == "home" and self.after_victory:
            if age < 1.6:
                return None
            self.after_victory = False
        if name == "gold" and not self.skip_offer:
            if age < 0.20:
                return None
            self.after_victory = False
            self.start_ad(time, screen.gold)
            self.skip_offer = True
            self.acted = True
            return Action("open gold ad (GET)", screen.point)
        if self.tower is not None and name in {"home", "tower", "castles", "unknown"}:
            try:
                handled, action = self.tower.feed(time, screen)
            except RuntimeError as exc:
                self.report(time, f"{exc} Automatic upgrades disabled for this run.")
                self.tower = None
            else:
                if handled:
                    return action
        elif self.tower is not None:
            self.tower.suspend()
        if name == "unknown" and age >= 3 and not self.wait_notified:
            self.report(time, "Unknown screen: waiting for the main screen or a battle")
            self.wait_notified = True
        if name == "battle":
            if screen.mimic is not None and age >= 0.20:
                if action := self.collect_mimic(time, screen.mimic):
                    self.last_skill = time
                    return action
            return self.cast(time, screen.ready) if age >= 0.45 else None
        if self.acted or age < 0.20:
            return None
        if name == "skip":
            if self.skip_waves and self.mode == "wave":
                if screen.gems is None and age < 0.65:
                    return None
                if screen.gems is not None and screen.gems >= SKIP_GEM_THRESHOLD and screen.skip_30:
                    action = Action("select Wave Skip 30", SKIP_30_POINT)
                else:
                    action = Action("close Wave Skip", screen.point)
            else:
                action = Action("close Wave Skip", screen.point)
        elif name == "replay_menu" and self.mode == "replay":
            action = Action("start Replay 100%", screen.point)
        elif name in {"home", "gold"} and age >= 0.85:
            self.skills_used.clear()
            if self.mode == "wave":
                action = Action("start next Battle", (1191, 648))
            else:
                action = Action("open Replay menu", (1017, 648))
        else:
            return None
        self.acted = True
        return action

    def cast(self, time, ready):
        for index in tuple(self.skills_used):
            self.skills_used[index] = 0 if index in ready else self.skills_used[index] + 1
            if self.skills_used[index] >= 2:
                del self.skills_used[index]
        if time - self.last_skill < 0.30:
            return None
        for index in ready:
            if index not in self.skills_used:
                self.skills_used[index] = 0
                self.last_skill = time
                label, x, _, y = SKILLS[index]
                return Action(f"cast {label}", (x, y))
        return None


def adb_frames(adb, serial, seconds):
    start = monotonic()
    while not seconds or monotonic() - start < seconds:
        sample = monotonic()
        raw = adb_run(adb, serial, "exec-out", "screencap", "-p")
        with Image.open(BytesIO(raw)) as screen:
            yield sample - start, screen.copy()
        sleep(max(0, 0.22 - (monotonic() - sample)))


def replay_frames(video):
    next_sample = 0
    for _, time, image in read_video(video):
        if time >= next_sample - 0.002:
            yield time, image
            next_sample += 0.20


def play(args, target, report, journal):
    skip_waves = args.skip or args.mode == "skip"
    mode_label = "skip" if (args.mode == "skip" or (args.mode == "wave" and args.skip)) else args.mode
    tower = TowerUpgrade(report, journal) if args.upgrade_tower else None
    player = Player(
        args.mode,
        report,
        tower,
        args.auto_captcha,
        watch_ads=args.ads,
        skip_waves=skip_waves,
    )
    vision = Vision(args.upgrade_tower)
    prefix = "TAP" if args.tap else "PREVIEW"
    if args.video:
        frames = replay_frames(args.video)
        print(f"{prefix} mode={mode_label} source={args.video}", flush=True)
    else:
        connected_serial = ensure_adb_connected(
            target.adb,
            target.serial,
            conf=target.conf,
            instance_key=target.instance if target.emulator == "bluestacks" else None,
            allow_port_refresh=(target.emulator == "bluestacks" and not args.serial),
        )
        target = replace(target, serial=connected_serial)
        frames = adb_frames(target.adb, target.serial, args.seconds)
        print(
            f"{prefix} mode={mode_label} emulator={target.emulator} "
            f"instance={target.instance} ({target.display_name!r}) source={target.serial}",
            flush=True,
        )

    for time, original in frames:
        activity = None
        if args.video:
            screen = vision.classify(
                viewport(original),
                watching_ad=player.ad is not None,
                original=original,
                time=time,
            )
        else:
            package, win_activity = foreground_window(target.adb, target.serial)
            if package == "com.raongames.growcastle" and win_activity:
                activity = win_activity
                # An ad can show footage of a game. Its Android window owns the
                # frame until it closes, even if the image resembles a game screen.
                screen = vision.classify(
                    viewport(original),
                    watching_ad=player.ad is not None,
                    ad_foreground=is_ad_activity(activity),
                    original=original,
                    time=time,
                    adb=target.adb,
                    serial=target.serial,
                )
            elif player.ad is not None and package in AD_OVERLAY_PACKAGES:
                screen = Screen("ad_external_overlay", keyevent=KEYCODE_BACK)
            else:
                vision.ad_closer.reset()
                screen = Screen("unfocused")
        was_paused = player.paused
        action = player.feed(time, screen)
        if args.auto_captcha and player.paused and not was_paused:
            attempt_started = monotonic()
            limit = min(16, args.seconds - time) if args.seconds else 16
            try:
                selected = limit > 0 and watch_target(
                    target, limit, True,
                    start_screen=vision.captcha_start_visible,
                )
            except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
                report(time + monotonic() - attempt_started, f"CAPTCHA attempt stopped: {exc}")
                selected = False
            if selected:
                report(time + monotonic() - attempt_started, "CAPTCHA: selection sent; waiting for the game to resume")
            else:
                report(time + monotonic() - attempt_started, "CAPTCHA: waiting for manual solution")
        if action:
            if action.keyevent is not None:
                if args.tap:
                    adb_run(target.adb, target.serial, "shell", "input", "keyevent", str(action.keyevent))
                report(time, f"{prefix} {action.name}")
            else:
                if args.tap:
                    if action.charge is not None:
                        raw = adb_run(target.adb, target.serial, "exec-out", "screencap", "-p")
                        with Image.open(BytesIO(raw)) as check:
                            latest = vision.classify(viewport(check))
                            if (check.size != original.size or latest.name != "tower"
                                    or (latest.gems, latest.level, latest.cost) != action.charge
                                    or foreground_activity(target.adb, target.serial) != activity):
                                tower.suspend()
                                continue
                        tower.record_tap(action)
                    if action.raw_point:
                        x, y = round(action.point[0]), round(action.point[1])
                    else:
                        x = round(action.point[0] * original.width / VIEWPORT[0])
                        y = round(action.point[1] * original.height / VIEWPORT[1])
                    adb_run(target.adb, target.serial, "shell", "input", "tap", str(x), str(y))
                elif action.charge is not None:
                    tower.record_tap(action)
                report(time, f"{prefix} {action.name} {action.point}")


def _device_lock_key(target) -> str:
    if (target.emulator == "bluestacks" and target.conf is not None
            and target.instance and target.instance != target.serial):
        return f"bluestacks:{target.conf.resolve()}:{target.instance}"
    return target.serial


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", type=Path, help="preview decisions on a recorded MP4")
    parser.add_argument("--mode", choices=("wave", "replay", "skip"), default="wave")
    parser.add_argument("--skip", action="store_true",
                        help="select 30 WAVES on Wave Skip when white gems >= 30")
    parser.add_argument("--emulator", choices=("bluestacks", "ldplayer"),
                        help="target emulator (default: bluestacks, or ldplayer when --ldconsole is given)")
    parser.add_argument("--instance", help="BlueStacks 5 instance key or window title (e.g. Pie64, Pie64_1)")
    parser.add_argument("--index", type=int, help="emulator instance index (0, 1, 2, ...)")
    parser.add_argument("--serial", help="ADB serial override (e.g. 127.0.0.1:5555 or emulator-5554)")
    parser.add_argument("--adb", type=Path, help="path to HD-Adb.exe or adb.exe (auto-detected by default)")
    parser.add_argument("--conf", type=Path, help="path to bluestacks.conf (auto-detected by default)")
    parser.add_argument("--ldconsole", type=Path, help="path to ldconsole.exe (for LDPlayer 9)")
    parser.add_argument("--list", action="store_true", help="list detected emulator instances and exit")
    parser.add_argument("--seconds", type=float, default=0, help="live capture limit, 0 waits indefinitely")
    parser.add_argument("--tap", action="store_true", help="send the recognized actions to the emulator")
    parser.add_argument("--ads", action=argparse.BooleanOptionalAction, default=True,
                        help="open gold reward ads automatically (default: enabled)")
    parser.add_argument("--auto-captcha", action="store_true",
                        help="automatically start and try one selection per CAPTCHA (requires --tap)")
    parser.add_argument("--upgrade-tower", action="store_true",
                        help="spend gems on a batch of 30 Lightning Castle upgrades at 90+ gems")
    args = parser.parse_args()
    if args.video and args.tap:
        parser.error("--video is preview only")
    if args.auto_captcha and not args.tap:
        parser.error("--auto-captcha requires --tap")
    if args.seconds < 0 or (args.index is not None and args.index < 0):
        parser.error("--seconds and --index must be nonnegative")

    def report(time, message):
        print(f"{time:6.2f}s  {message}", flush=True)

    try:
        if args.list:
            emu = args.emulator or ("ldplayer" if args.ldconsole else "bluestacks")
            print(format_instances(emulator=emu, adb=args.adb, conf=args.conf, ldconsole=args.ldconsole))
            return

        target = None if args.video else resolve_target(
            emulator=args.emulator,
            instance=args.instance,
            index=args.index,
            serial=args.serial,
            adb=args.adb,
            conf=args.conf,
            ldconsole=args.ldconsole,
        )
        journal = session_lock = None
        if args.tap and target is not None:
            device_id = sha256(_device_lock_key(target).encode()).hexdigest()[:16]
            session_lock = Path(__file__).with_name(f".autoplay-{device_id}.lock")
            if args.upgrade_tower:
                journal = Path(__file__).with_name(f".tower-upgrade-{device_id}.json")
        conflict_label = f"{target.instance} ({target.serial})" if target else "device"
        with lock_journal(session_lock, f"Autoplay is already running with --tap on {conflict_label}."), lock_journal(journal):
            play(args, target, report, journal)
    except KeyboardInterrupt:
        pass
    except subprocess.CalledProcessError as exc:
        parser.exit(1, f"{exc.stderr.decode(errors='replace').strip() or exc}\n")
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
