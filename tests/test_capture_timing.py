"""Timing tests for live ADB frame capture."""

from io import BytesIO
import unittest
from unittest.mock import patch

from PIL import Image

import autoplay


class CaptureTimingTests(unittest.TestCase):
    def test_target_interval_accounts_for_time_already_spent(self):
        buffer = BytesIO()
        Image.new("RGB", (16, 9)).save(buffer, format="PNG")
        for humanize in (False, True):
            for spent, expected in ((0.05, 0.13), (0.25, 0)):
                with self.subTest(humanize=humanize, spent=spent), \
                        patch.object(autoplay, "monotonic", side_effect=[10.0, 10.0, 10.0 + spent, 10.3]), \
                        patch.object(autoplay, "sleep") as sleep, \
                        patch.object(autoplay, "adb_run", return_value=buffer.getvalue()) as adb:
                    frames = autoplay.adb_frames("adb", "device", 0, humanize=humanize)
                    first = next(frames)
                    second = next(frames)
                    frames.close()
                    self.assertEqual(first[0], 0)
                    self.assertAlmostEqual(second[0], 0.3)
                    self.assertEqual(adb.call_count, 2)
                    self.assertAlmostEqual(sleep.call_args.args[0], expected)


if __name__ == "__main__":
    unittest.main()
