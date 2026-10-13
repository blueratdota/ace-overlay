"""Race standings worked out from where the cars are.

AC EVO doesn't publish other drivers' names, cars, classes or lap times. tools/probe_standings.py
searched every shared-memory block during a 21-car session and found only the player's. It does
publish every car's world position (graphics.car_coordinates, metres, y up) with a stable 128-bit id
per entry (car_ids). So:

- TrackMap learns the racing line from the player's own driving. The player's lap fraction
  (graphics.npos) is known, so each sample ties a world position to a lap fraction.
- Every other car is projected onto that line for its lap fraction, and its laps are counted as it
  crosses the line. Laps + fraction = progress, which orders the field in a race.
- Each car's passing time at CHECKPOINTS points per lap is recorded (interpolated between updates).
  That gives lap times, and the gap to the leader at the same point on track.

Laps are counted from when a car is first seen, relative to the player (assumed within half a lap).
A car that was already lapped before that is placed one or more laps too high.
"""

import math
import time
from dataclasses import dataclass, field

from .shm import STATUS_LIVE, text

BINS = 1000  # racing-line points per lap
READY_COVERAGE = 0.97  # share of the line that must be known before cars are placed on it
MAX_FILL_STEP = 0.02  # samples further apart than this (lap share) aren't joined: a reset or a pit stop
OUTLIER_M = 30.0  # a sample this far from an established point is an off: not learned
SEARCH_BINS = 40  # each car is first looked for this many points either side of where it last was
LOST_M = 40.0  # further than this from the line: search the whole line
CHECKPOINTS = 50  # timing points per lap
KEEP_LAPS = 3  # checkpoint times kept per car
TELEPORT_M = 150.0  # moved this far in one update: the car was reset (e.g. back to the pits)
PIT_OFFSET_M = 10.0  # this far from the racing line ...
PIT_SPEED_KMH = 90.0  # ... and slower than this = in the pit lane or box
GONE_S = 10.0  # a car that hasn't been in the entry list this long has left


