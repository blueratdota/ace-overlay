import ctypes
import unittest

from types import SimpleNamespace

from ace_overlay.shm import STATUS_LIVE, Electronics, Graphics, Physics, SessionState, TyreState, is_driving


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
    """Offsets verified against the live game (RPM matched physics; tyre compound, car model, lap times
    and fuel decoded correctly)."""

    def test_substruct_sizes(self):
        for struct, size in ((TyreState, 256), (Electronics, 128), (SessionState, 256)):
            with self.subTest(struct=struct.__name__):
                self.assertEqual(ctypes.sizeof(struct), size)

    def test_size(self):
        self.assertEqual(ctypes.sizeof(Graphics), 4900)

    def test_offsets(self):
        expected = {
            "rpm": 40, "tc_active": 45, "abs_active": 46, "tyres": 220, "npos": 1244,
            "fuel_liter_per_lap": 1460, "laps_possible_with_fuel": 1464, "electronics": 1872,
            "total_lap_count": 2384, "current_pos": 2388, "last_laptime_ms": 2396, "best_laptime_ms": 2400,
            "session_state": 2476, "car_model": 3086, "is_in_pit_lane": 3120, "is_valid_lap": 3121,
            "gap_ahead": 3844, "gap_behind": 3848, "fuel_per_lap": 3856, "max_fuel": 3928, "car_ids": 3940,
            "status": 4, "turbo_boost": 144, "max_turbo_boost": 3932, "is_in_pit_box": 3119,
        }
        for name, offset in expected.items():
            with self.subTest(field=name):
                self.assertEqual(getattr(Graphics, name).offset, offset)
        self.assertEqual(Electronics.brake_bias.offset, 8)
        self.assertEqual(SessionState.time_left_ms.offset, 48)
        self.assertEqual(SessionState.total_lap.offset, 68)


class DrivingTest(unittest.TestCase):
    def test_out_of_the_box_in_a_live_session(self):
        live = STATUS_LIVE
        self.assertTrue(is_driving(SimpleNamespace(status=live, is_in_pit_box=False)))
        self.assertFalse(is_driving(SimpleNamespace(status=live, is_in_pit_box=True)))
        self.assertFalse(is_driving(SimpleNamespace(status=live + 1, is_in_pit_box=False)))
        self.assertFalse(is_driving(None))


if __name__ == "__main__":
    unittest.main()
