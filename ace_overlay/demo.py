"""Fake telemetry so the overlay can be developed without the game running."""

import math
import time

from .shm import Graphics, Physics
from .tyres import GARAGE_C, PSI_PER_C

MAX_RPM = 8000
# Top speed (km/h) at redline for each forward gear, indexed by the raw gear value (2 = 1st).
GEAR_TOP = {2: 70, 3: 100, 4: 130, 5: 160, 6: 190, 7: 250}
FRONT = (True, True, False, False)  # FL, FR, RL, RR
LEFT = (True, False, True, False)
V_EXIT, V_TOP, V_APEX = 120.0, 225.0, 90.0  # km/h at lap start, end of straight, apex
DEMO_LAP_MS = 92_000  # the info panel reports each 10 s demo lap as a 1:32 lap
DEMO_COLD_PSI = (26.0, 26.2, 24.6, 29.4)  # FL, FR, RL, RR garage pressures: fronts right, rears one low / one high
DEMO_WINDOW_PSI = (27.0, 31.0)  # ideal pressure window; normalised = 1.0 inside, ±1/3 per psi outside
DEMO_WINDOW_C = (60.0, 95.0)  # ideal temperature window (surface ±1/30 per °C, core ±1/20 per °C outside)


def normalised(value, window, scale):
    """The game's normalisation: exactly 1.0 inside the window, linear outside it."""
    low, high = window
    return 1.0 + (min(0.0, value - low) + max(0.0, value - high)) / scale


def lap_speed(t):
    """Speed as a function of lap time, so every lap is identical (and loops seamlessly)."""
    if t < 6.0:  # straight: strong pull that tapers off
        return V_EXIT + (V_TOP - V_EXIT) * (1 - math.exp(-t / 2.2)) / (1 - math.exp(-6 / 2.2))
    if t < 7.5:  # heavy initial brake, easing off as the brake trails
        x = (t - 6.0) / 1.5
        return V_TOP - (V_TOP - V_APEX) * (1 - (1 - x) ** 2)
    return V_APEX + (V_EXIT - V_APEX) * (t - 7.5) / 2.5  # exit


