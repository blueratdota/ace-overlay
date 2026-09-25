import ctypes
import unittest

from ace_overlay.shm import Physics


class PhysicsLayoutTest(unittest.TestCase):
    """Offsets from the documented AC EVO physics block. A drift here breaks every field after it."""

    def test_size(self):
        self.assertEqual(ctypes.sizeof(Physics), 800)

    def test_offsets(self):
        expected = {
            "gas": 4, "brake": 8, "gear": 16, "rpms": 20, "steerAngle": 24, "speedKmh": 28,
            "pitLimiterOn": 248, "clutch": 364, "tyreTempO": 400, "isAIControlled": 416,
            "brakeBias": 564, "currentMaxRpm": 588, "tcInAction": 672, "absInAction": 676,
            "padLife": 740, "absVibrations": 796,
        }
        for name, offset in expected.items():
            with self.subTest(field=name):
                self.assertEqual(getattr(Physics, name).offset, offset)


if __name__ == "__main__":
    unittest.main()
