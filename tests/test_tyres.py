import unittest
from types import SimpleNamespace

from ace_overlay.tyres import MARGIN_PSI, PSI_PER_C, TyreAdvisor, Window


def normalised(value, low, high, scale):
    return 1.0 + (min(0.0, value - low) + max(0.0, value - high)) / scale


class WindowTest(unittest.TestCase):
    def test_learns_edges_and_scale_from_readings_outside(self):
        w = Window(default_scale=10.0)  # deliberately wrong; two readings per side correct it
        for psi in (25.0, 26.0, 28.0, 30.0, 32.0, 33.0):
            w.observe(psi, normalised(psi, 27.0, 31.0, 3.0))
        self.assertAlmostEqual(w.low, 27.0)
        self.assertAlmostEqual(w.high, 31.0)

    def test_inside_readings_only_bound_the_window(self):
        w = Window(default_scale=3.0)
        for psi in (28.0, 30.0):
            w.observe(psi, 1.0)
        self.assertIsNone(w.low)
        self.assertIsNone(w.high)
        self.assertEqual((w.inside_min, w.inside_max), (28.0, 30.0))


def tyre(psi, bulk_c, name=b"SuperCar (SC)"):
    return SimpleNamespace(pressure=psi, temperature_c=bulk_c, compound_front=name, compound_rear=name)


def garage(psi_at_40, bulk_c):
    """A tyre set to psi_at_40 in the garage, seen at bulk_c."""
    return tyre(psi_at_40 + PSI_PER_C * (bulk_c - 40.0), bulk_c)


class AdviceTest(unittest.TestCase):
    """SuperCar is seeded from live measurements: pressure from 27.0 psi, working temperature 60-95 °C."""

    def setUp(self):
        self.advisor = TyreAdvisor()

    def test_known_compound_needs_no_learning(self):
        self.assertIsNotNone(self.advisor.advise(garage(27.0, 64.0), 0))

    def test_tyre_that_warms_into_the_window_is_fine(self):
        # 26.0 in the garage is 27.9 at 60 °C: inside the window (27.0 + margin) once working.
        a = self.advisor.advise(garage(26.0, 40.0), 0)
        self.assertEqual(a.adjust, 0.0)
        self.assertAlmostEqual(a.garage_psi, 26.0)

    def test_tyre_still_low_at_working_temperature_gets_more_air(self):
        a = self.advisor.advise(garage(25.0, 40.0), 0)
        at_60 = 25.0 + PSI_PER_C * 20
        self.assertAlmostEqual(a.adjust, 27.0 + MARGIN_PSI - at_60)
        self.assertAlmostEqual(a.garage_psi, 25.0 + a.adjust)

    def test_advice_does_not_change_as_the_tyre_warms(self):
        cold, hot = self.advisor.advise(garage(25.0, 40.0), 0), self.advisor.advise(garage(25.0, 85.0), 0)
        self.assertAlmostEqual(cold.adjust, hot.adjust)
        self.assertAlmostEqual(cold.garage_psi, hot.garage_psi)

    def test_too_high_at_the_top_of_the_temperature_window_once_the_upper_edge_is_known(self):
        self.advisor.compound("SuperCar (SC)").pressure.high = 31.0
        a = self.advisor.advise(garage(29.0, 60.0), 0)
        at_95 = 29.0 + PSI_PER_C * 55
        self.assertAlmostEqual(a.adjust, 31.0 - MARGIN_PSI - at_95)

    def test_hot_pressure_is_quoted_at_the_middle_of_the_temperature_window(self):
        a = self.advisor.advise(garage(27.0, 50.0), 0)
        self.assertAlmostEqual(a.ref_c, 77.5)
        self.assertAlmostEqual(a.hot_psi, 27.0 + PSI_PER_C * 37.5)

    def test_unknown_compound_gives_no_advice(self):
        self.assertIsNone(self.advisor.advise(tyre(26.0, 40.0, b"Mystery"), 0))


if __name__ == "__main__":
    unittest.main()
