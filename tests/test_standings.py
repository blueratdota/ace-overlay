import math
import unittest
from types import SimpleNamespace

from ace_overlay.shm import STATUS_LIVE
from ace_overlay.standings import BINS, Standings, TrackMap, visible_rows

RADIUS = 500.0  # a circular test track, 3.1 km
DT = 0.05
PERIOD = 100.0  # s per lap for every car


def at(frac):
    angle = 2 * math.pi * frac
    return RADIUS * math.cos(angle), 30.0, RADIUS * math.sin(angle)


def static(session="Race", track=b"Test Ring"):
    return SimpleNamespace(track=track, track_configuration=b"", session_name=session.encode(), session_id=0)


def graphics(progress, player=0, laps=None):
    """progress: each car's laps driven; car `player` is the player."""
    player_progress = progress[player]
    return SimpleNamespace(
        status=STATUS_LIVE, is_in_pit_lane=False, npos=player_progress % 1.0,
        total_lap_count=int(player_progress) if laps is None else laps,
        driver_name=b"john", driver_surname=b"goc", player_car_id=(player + 1, 7),
        car_ids=[(k + 1, 7) for k in range(len(progress))],
        car_coordinates=[at(p % 1.0) for p in progress], active_cars=len(progress))


def run(standings, offsets, start, end, session="Race"):
    """Drive every car at PERIOD per lap from time `start` to `end`; offsets are in laps."""
    t = start
    while t < end:
        standings.update(graphics([t / PERIOD + o for o in offsets]), static(session), now=t)
        t += DT
    return t


class TrackMapTest(unittest.TestCase):
    def learned(self, samples_per_lap=250):
        track = TrackMap()
        for k in range(samples_per_lap + 1):
            x, _, z = at(k / samples_per_lap)
            track.learn((k / samples_per_lap) % 1.0, x, z)
        return track

    def test_sparse_samples_fill_the_whole_line(self):
        self.assertEqual(self.learned().filled, BINS)

    def test_projects_back_to_the_lap_fraction(self):
        track = self.learned()
        for frac in (0.0, 0.1234, 0.5, 0.9999):
            x, _, z = at(frac)
            found, dist, _ = track.project(x + 3.0 * math.cos(2 * math.pi * frac), z, None)  # 3 m off line
            self.assertAlmostEqual((found - frac + 0.5) % 1.0 - 0.5, 0.0, delta=0.0005)
            self.assertLess(dist, 3.5)

    def test_round_trip(self):
        track = self.learned()
        again = TrackMap.loads(track.dumps())
        self.assertTrue(again.ready)
        self.assertAlmostEqual(again.x[123], track.x[123], delta=0.06)

    def test_a_jump_is_not_joined_up(self):
        track = TrackMap()
        for frac in (0.1, 0.5):
            x, _, z = at(frac)
            track.learn(frac, x, z)
        self.assertEqual(track.filled, 2)


class RaceTest(unittest.TestCase):
    def setUp(self):
        self.standings = Standings()
        # player (car 1) in the middle: car 2 is 5 s ahead, car 3 is 2 s behind
        self.offsets = (0.0, 0.05, -0.02)
        self.end = run(self.standings, self.offsets, 0.0, 4.3 * PERIOD)

    def test_needs_a_lap_to_learn_the_track(self):
        fresh = Standings()
        run(fresh, self.offsets, 0.0, 0.5 * PERIOD)
        self.assertFalse(fresh.track.ready)
        self.assertEqual(fresh.entries(), [])

    def test_order_gaps_and_lap_times(self):
        rows = self.standings.entries()
        self.assertEqual([e.car.number for e in rows], [2, 1, 3])
        self.assertIsNone(rows[0].gap)
        self.assertAlmostEqual(rows[1].gap, 5.0, delta=0.1)
        self.assertAlmostEqual(rows[2].gap, 7.0, delta=0.1)
        for e in rows[1:]:  # the player's lap times come from the game, the others' are measured
            if not e.car.is_player:
                self.assertAlmostEqual(e.last_lap, PERIOD, delta=0.05)
        self.assertEqual(self.standings.player_name, "John Goc")

    def test_lapped_car(self):
        standings = Standings()
        t = run(standings, (0.0, 0.3, -0.3), 0.0, 1.5 * PERIOD)
        # car 3 stops: after the leader gains a lap on it, it shows laps down instead of a gap
        stopped = 1.5 - 0.3
        while t < 3.0 * PERIOD:
            standings.update(graphics([t / PERIOD, t / PERIOD + 0.3, stopped]), static(), now=t)
            t += DT
        rows = standings.entries()
        self.assertEqual(rows[-1].car.number, 3)
        self.assertEqual(rows[-1].laps_down, int(rows[0].car.progress - rows[-1].car.progress))
        self.assertGreaterEqual(rows[-1].laps_down, 1)
        self.assertIsNone(rows[-1].gap)

    def test_reset_to_the_pits_drops_the_lap_in_progress(self):
        car = self.standings.cars[(3, 7)]
        timed = car.last_lap
        t = self.end
        g = graphics([t / PERIOD, t / PERIOD + 0.05, t / PERIOD - 0.02])
        g.car_coordinates[2] = at(0.5)  # teleported half a lap away
        self.standings.update(g, static(), now=t)
        self.assertEqual(car.passed, {})
        self.assertEqual(car.last_lap, timed)

    def test_new_session_starts_over(self):
        t = self.end
        self.standings.update(graphics([t / PERIOD] * 3), static("Qualifying"), now=t)
        self.assertTrue(all(c.last_lap is None for c in self.standings.cars.values()))
        self.assertTrue(self.standings.track.ready)  # same track: the line is kept


class PracticeTest(unittest.TestCase):
    def test_ordered_by_best_lap(self):
        standings = Standings()
        t = run(standings, (0.0, 0.3, 0.6), 0.0, 1.2 * PERIOD, "Practice")
        # car 3 sets a faster lap than car 2 by driving its next lap at 95 s
        progress = {2: t / PERIOD + 0.3, 3: t / PERIOD + 0.6}
        while t < 3.5 * PERIOD:
            progress[2] += DT / PERIOD
            progress[3] += DT / (PERIOD * 0.95)
            standings.update(graphics([t / PERIOD, progress[2], progress[3]]), static("Practice"), now=t)
            t += DT
        rows = standings.entries(player_best_ms=101_000)
        self.assertEqual([e.car.number for e in rows], [3, 2, 1])
        self.assertTrue(rows[0].session_best)
        self.assertAlmostEqual(rows[1].gap, PERIOD - 0.95 * PERIOD, delta=0.1)
        self.assertAlmostEqual(rows[2].best_lap, 101.0)


class VisibleRowsTest(unittest.TestCase):
    def test_everything_fits(self):
        self.assertEqual(visible_rows(5, 4, 12), [0, 1, 2, 3, 4])

    def test_player_near_the_front(self):
        self.assertEqual(visible_rows(20, 2, 6), [0, 1, 2, 3, 4, 5])

    def test_leaders_then_a_window_around_the_player(self):
        self.assertEqual(visible_rows(20, 11, 8), [0, 1, 2, 9, 10, 11, 12, 13])

    def test_player_at_the_back(self):
        self.assertEqual(visible_rows(20, 19, 8), [0, 1, 2, 15, 16, 17, 18, 19])


if __name__ == "__main__":
    unittest.main()
