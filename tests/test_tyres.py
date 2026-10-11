import unittest
from types import SimpleNamespace

from ace_overlay.tyres import PSI_PER_C, TyreAdvisor, Window


def normalised(value, low, high, scale):
    return 1.0 + (min(0.0, value - low) + max(0.0, value - high)) / scale


class WindowTest(unittest.TestCase):
    def test_learns_edges_and_scale_from_readings_outside(self):
        w = Window(default_scale=10.0)  # deliberately wrong; two readings per side correct it
        for psi in (25.0, 26.0, 28.0, 30.0, 32.0, 33.0):
            w.observe(psi, normalised(psi, 27.0, 31.0, 3.0))
        self.assertAlmostEqual(w.low, 27.0)
        self.assertAlmostEqual(w.high, 31.0)
        self.assertAlmostEqual(w.target(), 29.0)

    def test_no_target_until_both_edges_seen(self):
        w = Window(default_scale=3.0)
        for psi in (26.0, 28.0, 30.0):  # never over the window
            w.observe(psi, normalised(psi, 27.0, 31.0, 3.0))
        self.assertAlmostEqual(w.low, 27.0)
        self.assertIsNone(w.high)
        self.assertIsNone(w.target())
        self.assertEqual((w.inside_min, w.inside_max), (28.0, 30.0))


def tyre(psi, bulk_c, name=b"Test"):
    return SimpleNamespace(pressure=psi, temperature_c=bulk_c, compound_front=name, compound_rear=name,
                           normalized_pressure=1.0, temperature_center=bulk_c, normalized_temperature_center=1.0,
                           normalized_temperature_core=1.0)


class AdviceTest(unittest.TestCase):
    def setUp(self):
        self.advisor = TyreAdvisor()
        c = self.advisor.compound("Test")
        c.pressure.low, c.pressure.high = 27.0, 31.0  # target 29.0 psi hot
        c.surface.low, c.surface.high = 60.0, 95.0  # target 77.5 °C

    def test_cold_tyre_is_judged_at_operating_temperature(self):
        # 26.0 psi in the garage (40 °C) is below the window now, but reaches 29.6 psi at 77.5 °C.
        a = self.advisor.advise(tyre(26.0, 40.0), 0)
        self.assertAlmostEqual(a.hot_psi, 26.0 + PSI_PER_C * 37.5)
        self.assertAlmostEqual(a.adjust, 29.0 - a.hot_psi)
        self.assertAlmostEqual(a.garage_psi, 26.0 + a.adjust)

    def test_advice_does_not_change_as_the_tyre_warms(self):
        # Same garage pressure seen at different temperatures gives the same recommendation.
        cold = self.advisor.advise(tyre(26.0, 40.0), 0)
        warm = self.advisor.advise(tyre(26.0 + PSI_PER_C * 45.0, 85.0), 0)
        self.assertAlmostEqual(cold.garage_psi, warm.garage_psi)
        self.assertAlmostEqual(cold.adjust, warm.adjust)

    def test_unknown_compound_gives_no_advice(self):
        self.assertIsNone(self.advisor.advise(tyre(26.0, 40.0, b"Other"), 0))


if __name__ == "__main__":
    unittest.main()
