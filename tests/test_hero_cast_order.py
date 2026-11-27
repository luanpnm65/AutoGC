"""Hero detection, battle gating, latches, priority, and tap safety."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import unittest

import numpy as np
from PIL import Image

import autoplay
from autoplay import (
    ARCHER_SKILLS,
    BOSS_GLYPH,
    BOSS_ONLY_HERO_SLOT,
    BOSS_ONLY_SKILL_INDEX,
    HERO_SKILLS,
    SKILLS,
    Player,
    Screen,
    Vision,
    detect_hero_skills,
    viewport,
)
from emulator import EmulatorTarget
from tower_upgrade import HERO_SLOTS


class HeroDetectionTests(unittest.TestCase):
    def setUp(self):
        self.rgb = np.zeros((720, 1280, 3), dtype=np.uint8)

    def bar(self, hero, color=(10, 200, 220), count=245):
        _, x, y, _ = HERO_SKILLS[hero]
        region = self.rgb[y - 2:y + 3, x - 24:x + 25]
        region[:] = 0
        for i in range(count):
            region[i // 49, i % 49] = color

    def test_coordinates_and_detection_in_current_frame(self):
        expected = [(x, y, tap_y) for y, tap_y in ((146, 184), (241, 277), (331, 370))
                    for x in (293, 373, 453)]
        self.assertEqual([(x, y, tap_y) for _, x, y, tap_y in HERO_SKILLS], expected)
        for hero in range(9):
            self.bar(hero)
        self.assertEqual(detect_hero_skills(self.rgb), list(range(9)))
        self.bar(4, count=0)
        self.assertEqual(detect_hero_skills(self.rgb), [0, 1, 2, 3, 5, 6, 7, 8])

    def test_92_percent_threshold_and_signed_arithmetic(self):
        self.bar(0, count=225)  # 225 / 245 < 0.92
        self.bar(1, count=226)  # 226 / 245 >= 0.92
        self.bar(2, color=(250, 220, 200))  # unsigned subtraction would wrap
        self.bar(3, color=(0, 106, 165))  # blue-red >65 and green-red >50
        self.bar(4, color=(0, 105, 220))  # strict green threshold
        self.bar(5, color=(0, 200, 164))  # strict blue threshold
        self.bar(6, color=(150, 210, 215))  # blue-red == 65
        self.bar(7, color=(100, 150, 200))  # green-red == 50
        self.assertEqual(detect_hero_skills(self.rgb), [1, 3])

    def test_viewport_tolerance_and_size(self):
        self.assertEqual(viewport(Image.new("RGB", (640, 360))).size, (1280, 720))
        self.assertEqual(viewport(Image.new("RGB", (1820, 1000))).size, (1280, 720))
        self.assertIsNone(viewport(Image.new("RGB", (1850, 1000))))
        self.assertIsNone(viewport(Image.new("RGB", (900, 600))))

    def test_classification_requires_hud_speed_and_wave_or_boss(self):
        vision = Vision(False)
        self.bar(0)
        for hud, speed, wave, boss, expected in (
            (True, True, True, False, "battle"),
            (True, True, False, True, "battle"),
            (False, True, True, False, "unknown"),
            (True, False, True, False, "unknown"),
            (True, True, False, False, "unknown"),
        ):
            with self.subTest(hud=hud, speed=speed, wave=wave, boss=boss), \
                    patch.object(vision, "matches", side_effect=lambda rgb, name, *args:
                                 {"hud": hud, "speed": speed, "wave": wave}.get(name, False)), \
                    patch.object(vision, "matches_boss", return_value=boss), \
                    patch.object(vision, "hp_empty", return_value=False), \
                    patch.object(vision, "find_mimic", return_value=None), \
                    patch.object(vision, "smith_skill_ready", return_value=False), \
                    patch.object(vision, "castle_hp_low", return_value=False):
                screen = vision._classify_game_screen(self.rgb.astype(np.int16))
                self.assertEqual(screen.name, expected)
                if expected == "battle":
                    self.assertEqual(screen.ready, (2,))
                    self.assertEqual(screen.boss, boss)


class HeroDecisionTests(unittest.TestCase):
    def make_player(self, humanize=False):
        return Player("wave", lambda *args: None, watch_ads=False, humanize=humanize)

    def test_each_decision_scans_from_hero_one_and_preserves_priority(self):
        player = self.make_player()
        self.assertEqual(player.cast(0, (5,)).name, "cast skill 4")
        self.assertEqual(player.cast(1, (0, 2, 6)).name, "cast archer skill 1")
        # Hero 1 becomes ready after the Archer, so it wins over Hero 5.
        self.assertEqual(player.cast(2, (2, 6)).name, "cast skill 1")
        self.assertEqual(player.cast(3, (1, 6), smith_ready=True, hp_low=True).name,
                         "cast Smith (HP < 50%)")
        self.assertEqual(player.cast(4, (1, 6), smith_ready=True, hp_low=True).name,
                         "cast archer skill 2")
        self.assertEqual(player.cast(5, (6,)).name, "cast skill 5")

    def test_shared_020_second_interval_for_smith_archer_and_heroes(self):
        for humanize in (False, True):
            with self.subTest(humanize=humanize):
                player = self.make_player(humanize)
                ready = (0, 1, 2, 3)
                self.assertEqual(player.cast(0, ready, smith_ready=True, hp_low=True).name,
                                 "cast Smith (HP < 50%)")
                self.assertIsNone(player.cast(0.199, ready, smith_ready=True, hp_low=True))
                self.assertEqual(player.cast(0.2, ready, smith_ready=True, hp_low=True).name,
                                 "cast archer skill 1")
                self.assertIsNone(player.cast(0.39, ready, smith_ready=True, hp_low=True))
                self.assertEqual(player.cast(0.41, ready, smith_ready=True, hp_low=True).name,
                                 "cast archer skill 2")
                self.assertIsNone(player.cast(0.60, ready, smith_ready=True, hp_low=True))
                self.assertEqual(player.cast(0.62, ready, smith_ready=True, hp_low=True).name,
                                 "cast skill 1")
                self.assertIsNone(player.cast(0.81, ready, smith_ready=True, hp_low=True))
                self.assertEqual(player.cast(0.83, ready, smith_ready=True, hp_low=True).name,
                                 "cast skill 2")

    def test_latch_requires_two_consecutive_non_full_battle_frames(self):
        player = self.make_player()
        self.assertEqual(player.cast(0, (2,)).name, "cast skill 1")
        self.assertIsNone(player.cast(0.1, ()))
        self.assertIsNone(player.cast(0.2, (2,)))  # full resets missing streak
        self.assertIsNone(player.cast(0.3, ()))
        self.assertIsNone(player.cast(0.4, (2,)))
        self.assertIsNone(player.cast(0.5, ()))
        self.assertIsNone(player.cast(0.6, ()))
        self.assertEqual(player.cast(1, (2,)).name, "cast skill 1")

    def test_interrupted_or_invalid_frames_do_not_complete_latch_streak(self):
        for interruption in ("skip", "captcha", "invalid"):
            with self.subTest(interruption=interruption):
                player = self.make_player()
                player.feed(0, Screen("battle", ready=(2,)))
                self.assertEqual(player.feed(0.5, Screen("battle", ready=(2,))).name, "cast skill 1")
                player.feed(0.6, Screen("battle", ready=()))
                if interruption == "invalid":
                    player.invalidate_frame(0.7)
                else:
                    player.feed(0.7, Screen(interruption))
                player.feed(1, Screen("battle", ready=()))
                self.assertIn(2, player.skills_used)  # one observed missing frame
                player.feed(1.1, Screen("battle", ready=(2,)))
                self.assertIn(2, player.skills_used)  # full breaks the streak
                self.assertIsNone(player.feed(1.5, Screen("battle", ready=(2,))))
                player.feed(1.6, Screen("battle", ready=()))
                player.feed(1.7, Screen("battle", ready=()))
                self.assertEqual(player.feed(1.8, Screen("battle", ready=(2,))).name, "cast skill 1")

    def test_entry_delay_cooldown_and_latch_reset(self):
        for humanize in (False, True):
            with self.subTest(humanize=humanize):
                player = self.make_player(humanize)
                battle = Screen("battle", ready=(2, 3))
                self.assertIsNone(player.feed(0, battle))
                self.assertIsNone(player.feed(0.44, battle))
                self.assertEqual(player.feed(0.45, battle).name, "cast skill 1")
                self.assertIsNone(player.feed(0.64, battle))
                self.assertEqual(player.feed(0.66, battle).name, "cast skill 2")
                player.feed(1, Screen("victory"))
                self.assertEqual(player.skills_used, {})
                player.feed(2, Screen("home"))
                player.feed(4, Screen("home"))  # starts a new battle
                self.assertEqual(player.skills_used, {})
                player.feed(5, battle)
                self.assertEqual(player.feed(5.5, battle).name, "cast skill 1")


class BossOnlyHeroSlotTests(unittest.TestCase):
    """Hero slot 12 ("skill 9") only casts while a Boss health bar is visible."""

    def make_player(self, mode="wave"):
        return Player(mode, lambda *args: None, watch_ads=False)

    def test_slot12_maps_to_bottom_right_hero_skill(self):
        self.assertEqual(BOSS_ONLY_HERO_SLOT, 12)
        self.assertEqual(BOSS_ONLY_SKILL_INDEX, len(ARCHER_SKILLS) + 8)
        self.assertEqual(SKILLS[BOSS_ONLY_SKILL_INDEX], ("skill 9", 453, 331, 370))
        # Battle tap row matches home-grid slot 12 (bottom-right).
        self.assertEqual(HERO_SLOTS[BOSS_ONLY_HERO_SLOT - 1], (461, 370))

    def test_every_auto_mode_holds_slot12_until_boss(self):
        for mode in ("wave", "replay", "skip", "skip10", "skip20", "skip30"):
            with self.subTest(mode=mode):
                player = self.make_player(mode)
                self.assertIsNone(player.cast(0, (BOSS_ONLY_SKILL_INDEX,)))
                self.assertNotIn(BOSS_ONLY_SKILL_INDEX, player.skills_used)
                self.assertIsNone(player.cast(1, (BOSS_ONLY_SKILL_INDEX,), boss=False))
                action = player.cast(2, (BOSS_ONLY_SKILL_INDEX,), boss=True)
                self.assertEqual(action.name, "cast skill 9")
                self.assertEqual(action.point, (453, 370))

    def test_other_skills_cast_normally_while_slot12_waits(self):
        player = self.make_player()
        ready = (0, 1, 2, BOSS_ONLY_SKILL_INDEX)
        self.assertEqual(player.cast(0, ready, smith_ready=True, hp_low=True).name,
                         "cast Smith (HP < 50%)")
        self.assertEqual(player.cast(0.2, ready).name, "cast archer skill 1")
        self.assertEqual(player.cast(0.41, ready).name, "cast archer skill 2")
        self.assertEqual(player.cast(0.62, ready).name, "cast skill 1")
        self.assertIsNone(player.cast(0.83, ready))  # only slot 12 left, no Boss
        self.assertEqual(player.cast(1.0, ready, boss=True).name, "cast skill 9")

    def test_feed_passes_boss_flag_and_holds_without_latching(self):
        player = self.make_player()
        wave = Screen("battle", ready=(BOSS_ONLY_SKILL_INDEX,))
        self.assertIsNone(player.feed(0, wave))
        self.assertIsNone(player.feed(0.5, wave))
        self.assertIsNone(player.feed(1.0, wave))
        self.assertNotIn(BOSS_ONLY_SKILL_INDEX, player.skills_used)
        boss = Screen("battle", ready=(BOSS_ONLY_SKILL_INDEX,), boss=True)
        self.assertEqual(player.feed(1.5, boss).name, "cast skill 9")
        # Latched after the cast; a visible Boss does not bypass the latch.
        self.assertIsNone(player.feed(1.71, boss))
        self.assertIsNone(player.feed(1.9, Screen("battle", ready=(), boss=True)))
        self.assertIsNone(player.feed(2.1, Screen("battle", ready=(), boss=True)))
        self.assertEqual(player.feed(2.3, boss).name, "cast skill 9")
        # Boss gone: after the latch releases, the ready skill is held again.
        self.assertIsNone(player.feed(2.5, Screen("battle", ready=(), boss=False)))
        self.assertIsNone(player.feed(2.7, Screen("battle", ready=(), boss=False)))
        self.assertNotIn(BOSS_ONLY_SKILL_INDEX, player.skills_used)
        self.assertIsNone(player.feed(2.9, wave))
        self.assertEqual(player.feed(3.1, boss).name, "cast skill 9")

    def test_boss_bar_frame_sets_boss_flag_from_real_detector(self):
        vision = Vision(False)
        rgb = np.zeros((720, 1280, 3), dtype=np.uint8)
        colors = {"#": (250, 250, 250), "@": (15, 15, 15), ".": (180, 40, 40)}
        glyph = np.array([[colors[ch] for ch in row] for row in BOSS_GLYPH], dtype=np.uint8)
        scale = 1.25
        width, height = (round(glyph.shape[1] * scale), round(glyph.shape[0] * scale))
        bar = np.asarray(Image.fromarray(glyph).resize((width, height), Image.Resampling.BILINEAR))
        rgb[44:44 + height, 600:600 + width] = bar
        frame = rgb.astype(np.int16)
        self.assertTrue(vision.matches_boss(frame))
        # WAVE marker absent: the Boss bar alone must classify the battle and
        # carry boss=True; a blank frame stays unknown with boss=False.
        with patch.object(vision, "matches", side_effect=lambda rgb, name, *args:
                          name in {"hud", "speed"}), \
                patch.object(vision, "hp_empty", return_value=False), \
                patch.object(vision, "find_mimic", return_value=None), \
                patch.object(vision, "smith_skill_ready", return_value=False), \
                patch.object(vision, "castle_hp_low", return_value=False):
            screen = vision._classify_game_screen(frame)
            self.assertEqual(screen.name, "battle")
            self.assertTrue(screen.boss)
            blank = vision._classify_game_screen(np.zeros_like(frame))
            self.assertEqual(blank.name, "unknown")
            self.assertFalse(blank.boss)


class HeroPlayTests(unittest.TestCase):
    def args(self, *, tap, video=None):
        return SimpleNamespace(mode="wave", skip=None, tap=tap, humanize=True,
                               upgrade_hero=None, upgrade_tower=None, upgrade_gems=None,
                               upgrade_levels=None, auto_captcha=False, ads=False,
                               video=video, serial="device", seconds=5)

    def target(self):
        return EmulatorTarget(emulator="ldplayer", adb=Path("adb"), serial="device",
                              instance="test", display_name="test")

    def test_real_hero_tap_scaled_foreground_checked_and_no_extra_capture(self):
        frame = Image.new("RGB", (1920, 1080))
        battle = Screen("battle", ready=(2,))
        with patch.object(autoplay, "ensure_adb_connected", return_value="device"), \
                patch.object(autoplay, "adb_frames", return_value=iter([(0, frame), (.5, frame)])), \
                patch.object(autoplay, "foreground_window", return_value=("com.raongames.growcastle", "game")) as fg, \
                patch.object(autoplay, "Vision") as vision, \
                patch.object(autoplay, "human_tap") as human, \
                patch.object(autoplay, "adb_run") as adb, \
                patch("builtins.print"):
            vision.return_value.classify.return_value = battle
            autoplay.play(self.args(tap=True), self.target(), lambda *args: None, None)
            self.assertEqual(fg.call_count, 3)  # once per frame and just before tap
            human.assert_not_called()
            adb.assert_called_once_with(Path("adb"), "device", "shell", "input", "tap", "440", "276")
            self.assertEqual(vision.return_value.classify.call_count, 2)

    def test_live_casts_enforce_wall_clock_spacing_after_archer(self):
        frame = Image.new("RGB", (1280, 720))
        battle = Screen("battle", ready=(0, 2))
        with patch.object(autoplay, "ensure_adb_connected", return_value="device"), \
                patch.object(autoplay, "adb_frames", return_value=iter([(0, frame), (.5, frame), (.9, frame)])), \
                patch.object(autoplay, "foreground_window", return_value=("com.raongames.growcastle", "game")), \
                patch.object(autoplay, "Vision") as vision, \
                patch.object(autoplay, "human_tap", return_value=(135, 405)) as human, \
                patch.object(autoplay, "adb_run") as adb, \
                patch.object(autoplay, "monotonic", side_effect=[10.0, 10.1, 10.3]), \
                patch.object(autoplay, "sleep") as sleep, \
                patch("builtins.print"):
            vision.return_value.classify.return_value = battle
            autoplay.play(self.args(tap=True), self.target(), lambda *args: None, None)
            human.assert_called_once()
            adb.assert_called_once_with(Path("adb"), "device", "shell", "input", "tap", "293", "184")
            self.assertAlmostEqual(sleep.call_args.args[0], 0.1)

    def test_foreground_change_cancels_tap_and_allows_safe_retry(self):
        frame = Image.new("RGB", (1280, 720))
        battle = Screen("battle", ready=(2,))
        game = ("com.raongames.growcastle", "game")
        fg_values = [game, game, ("other.app", "activity"), game, game, game]
        with patch.object(autoplay, "ensure_adb_connected", return_value="device"), \
                patch.object(autoplay, "adb_frames", return_value=iter([(0, frame), (.5, frame),
                                                                          (1, frame), (1.5, frame)])), \
                patch.object(autoplay, "foreground_window", side_effect=fg_values), \
                patch.object(autoplay, "Vision") as vision, \
                patch.object(autoplay, "adb_run") as adb, \
                patch("builtins.print"):
            vision.return_value.classify.return_value = battle
            autoplay.play(self.args(tap=True), self.target(), lambda *args: None, None)
            adb.assert_called_once_with(Path("adb"), "device", "shell", "input", "tap", "293", "184")

    def test_invalid_aspect_frame_never_classified_or_tapped(self):
        bad = Image.new("RGB", (900, 600))
        with patch.object(autoplay, "ensure_adb_connected", return_value="device"), \
                patch.object(autoplay, "adb_frames", return_value=iter([(0, bad), (1, bad)])), \
                patch.object(autoplay, "foreground_window") as fg, \
                patch.object(autoplay, "Vision") as vision, \
                patch.object(autoplay, "adb_run") as adb, \
                patch("builtins.print"):
            autoplay.play(self.args(tap=True), self.target(), lambda *args: None, None)
            fg.assert_not_called()
            vision.return_value.classify.assert_not_called()
            adb.assert_not_called()

    def test_preview_logs_exact_normalized_hero_action_without_tap(self):
        frame = Image.new("RGB", (640, 360))
        with patch.object(autoplay, "replay_frames", return_value=iter([(0, frame), (.5, frame)])), \
                patch.object(autoplay, "Vision") as vision, \
                patch.object(autoplay, "adb_run") as adb, \
                patch("builtins.print") as output:
            vision.return_value.classify.return_value = Screen("battle", ready=(2,))
            autoplay.play(self.args(tap=False, video=Path("recording.mp4")), None, lambda *args: None, None)
            output.assert_any_call("PREVIEW cast skill 1 (293, 184)", flush=True)
            adb.assert_not_called()


if __name__ == "__main__":
    unittest.main()
