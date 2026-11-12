"""Verify the Lightning Castle upgrade controls and read their counters."""

from pathlib import Path

import numpy as np
from PIL import Image


GEMS = (283, 2, 399, 36)
LEVEL = (316, 421, 456, 455)
PRICE = (902, 480, 965, 517)
UI = {
    "toggle": ((341, 419, 418, 499), 23),
    "castle_slot": ((343, 325, 417, 408), 24),
    "chain_lightning": ((532, 178, 825, 216), 18),
    "detail_close": ((970, 138, 1020, 181), 24),
    "button": ((806, 434, 983, 474), 23),
    "bulk": ((315, 586, 480, 629), 37),
    "list_title": ((845, 27, 1039, 77), 25),
    "list_close": ((1220, 49, 1275, 99), 26),
}
HOME_TEXT = {
    "town": (20, 66, 148, 105),
    "upgrade": (923, 89, 1218, 129),
    "battle": (1126, 668, 1257, 706),
    "replay": (950, 668, 1084, 706),
}
TITLE = (320, 107, 719, 155)
TITLE_SHIFTS = ((0, 0), (0, 1), (-1, 2), (-1, -2), (-1, -3))
DETAIL_SHIFTS = ((0, 0), (0, 1), (0, -1), (0, 2), (0, -2), (-1, 2), (-1, -2), (-1, -3))
LIST_SHIFTS = ((0, 0), (0, 1), (0, -1), (-1, 0), (1, 0), (-2, 0), (0, 2))
BOUNCE_SHIFTS = ((0, 0), (0, -2), (0, 2), (0, -1), (0, 1), (-1, -2), (-1, 2))
HOME_SHIFTS = ((0, 0), (0, 1), (0, 2), (-1, 1), (1, 1), (0, -1), (-2, 0), (-2, 2))
HERO_SLOT_BORDERS = ((51, 66), (122, 134), (146, 158), (218, 231), (241, 253), (314, 326))


def crop(rgb, box):
    left, top, right, bottom = box
    return rgb[top:bottom, left:right]


def digit_mask(rgb, palette):
    red, green, blue = rgb.transpose(2, 0, 1)
    if palette == "level":
        return (green > 106) & (green - red > 49) & (green - blue > 49)
    if palette == "cost":
        return (blue > 115) & (blue - red > 46) & (green - red > 40)
    white = max(54, np.quantile(rgb.max(axis=2), 0.995) * 0.59)
    return (rgb.min(axis=2) > white) & (np.ptp(rgb, axis=2) < 35)


def glyphs(mask):
    columns = mask.any(axis=0)
    starts = np.flatnonzero(columns & ~np.r_[False, columns[:-1]])
    ends = np.flatnonzero(columns & ~np.r_[columns[1:], False]) + 1
    for start, end in zip(starts, ends):
        tile = mask[:, start:end]
        rows = np.flatnonzero(tile.any(axis=1))
        yield tile[rows[0]:rows[-1] + 1]


def normalize(glyph):
    return np.asarray(Image.fromarray(glyph).resize((18, 24)), dtype=bool)


def text_mask(rgb):
    return (rgb.min(axis=2) > 145) & (np.ptp(rgb, axis=2) < 48)


def load_gem_templates():
    with np.load(Path(__file__).with_name("tower_templates.npz"), allow_pickle=False) as atlas:
        return atlas["gems"].astype(bool)


def read_white_gems(rgb, gem_templates):
    """Read only the white gem counter, ignoring any orange '+xxx' bonus suffix."""
    box = crop(rgb, GEMS)
    red, green, blue = box[:, :, 0], box[:, :, 1], box[:, :, 2]
    orange = (red > 175) & (green > 80) & (blue < 55) & (red - blue > 130) & (red - green > 40)
    orange_cols = np.flatnonzero(orange.sum(axis=0) >= 2)
    has_orange = len(orange_cols) > 0
    if has_orange:
        cut = int(orange_cols[0])
        if cut < 8:
            return None
        box = box[:, :cut]
    if box.shape[1] < 8:
        return None
    digits = [g for g in glyphs(digit_mask(box, "gems")) if g.shape[0] >= 12 and g.shape[1] >= 7]
    if not 1 <= len(digits) <= 5:
        return None
    min_h, min_w = (13, 8) if has_orange else (18, 10)
    max_score, min_margin = (76, 15) if has_orange else (72, 17)
    value = 0
    for glyph in digits:
        height, width = glyph.shape
        if not (min_h <= height <= 28 and min_w <= width <= 21 and 1.05 <= height / width <= 2.45):
            return None
        scores = np.count_nonzero(gem_templates != normalize(glyph), axis=(2, 3)).min(axis=1)
        best, second = np.argsort(scores)[:2]
        if scores[best] > max_score or scores[second] - scores[best] < min_margin:
            return None
        value = value * 10 + int(best)
    return value


