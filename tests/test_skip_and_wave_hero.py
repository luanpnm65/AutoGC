"""Tests for Skip selection and post-wave Hero upgrade timing."""

import unittest

from autoplay import Player, Screen, WAVE_HERO_HOME_WAIT
from tower_upgrade import TowerUpgrade


class SkipSelectionTests(unittest.TestCase):
    def test_waits_for_requested_button_and_then_selects_it(self):
        for tier in (10, 20, 30):
            with self.subTest(tier=tier):
                messages = []
                player = Player("wave", lambda t, m: messages.append(m), skip_waves=tier)
                unresolved = Screen("skip", (888, 216), gems=100)
                player.feed(0, unresolved)
                self.assertIsNone(player.feed(0.3, unresolved))
                self.assertIsNone(player.feed(1.0, unresolved))
                self.assertEqual(len(messages), 1)
                ready = Screen("skip", (888, 216), gems=100,
                               skip_options=((tier, (469, 365)),))
                action = player.feed(1.1, ready)
                self.assertEqual(action.name, f"select Wave Skip {tier}")
                self.assertEqual(action.point, (469, 365))

    def test_waits_when_gems_unreadable_and_closes_only_when_insufficient(self):
        player = Player("skip10", lambda *args: None)
        no_gems = Screen("skip", (888, 216), skip_options=((10, (469, 365)),))
        player.feed(0, no_gems)
        self.assertIsNone(player.feed(2, no_gems))
        action = player.feed(2.1, Screen("skip", (888, 216), gems=9))
        self.assertEqual(action.name, "close Wave Skip")

    def test_skip_disabled_or_replay_still_closes(self):
        for mode, skip in (("wave", False), ("replay", 10)):
            with self.subTest(mode=mode):
                player = Player(mode, lambda *args: None, skip_waves=skip)
                offer = Screen("skip", (888, 216), gems=100, skip_options=((10, (469, 365)),))
                player.feed(0, offer)
                self.assertEqual(player.feed(0.3, offer).name, "close Wave Skip")


class WaveHeroWaitTests(unittest.TestCase):
    def player(self, mode, target="hero", watch_ads=False):
        upgrade = TowerUpgrade(lambda *args: None, target=target, hero_slot=1)
        return Player(mode, lambda *args: None, tower=upgrade, watch_ads=watch_ads)

    def test_wave_waits_after_battle_even_when_no_victory_or_ads(self):
        for mode in ("wave", "skip10", "skip20", "skip30"):
            with self.subTest(mode=mode):
                player = self.player(mode)
                player.feed(0, Screen("battle"))
                home = Screen("home", gems=100, layout="hero")
                self.assertIsNone(player.feed(1, home))
                self.assertIsNone(player.feed(1 + WAVE_HERO_HOME_WAIT - 0.01, home))
                action = player.feed(1 + WAVE_HERO_HOME_WAIT, home)
                self.assertEqual((action.name, action.point), ("open Hero slot 1", (293, 92)))

    def test_wave_victory_with_ads_and_humanized_wait(self):
        import random
        upgrade = TowerUpgrade(lambda *args: None, target="hero", hero_slot=1,
                               humanize=True, rng=random.Random(123))
        player = Player("wave", lambda *args: None, tower=upgrade, watch_ads=True,
                        humanize=True, rng=random.Random(123))
        player.feed(0, Screen("battle"))
        player.feed(1, Screen("victory"))
        home = Screen("home", gems=100, layout="hero")
        self.assertIsNone(player.feed(2, home))
        self.assertIsNone(player.feed(5.9, home))
        self.assertIsNone(player.feed(6.0, home))  # first post-victory upgrade observation
        self.assertEqual(player.feed(6.8, home).name, "open Hero slot 1")

    def test_wait_restarts_if_home_is_interrupted(self):
        player = self.player("wave")
        player.feed(0, Screen("battle"))
        home = Screen("home", gems=100, layout="hero")
        player.feed(1, home)
        player.feed(3, Screen("captcha"))
        self.assertIsNone(player.feed(4, home))
        self.assertIsNone(player.feed(7.9, home))
        self.assertIsNone(player.feed(8, home))
        self.assertEqual(player.feed(8.2, home).name, "open Hero slot 1")

    def test_replay_and_tower_upgrade_timing_unchanged(self):
        for mode, target, expected in (("replay", "hero", "open Hero slot 1"),
                                       ("wave", "tower", "show castle layers")):
            with self.subTest(mode=mode, target=target):
                player = self.player(mode, target)
                player.feed(0, Screen("battle"))
                home = Screen("home", gems=100, layout="hero")
                self.assertIsNone(player.feed(1, home))
                self.assertEqual(player.feed(1.2, home).name, expected)

    def test_no_extra_wait_at_initial_home_or_for_normal_wave(self):
        home = Screen("home", gems=100, layout="hero")
        player = self.player("wave")
        self.assertIsNone(player.feed(0, home))
        self.assertEqual(player.feed(0.2, home).name, "open Hero slot 1")
        plain = Player("wave", lambda *args: None, watch_ads=False)
        plain.feed(0, Screen("battle"))
        plain.feed(1, home)
        self.assertEqual(plain.feed(1.9, home).name, "start next Battle")


if __name__ == "__main__":
    unittest.main()
