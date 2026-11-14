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


if __name__ == "__main__":
    unittest.main()