class TowerVision:
    def __init__(self):
        with np.load(Path(__file__).with_name("tower_templates.npz"), allow_pickle=False) as atlas:
            self.ui = {key: atlas[key].astype(np.int16) for key in UI}
            self.numbers = {key: atlas[key].astype(bool) for key in ("gems", "level", "cost")}
            self.text = {key: text_mask(atlas[key]) for key in (*HOME_TEXT, "title")}

    def _matches(self, rgb, name, shifts=((0, 0),), min_std=0):
        box, tolerance = UI[name]
        left, top, right, bottom = box
        template = self.ui[name]
        for dx, dy in shifts:
            patch = rgb[top + dy:bottom + dy, left + dx:right + dx]
            if np.mean(np.abs(patch - template)) < tolerance and (not min_std or patch.std() >= min_std):
                return True
        return False

    def _text_matches(self, rgb, name, box, shifts, minimum):
        left, top, right, bottom = box
        target = self.text[name]
        for dx, dy in shifts:
            observed = text_mask(rgb[top + dy:bottom + dy, left + dx:right + dx])
            if np.count_nonzero(observed & target) > minimum * np.count_nonzero(observed | target):
                return True
        return False

    def is_home(self, rgb):
        """Check the bright, unobscured controls of the recorded home layout."""
        return all(self._text_matches(rgb, name, box, HOME_SHIFTS, 0.63)
                   for name, box in HOME_TEXT.items())

    def _number(self, rgb, box, palette, limit, shifts=((0, 0),)):
        left, top, right, bottom = box
        for dx, dy in shifts:
            shifted = (left + dx, top + dy, right + dx, bottom + dy)
            digits = list(glyphs(digit_mask(crop(rgb, shifted), palette)))
            if not 1 <= len(digits) <= limit:
                continue
            value = 0
            valid = True
            for glyph in digits:
                height, width = glyph.shape
                if not (18 <= height <= 28 and 11 <= width <= 21):
                    valid = False
                    break
                scores = np.count_nonzero(self.numbers[palette] != normalize(glyph),
                                          axis=(2, 3)).min(axis=1)
                best, second = np.argsort(scores)[:2]
                if scores[best] > 72 or scores[second] - scores[best] < 17:
                    valid = False
                    break
                value = value * 10 + int(best)
            if valid:
                return value
        return None

    def home(self, rgb):
        """Return (gems, edit layout) on a previously verified home screen."""
        rgb = np.asarray(rgb, dtype=np.int16)
        if not self._matches(rgb, "toggle"):
            return None, None
        if self._matches(rgb, "castle_slot"):
            layout = "castle"
        else:
            borders = sum(
                float(np.max((rgb[y0:y1, left:right].max(axis=2) < 95).mean(axis=1))) > 0.80
                for y0, y1 in HERO_SLOT_BORDERS
                for left, right in ((275, 321), (437, 486))
            )
            layout = "hero" if borders >= 8 else None
        return read_white_gems(rgb, self.numbers["gems"]), layout

    def _is_detail_card(self, rgb):
        unequip = rgb[434:518, 595:775]
        red, green, blue = unequip[:, :, 0], unequip[:, :, 1], unequip[:, :, 2]
        if ((red > 175) & (red - green > 95) & (red - blue > 95)).mean() < 0.38:
            return False
        if (rgb[220:400, 535:955].max(axis=2) < 55).mean() < 0.65:
            return False
        return self._matches(rgb, "detail_close", DETAIL_SHIFTS, min_std=12)

    def panel(self, rgb):
        """Read a verified Hero/Tower detail panel or right-side Heroes/Castles list."""
        rgb = np.asarray(rgb, dtype=np.int16)
        # The detail panel bounces a few pixels while the level changes.
        if self._is_detail_card(rgb):
            gems = read_white_gems(rgb, self.numbers["gems"])
            level = self._number(rgb, LEVEL, "level", 7, BOUNCE_SHIFTS)
            cost = None
            if self._matches(rgb, "button", DETAIL_SHIFTS):
                value = self._number(rgb, PRICE, "cost", 1, BOUNCE_SHIFTS)
                if value in (1, 2, 3):
                    cost = value
            return "tower", gems, level, cost
        if self._matches(rgb, "list_close", LIST_SHIFTS, min_std=14):
            return "castles", None, None, None
        return None