class DemoSource:
    """Loops a 10 s 'lap': a straight, a trail-braked left-hander, then the exit."""

    def __init__(self):
        self._start = self._last = time.monotonic()
        self._speed = V_EXIT
        self._gear = 5
        self._shift_until = 0.0
        self._packet = 0
        # [wheel][inner, middle, outer] surface temperatures, plus a slower bulk (carcass) temperature.
        # They start at the 40 °C garage temperature, like leaving the pits on fresh tyres.
        self._temps = [[40.0, 40.0, 40.0] for _ in range(4)]
        self._bulk = [40.0] * 4
        self.graphics = None  # Graphics snapshot from the last read(), like LiveSource

    def read(self):
        now = time.monotonic()
        dt, self._last = now - self._last, now
        t = (now - self._start) % 10.0

        if t < 6.0:
            gas, brake, corner = min(1.0, t / 0.4), 0.0, 0.0
        elif t < 7.5:
            gas, brake = 0.0, max(0.0, 1.0 - (t - 6.0) / 1.5)
            corner = math.sin((t - 6.0) / 3.0 * math.pi)
        else:
            gas, brake = min(1.0, (t - 7.5) / 1.8), 0.0
            corner = math.sin((t - 6.0) / 3.0 * math.pi) if t < 9.0 else 0.0

        self._speed = lap_speed(t)

        rpm = self._speed / GEAR_TOP[self._gear] * MAX_RPM
        if rpm >= MAX_RPM and self._gear < 7:  # shift at the limiter, so the shift light gets its moment
            self._gear += 1
            self._shift_until = now + 0.12
        elif self._gear > 2 and self._speed < GEAR_TOP[self._gear - 1] * 0.65:
            self._gear -= 1
            self._shift_until = now + 0.12
        rpm = max(1500, min(MAX_RPM, self._speed / GEAR_TOP[self._gear] * MAX_RPM))

        self._update_tyres(dt, gas, brake, corner)

        self._packet += 1
        p = Physics()
        p.packetId = self._packet
        p.gas = gas
        p.brake = brake
        p.clutch = 1.0 if now < self._shift_until else 0.0
        p.gear = self._gear
        p.rpms = int(rpm)
        p.currentMaxRpm = MAX_RPM
        p.speedKmh = self._speed
        # ABS chatters under heavy braking; TC cuts in on the corner exit.
        p.absInAction = int(brake > 0.55 and int(now * 20) % 3 != 0)
        p.tcInAction = int(7.9 < t < 8.9 and int(now * 14) % 2 == 0)
        # Per-wheel slip: braking locks the unloaded inside (left) wheels more as the car turns in;
        # on the exit the inside rear spins up.
        lock = brake * 0.12
        spin = gas * 0.18 if 7.9 < t < 8.9 else 0.0
        p.slipRatio[0] = -lock * (1 + 2 * corner)  # FL
        p.slipRatio[1] = -lock  # FR
        p.slipRatio[2] = -lock * 0.6 * (1 + 2 * corner) + spin  # RL
        p.slipRatio[3] = -lock * 0.6 + spin * 0.3  # RR
        for w in range(4):
            p.tyreTempI[w], p.tyreTempM[w], p.tyreTempO[w] = self._temps[w]
        p.airTemp, p.roadTemp = 24.0, 33.0
        self.graphics = self._graphics(now, t)
        return p

    def _graphics(self, now, t):
        """Info-panel data. The 10 s demo lap is reported as a 1:32 lap, ticking at that pace."""
        g = Graphics()
        elapsed = now - self._start
        lap_index = int(elapsed // 10)
        g.npos = t / 10
        g.total_lap_count = 6 + lap_index
        g.current_lap_time_ms = int(t / 10 * DEMO_LAP_MS)
        g.best_laptime_ms = 91_842
        g.last_laptime_ms = 91_842 + (lap_index * 137) % 900
        g.delta_time_ms = int(-420 * math.sin(t / 10 * math.pi) + 60)
        g.predicted_lap_time_ms = g.best_laptime_ms + g.delta_time_ms
        g.is_valid_lap = lap_index % 5 != 3
        g.session_state.time_left_ms = max(0, int(25 * 60_000 - elapsed * DEMO_LAP_MS / 10))
        g.current_pos, g.total_drivers = 3, 16
        g.gap_ahead, g.gap_behind = 1.2 + 0.3 * math.sin(elapsed / 7), -(0.8 + 0.2 * math.cos(elapsed / 5))

        g.max_fuel = 55.0
        g.fuel_liter_per_lap = g.fuel_per_lap = 2.45
        g.fuel_liter_current_quantity = 42.0 - (elapsed / 10 % 15) * 2.45
        g.laps_possible_with_fuel = g.fuel_liter_current_quantity / 2.45

        e = g.electronics
        e.tc_level, e.abs_level, e.engine_map_level, e.brake_bias = 3, 2, 1, 0.565

        for w, tyre in enumerate(g.tyres):
            inner, middle, outer = self._temps[w]
            # Graphics faces are car-relative: left wheels have outer on the left.
            tyre.temperature_left, tyre.temperature_right = (outer, inner) if LEFT[w] else (inner, outer)
            tyre.temperature_center = middle
            tyre.temperature_c = self._bulk[w]
            # The game's model: pressure follows bulk temperature from the 40 °C garage reference.
            tyre.pressure = DEMO_COLD_PSI[w] + PSI_PER_C * (self._bulk[w] - GARAGE_C)
            tyre.normalized_pressure = normalised(tyre.pressure, DEMO_WINDOW_PSI, 3.0)
            tyre.normalized_temperature_center = normalised(middle, DEMO_WINDOW_C, 30.0)
            tyre.normalized_temperature_core = normalised(self._bulk[w], DEMO_WINDOW_C, 20.0)
            name = b"Demo Slick"
            tyre.compound_front = tyre.compound_rear = name
        return g

    def _update_tyres(self, dt, gas, brake, corner):
        """Each surface band chases a target set by load; the inner band runs hotter (camber)."""
        speed_heat = self._speed / 280 * 12
        for w in range(4):
            load = speed_heat
            load += brake * 40 if FRONT[w] else gas * 4
            load += corner * 35 if not LEFT[w] else 0  # left-hander loads the right-side tyres
            base = 66 + load
            targets = (base + 9, base + 2, base - 7 + (corner * 12 if not LEFT[w] else 0))
            rate = 0.6 if load > speed_heat else 0.15  # heats up faster than it cools
            for band in range(3):
                self._temps[w][band] += (targets[band] - self._temps[w][band]) * min(1.0, rate * dt)
            # The carcass lags the surface and runs cooler.
            surface = sum(self._temps[w]) / 3
            self._bulk[w] += (surface - 12 - self._bulk[w]) * min(1.0, 0.08 * dt)
