"""Regression tests for Hero rotation and higher-priority skill interrupts."""

import unittest

from autoplay import Player, Screen


class HeroCastOrderTests(unittest.TestCase):
    def make_player(self, humanize=False):
        return Player("wave", lambda *args: None, watch_ads=False, humanize=humanize)

    def test_archer_and_smith_do_not_restart_hero_rotation(self):
        for humanize in (False, True):
            with self.subTest(humanize=humanize):
                player = self.make_player(humanize)
                heroes = tuple(range(2, 11))
                for i in range(4):
                    self.assertEqual(player.cast(i, heroes).name, f"cast skill {i + 1}")
                # Hero 1's bar goes away for two frames and becomes available again.
                # It must not jump ahead of Hero 5 after Archer interrupts.
                self.assertIsNone(player.cast(3.1, heroes[1:]))
                self.assertIsNone(player.cast(3.2, heroes[1:]))
                self.assertEqual(player.cast(4, (0,) + heroes).name, "cast archer skill 1")
                self.assertEqual(player.cast(5, heroes).name, "cast skill 5")
                self.assertEqual(player.cast(6, heroes, smith_ready=True, hp_low=True).name,
                                 "cast Smith (HP < 50%)")
                self.assertEqual(player.cast(7, heroes).name, "cast skill 6")
                for number in (7, 8, 9):
                    self.assertEqual(player.cast(number + 1, heroes).name, f"cast skill {number}")
                self.assertEqual(player.cast(11, heroes).name, "cast skill 1")

    def test_skips_unready_heroes_and_wraps_in_order(self):
        player = self.make_player()
        self.assertEqual(player.cast(0, (4, 7, 10)).name, "cast skill 3")
        self.assertEqual(player.cast(1, (2, 7, 10)).name, "cast skill 6")
        self.assertEqual(player.cast(2, (2, 10)).name, "cast skill 9")
        self.assertEqual(player.cast(3, (2,)).name, "cast skill 1")

    def test_smith_and_archer_priority_with_shuffled_input(self):
        player = self.make_player()
        # Normal vision provides a sorted tuple, but priorities should not depend on that.
        ready = (10, 3, 1, 2, 0)
        self.assertEqual(player.cast(0, ready, smith_ready=True, hp_low=True).name,
                         "cast Smith (HP < 50%)")
        self.assertEqual(player.cast(1, ready, smith_ready=True, hp_low=True).name,
                         "cast archer skill 1")
        self.assertEqual(player.cast(2, ready, smith_ready=True, hp_low=True).name,
                         "cast archer skill 2")
        self.assertEqual(player.cast(3, ready, smith_ready=True, hp_low=True).name,
                         "cast skill 1")

    def test_cooldown_and_battle_entry_delay_unchanged(self):
        for humanize in (False, True):
            with self.subTest(humanize=humanize):
                player = self.make_player(humanize)
                battle = Screen("battle", ready=(2, 3))
                self.assertIsNone(player.feed(0, battle))
                self.assertIsNone(player.feed(0.44, battle))
                self.assertEqual(player.feed(0.45, battle).name, "cast skill 1")
                self.assertIsNone(player.feed(0.74, battle))
                self.assertEqual(player.feed(0.76, battle).name, "cast skill 2")

    def test_skip_interrupt_keeps_cursor_victory_and_new_battle_reset_it(self):
        player = self.make_player()
        battle = Screen("battle", ready=(2, 3))
        player.feed(0, battle)
        self.assertEqual(player.feed(0.5, battle).name, "cast skill 1")
        player.feed(0.8, Screen("skip", (888, 216)))
        player.feed(1, battle)
        self.assertEqual(player.feed(1.5, battle).name, "cast skill 2")
        player.feed(2, Screen("victory"))
        self.assertEqual(player.next_hero_skill, 0)
        self.assertEqual(player.cast(3, (2, 3)).name, "cast skill 1")
        home = Screen("home")
        player.feed(4, home)
        self.assertEqual(player.feed(5, home).name, "start next Battle")
        self.assertEqual(player.next_hero_skill, 0)
        player.feed(6, battle)
        self.assertEqual(player.feed(6.5, battle).name, "cast skill 1")

    def test_smith_only_interrupts_for_low_hp(self):
        player = self.make_player()
        self.assertEqual(player.cast(0, (2, 3), smith_ready=True, hp_low=False).name,
                         "cast skill 1")
        self.assertEqual(player.cast(1, (2, 3), smith_ready=True, hp_low=True).name,
                         "cast Smith (HP < 50%)")
        self.assertEqual(player.cast(2, (2, 3), smith_ready=True, hp_low=False).name,
                         "cast skill 2")


if __name__ == "__main__":
    unittest.main()
