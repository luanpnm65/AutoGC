"""Regression tests for selecting and recovering a Hero upgrade slot."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import autoplay
from tower_upgrade import Batch, DEFAULT_HERO_SLOT, DETAIL_CLOSE, HERO_SLOTS, LIST_CLOSE, TowerUpgrade


def screen(name, *, gems=None, layout=None, level=None, cost=None, bulk_cost=None):
    return SimpleNamespace(name=name, gems=gems, layout=layout, level=level,
                           cost=cost, bulk_cost=bulk_cost)


class HeroSlotsTest(unittest.TestCase):
    def make_upgrade(self, slot=DEFAULT_HERO_SLOT, journal=None):
        return TowerUpgrade(lambda *args: None, journal, target="hero", hero_slot=slot)

    def test_all_slots_select_correct_home_coordinates(self):
        expected = [(x, y) for y in (92, 184, 277, 370) for x in (293, 373, 461)]
        self.assertEqual(list(HERO_SLOTS), expected)
        for slot, point in enumerate(expected, 1):
            with self.subTest(slot=slot):
                upgrade = self.make_upgrade(slot)
                home = screen("home", gems=100, layout="hero")
                self.assertEqual(upgrade.feed(0, home), (False, None))
                handled, action = upgrade.feed(0.2, home)
                self.assertTrue(handled)
                self.assertEqual(action.point, point)
                self.assertEqual(action.name, f"open Hero slot {slot}")

    def test_default_and_invalid_slots(self):
        self.assertEqual(self.make_upgrade().hero_slot, 3)
        for value in (0, 13, -1, True, 1.5, "1"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.make_upgrade(value)

    def test_bulk_upgrade_records_selected_slot_and_confirms(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "journal.json"
            upgrade = self.make_upgrade(12, path)
            home = screen("home", gems=100, layout="hero")
            upgrade.feed(0, home)
            upgrade.feed(0.2, home)
            detail = screen("tower", gems=100, level=20, cost=1, bulk_cost=10)
            upgrade.feed(0.4, detail)
            handled, action = upgrade.feed(0.6, detail)
            self.assertTrue(handled)
            self.assertIn("+10", action.name)
            upgrade.record_tap(action)
            self.assertEqual(json.loads(path.read_text())["hero_slot"], 12)
            self.assertEqual(json.loads(path.read_text())["pending_cost"], 10)
            recovered = self.make_upgrade(12, path)
            after = screen("tower", gems=90, level=30, cost=1, bulk_cost=10)
            recovered.feed(1, after)
            handled, next_action = recovered.feed(1.2, after)
            self.assertTrue(handled)
            self.assertEqual(recovered.batch.confirmed, 10)
            self.assertIn("+10", next_action.name)

    def test_journal_blocks_switching_while_batch_is_unfinished(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "journal.json"
            for old_slot in (None, 7):
                data = Batch(50, 10, False, pending_cost=1, hero_slot=old_slot)
                path.write_text(json.dumps(data.__dict__))
                slot = old_slot or 3
                self.assertTrue(self.make_upgrade(slot, path).recovered_pending)
                with self.assertRaisesRegex(ValueError, f"--hero-slot {slot}"):
                    self.make_upgrade(12, path)
            path.write_text(json.dumps(Batch(50, 10, False, done=True, closed=True, hero_slot=7).__dict__))
            self.assertEqual(self.make_upgrade(12, path).hero_slot, 12)

    def test_legacy_journal_without_slot_is_slot_three(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "journal.json"
            data = Batch(50, 10, False, pending_cost=1).__dict__
            del data["hero_slot"]
            path.write_text(json.dumps(data))
            self.assertTrue(self.make_upgrade(3, path).recovered_pending)
            with self.assertRaisesRegex(ValueError, "--hero-slot 3"):
                self.make_upgrade(1, path)

    def test_opening_empty_slot_times_out_and_closes_list(self):
        upgrade = self.make_upgrade(1)
        home = screen("home", gems=100, layout="hero")
        upgrade.feed(0, home)
        upgrade.feed(0.2, home)
        upgrade.feed(1, screen("castles"))
        handled, action = upgrade.feed(4.3, screen("castles"))
        self.assertTrue(handled)
        self.assertEqual(action.point, LIST_CLOSE)
        self.assertTrue(upgrade.batch.done)
        self.assertIsNone(upgrade.batch.pending_cost)

    def test_play_passes_selected_slot_and_keeps_legacy_default(self):
        for selected, expected in ((12, 12), (None, 3)):
            args = SimpleNamespace(mode="wave", skip=None, tap=False, humanize=True,
                                   upgrade_hero=30, upgrade_tower=None, upgrade_gems=None,
                                   upgrade_levels=None, hero_slot=selected, auto_captcha=False,
                                   ads=False, video=Path("preview.mp4"))
            with self.subTest(selected=selected), \
                    patch.object(autoplay, "TowerUpgrade") as upgrade, \
                    patch.object(autoplay, "Vision"), \
                    patch.object(autoplay, "replay_frames", return_value=[]), \
                    patch("builtins.print"):
                autoplay.play(args, None, lambda *args: None, None)
                self.assertEqual(upgrade.call_args.kwargs["hero_slot"], expected)
                self.assertEqual(upgrade.call_args.kwargs["gem_threshold"], 30)

    def test_cli_selection_and_validation(self):
        def run(*flags):
            with patch("sys.argv", ["autoplay.py", *flags]), \
                    patch.object(autoplay, "resolve_target", return_value=None), \
                    patch.object(autoplay, "play") as play:
                autoplay.main()
                return play.call_args.args[0]

        args = run("--upgrade-hero", "30", "--hero-slot", "12")
        self.assertEqual((args.upgrade_hero, args.hero_slot), (30, 12))
        self.assertIsNone(run("--upgrade-hero").hero_slot)
        for flags in (("--upgrade-hero", "--hero-slot", "0"),
                      ("--upgrade-hero", "--hero-slot", "13"),
                      ("--hero-slot", "1"),
                      ("--upgrade-tower", "--hero-slot", "1")):
            with self.subTest(flags=flags), patch("sys.stderr"), self.assertRaises(SystemExit):
                run(*flags)


if __name__ == "__main__":
    unittest.main()
