import ctypes
import unittest

from ace_overlay.shm import Graphics, Physics, TyreState


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


class GraphicsLayoutTest(unittest.TestCase):
    """Offsets verified against the live game (RPM matched physics, tyre compound name decoded)."""

    def test_tyre_state_size(self):
        self.assertEqual(ctypes.sizeof(TyreState), 256)

    def test_offsets(self):
        expected = {"rpm": 40, "tc_active": 45, "abs_active": 46, "tyres": 220}
        for name, offset in expected.items():
            with self.subTest(field=name):
                self.assertEqual(getattr(Graphics, name).offset, offset)
        self.assertEqual(ctypes.sizeof(Graphics), 220 + 4 * 256)


if __name__ == "__main__":
    unittest.main()
