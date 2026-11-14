"""Battle recognition when the emulator draws the HUD slightly higher/lower."""

from pathlib import Path
import unittest

import numpy as np
from PIL import Image

from autoplay import HERO_SKILLS, Player, TEMPLATES, Vision


class BattleAlignmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.vision = Vision()
        # Only HUD/WAVE/speed regions from a user-provided game screenshot;
        # the rest of the frame is blank to avoid retaining unrelated content.
        image = Image.open(Path(__file__).parent / "fixtures" / "battle_wave_shifted.png")
        cls.rgb = np.asarray(image.convert("RGB"), dtype=np.int16)

    def test_user_frame_matches_battle_with_consistent_vertical_offset(self):
        v = self.vision
        self.assertFalse(v.matches(self.rgb, "hud"))
        self.assertFalse(v.matches(self.rgb, "wave"))
        self.assertTrue(v.matches(self.rgb, "hud", -2))
        self.assertTrue(v.matches(self.rgb, "wave", -2))
        self.assertTrue(v.matches(self.rgb, "speed", -2))
        self.assertEqual(v._classify_game_screen(self.rgb).name, "battle")

    def test_all_three_battle_markers_are_required(self):
        for box in ((0, 0, 34, 42), (610, 31, 714, 78), (20, 625, 102, 690)):
            with self.subTest(box=box):
                altered = self.rgb.copy()
                x0, y0, x1, y1 = box
                altered[y0:y1, x0:x1] = 0
                self.assertNotEqual(self.vision._classify_game_screen(altered).name, "battle")

    def test_skip_dialog_takes_precedence_over_battle(self):
        rgb = self.rgb.copy()
        for name in ("skip_title", "skip_close"):
            x0, y0, x1, y1 = TEMPLATES[name][0]
            rgb[y0 - 2:y1 - 2, x0:x1] = self.vision.templates[name]
        self.assertEqual(self.vision._classify_game_screen(rgb).name, "skip")

    def test_hero_cast_still_waits_for_stable_battle(self):
        rgb = self.rgb.copy()
        _, x, bar_y, _ = HERO_SKILLS[0]
        rgb[bar_y - 2:bar_y + 3, x - 24:x + 25] = (10, 200, 220)
        screen = self.vision._classify_game_screen(rgb)
        self.assertEqual(screen.name, "battle")
        self.assertIn(2, screen.ready)
        player = Player("wave", lambda *args: None, watch_ads=False)
        self.assertIsNone(player.feed(0, screen))
        self.assertIsNone(player.feed(0.44, screen))
        self.assertEqual(player.feed(0.45, screen).name, "cast skill 1")
        self.assertIsNone(player.feed(0.8, screen))  # latch prevents duplicate tap


class NativeAdbBattleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.vision = Vision()
        # Retain only HUD, WAVE and speed regions from the raw ADB screenshot.
        image = Image.open(Path(__file__).parent / "fixtures" / "battle_wave_adb.png")
        cls.rgb = np.asarray(image.convert("RGB"), dtype=np.int16)

    def test_native_adb_wave_matches_with_sharp_text(self):
        v = self.vision
        x0, y0, x1, y1 = TEMPLATES["wave"][0]
        shifted = self.rgb[y0 + 1:y1 + 1, x0:x1]
        difference = np.mean(np.abs(shifted - v.templates["wave"])[v.wave_text])
        self.assertGreaterEqual(difference, 20)  # rejected by previous fallback
        self.assertLess(difference, 23)
        self.assertTrue(v.matches(self.rgb, "hud"))
        self.assertTrue(v.matches(self.rgb, "speed"))
        self.assertTrue(v.matches(self.rgb, "wave"))
        self.assertEqual(v._classify_game_screen(self.rgb).name, "battle")

    def test_native_adb_frame_requires_hud_wave_and_speed(self):
        for box in ((0, 0, 34, 42), (610, 31, 714, 78), (20, 625, 102, 690)):
            with self.subTest(box=box):
                rgb = self.rgb.copy()
                x0, y0, x1, y1 = box
                rgb[y0:y1, x0:x1] = 0
                self.assertNotEqual(self.vision._classify_game_screen(rgb).name, "battle")

    def test_partial_wave_text_is_not_enough_to_start_battle(self):
        for offset in (10, 30, 50, 70):
            with self.subTest(offset=offset):
                rgb = self.rgb.copy()
                rgb[35:75, 615 + offset:615 + offset + 12] = 0
                self.assertNotEqual(self.vision._classify_game_screen(rgb).name, "battle")

    def test_native_adb_frame_does_not_cast_under_skip_dialog(self):
        rgb = self.rgb.copy()
        for name in ("skip_title", "skip_close"):
            x0, y0, x1, y1 = TEMPLATES[name][0]
            rgb[y0:y1, x0:x1] = self.vision.templates[name]
        self.assertEqual(self.vision._classify_game_screen(rgb).name, "skip")

    def test_native_adb_frame_can_cast_ready_hero_after_entry_delay(self):
        rgb = self.rgb.copy()
        _, x, bar_y, _ = HERO_SKILLS[0]
        rgb[bar_y - 2:bar_y + 3, x - 24:x + 25] = (10, 200, 220)
        screen = self.vision._classify_game_screen(rgb)
        self.assertEqual(screen.name, "battle")
        self.assertIn(2, screen.ready)
        player = Player("wave", lambda *args: None, watch_ads=False)
        self.assertIsNone(player.feed(0, screen))
        self.assertIsNone(player.feed(0.44, screen))
        self.assertEqual(player.feed(0.45, screen).name, "cast skill 1")


if __name__ == "__main__":
    unittest.main()