class TrackMap:
    """The racing line as BINS points, one per 1/BINS of a lap (at the bin's centre)."""

    def __init__(self):
        self.x = [0.0] * BINS
        self.z = [0.0] * BINS
        self.n = [0] * BINS  # samples averaged into each point (capped, so the line keeps adapting)
        self.filled = 0
        self.dirty = False  # learned something since the last save
        self._last = None  # previous learning sample (frac, x, z)

    @property
    def coverage(self):
        return self.filled / BINS

    @property
    def ready(self):
        return self.coverage >= READY_COVERAGE

    def learn(self, frac, x, z):
        """Add the player's position at lap fraction `frac`. Every point between this sample and the
        previous one is filled in along the straight line between them, so the tick rate doesn't
        leave holes."""
        prev, self._last = self._last, (frac, x, z)
        if prev is None:
            self._add(round(frac * BINS - 0.5) % BINS, x, z)
            return
        pf, px, pz = prev
        step = (frac - pf) % 1.0
        if step > MAX_FILL_STEP:  # backwards, or a jump
            self._add(round(frac * BINS - 0.5) % BINS, x, z)
            return
        first = math.ceil(pf * BINS - 0.5)  # first bin centre at or after the previous sample
        for k in range(first, first + int(step * BINS) + 2):
            ahead = ((k + 0.5) / BINS - pf) % 1.0
            if 0 < ahead <= step:
                t = ahead / step
                self._add(k % BINS, px + (x - px) * t, pz + (z - pz) * t)

    def _add(self, b, x, z):
        n = self.n[b]
        if n == 0:
            self.filled += 1
        elif n >= 3 and math.hypot(x - self.x[b], z - self.z[b]) > OUTLIER_M:
            return
        n = min(n + 1, 10)
        self.x[b] += (x - self.x[b]) / n
        self.z[b] += (z - self.z[b]) / n
        self.n[b] = n
        self.dirty = True

    def _nearest(self, x, z, bins):
        best, best_d2 = None, float("inf")
        xs, zs, ns = self.x, self.z, self.n
        for k in bins:
            b = k % BINS
            if ns[b]:
                d2 = (xs[b] - x) ** 2 + (zs[b] - z) ** 2
                if d2 < best_d2:
                    best, best_d2 = b, d2
        return best, math.sqrt(best_d2)

    def _neighbour(self, b, direction):
        for k in range(1, 20):
            nb = (b + direction * k) % BINS
            if self.n[nb]:
                return nb
        return None

    def project(self, x, z, hint=None):
        """(lap fraction, distance from the line in m, nearest point) for a world position, or None.
        `hint` is the point returned last time for this car; the search starts around it."""
        b = None
        if hint is not None:
            b, dist = self._nearest(x, z, range(hint - SEARCH_BINS, hint + SEARCH_BINS + 1))
        if b is None or dist > LOST_M:
            b, dist = self._nearest(x, z, range(BINS))
        if b is None:
            return None
        frac, best = (b + 0.5) / BINS, dist
        for nb in (self._neighbour(b, -1), self._neighbour(b, 1)):  # refine onto the segments either side
            if nb is None:
                continue
            ax, az, bx, bz = self.x[b], self.z[b], self.x[nb], self.z[nb]
            dx, dz = bx - ax, bz - az
            length2 = dx * dx + dz * dz
            if length2 == 0:
                continue
            t = max(0.0, min(1.0, ((x - ax) * dx + (z - az) * dz) / length2))
            d = math.hypot(x - (ax + t * dx), z - (az + t * dz))
            if d < best:
                span = ((nb - b + BINS // 2) % BINS) - BINS // 2  # signed bins from b to nb
                frac, best = (b + 0.5 + t * span) / BINS, d
        return frac % 1.0, best, b

    def dumps(self):
        return ";".join(f"{self.x[b]:.1f},{self.z[b]:.1f}" if self.n[b] else "" for b in range(BINS))

    @classmethod
    def loads(cls, data):
        track = cls()
        points = data.split(";") if data else []
        if len(points) != BINS:
            return track
        for b, point in enumerate(points):
            if point:
                x, z = point.split(",")
                track.x[b], track.z[b], track.n[b] = float(x), float(z), 3
                track.filled += 1
        return track


@dataclass
class Car:
    key: tuple
    number: int  # its slot in the entry list when first seen, from 1; shown as "Car N"
    is_player: bool = False
    laps: int = 0
    frac: float = 0.0
    hint: int = None
    x: float = 0.0
    z: float = 0.0
    seen: float = 0.0  # time of the last update
    speed: float = 0.0  # km/h, smoothed
    off_line: float = 0.0  # m from the racing line
    in_pit: bool = False
    next_cp: int = 0  # next checkpoint to time (counted from lap 0)
    passed: dict = field(default_factory=dict)  # checkpoint -> time
    last_lap: float = None  # s
    best_lap: float = None

    @property
    def progress(self):
        return self.laps + self.frac


@dataclass
class Entry:
    car: Car
    position: int
    gap: float = None  # s behind the leader (race) or behind the fastest lap (other sessions)
    laps_down: int = 0
    last_lap: float = None
    best_lap: float = None
    session_best: bool = False  # holds the fastest lap of the session


class Standings:
    """Keeps every car's progress and timing. update() once per tick; entries() for the table."""

    def __init__(self, time_scale=1.0):
        self.time_scale = time_scale  # the demo runs a 92 s lap in 10 s
        self.track = TrackMap()
        self.track_key = None  # (track, layout) the line belongs to; the panel loads/saves lines by it
        self.session = None
        self.is_race = False
        self.cars = {}
        self.player_laps = 0
        self.player_name = ""

    def reset(self, session):
        self.session = session
        self.cars = {}
        self.player_laps = 0

    def update(self, g, static, now=None):
        """Feed one graphics + static snapshot. Returns True if the track changed (load its line)."""
        now = time.monotonic() if now is None else now
        if g is None or static is None:
            return False
        track_key = (text(static.track), text(static.track_configuration))
        session = (track_key, text(static.session_name), static.session_id)
        track_changed = track_key != self.track_key
        if track_changed:
            self.track_key, self.track = track_key, TrackMap()
        if session != self.session or g.total_lap_count < self.player_laps:  # new session or a restart
            self.reset(session)
        self.player_laps = g.total_lap_count
        self.is_race = "race" in session[1].lower()
        self.player_name = " ".join(s.capitalize() for s in (text(g.driver_name), text(g.driver_surname)) if s)

        player_key = tuple(g.player_car_id)
        slots = [(k, tuple(g.car_ids[k]), g.car_coordinates[k]) for k in range(min(g.active_cars, 60))]
        slots = [(k, key, xyz) for k, key, xyz in slots if any(key)]
        player = next(((xyz[0], xyz[2]) for _, key, xyz in slots if key == player_key), None)
        if player is not None and g.status == STATUS_LIVE and not g.is_in_pit_lane:
            self.track.learn(g.npos, *player)
        if not self.track.ready or g.status != STATUS_LIVE:
            return track_changed

        reference = None  # the player's progress; others' laps are first counted from it
        for slot, key, (x, _, z) in sorted(slots, key=lambda s: s[1] != player_key):  # player first
            car = self.cars.get(key)
            if car is None:
                car = self.cars[key] = Car(key, slot + 1, key == player_key)
            if car.is_player:
                frac, off_line, hint = g.npos, 0.0, None
                car.in_pit = bool(g.is_in_pit_lane)
            else:
                found = self.track.project(x, z, car.hint)
                if found is None:
                    continue
                frac, off_line, hint = found
            self._move(car, frac, x, z, now, reference)
            if car.is_player:
                reference = car.progress
            car.hint, car.off_line = hint, off_line
            if not car.is_player:
                car.in_pit = off_line > PIT_OFFSET_M and car.speed < PIT_SPEED_KMH
        for key in [k for k, c in self.cars.items() if now - c.seen > GONE_S]:
            del self.cars[key]
        return track_changed

    def _move(self, car, frac, x, z, now, reference):
        if not car.seen:  # first sight: count its laps from the player's, within half a lap
            car.laps = round(reference - frac) if reference is not None else 0
            car.frac, car.x, car.z, car.seen = frac, x, z, now
            car.next_cp = math.floor(car.progress * CHECKPOINTS) + 1
            return
        dt = now - car.seen
        moved = math.hypot(x - car.x, z - car.z)
        old = car.progress
        if frac - car.frac < -0.5:
            car.laps += 1
        elif frac - car.frac > 0.5:
            car.laps -= 1
        car.frac, car.x, car.z, car.seen = frac, x, z, now
        new = car.progress
        if dt > 0:
            car.speed += (moved / dt * 3.6 - car.speed) * min(1.0, dt * 4)
        if moved > TELEPORT_M:  # reset to the pits: the lap in progress can't be timed
            car.passed.clear()
            car.next_cp = math.floor(new * CHECKPOINTS) + 1
            car.speed = 0.0
            return
        while car.next_cp / CHECKPOINTS <= new:
            cp = car.next_cp
            at = now - dt * (new - cp / CHECKPOINTS) / (new - old) if new > old else now
            car.passed[cp] = at
            if cp % CHECKPOINTS == 0 and cp - CHECKPOINTS in car.passed:
                car.last_lap = (at - car.passed[cp - CHECKPOINTS]) * self.time_scale
                car.best_lap = min(car.best_lap or car.last_lap, car.last_lap)
            car.next_cp += 1
        for cp in [c for c in car.passed if c < car.next_cp - KEEP_LAPS * CHECKPOINTS]:
            del car.passed[cp]

    def entries(self, player_last_ms=0, player_best_ms=0):
        """The table, in order. The player's lap times come from the game (only valid laps count),
        everyone else's from their measured line crossings."""
        rows = []
        for car in self.cars.values():
            last, best = car.last_lap, car.best_lap
            if car.is_player:
                last = player_last_ms / 1000 if player_last_ms > 0 else None
                best = player_best_ms / 1000 if player_best_ms > 0 else None
            rows.append(Entry(car, 0, last_lap=last, best_lap=best))
        if self.is_race:
            rows.sort(key=lambda e: -e.car.progress)
        else:
            rows.sort(key=lambda e: (e.best_lap is None, e.best_lap or 0, e.car.number))
        fastest = min((e.best_lap for e in rows if e.best_lap), default=None)
        leader = rows[0].car if rows else None
        for position, e in enumerate(rows, 1):
            e.position = position
            e.session_best = fastest is not None and e.best_lap == fastest
            if position == 1:
                continue
            if self.is_race:
                e.laps_down = int(leader.progress - e.car.progress)
                cp = e.car.next_cp - 1
                if not e.laps_down and cp in e.car.passed and cp in leader.passed:
                    e.gap = (e.car.passed[cp] - leader.passed[cp]) * self.time_scale
            elif e.best_lap is not None:
                e.gap = e.best_lap - fastest
        return rows


def visible_rows(count, player_row, limit, leaders=3):
    """Row indices to show: all of them if they fit, else the leaders plus a window around the player."""
    if count <= limit:
        return list(range(count))
    if player_row is None or player_row < limit:
        return list(range(limit))
    rest = limit - leaders
    start = min(max(player_row - rest // 2, leaders), count - rest)
    return list(range(leaders)) + list(range(start, start + rest))
