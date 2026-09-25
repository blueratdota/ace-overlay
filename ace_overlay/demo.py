"""Fake telemetry so the overlay can be developed without the game running."""

import math
import time

from .shm import Physics

MAX_RPM = 8000
# Top speed (km/h) at redline for each forward gear, indexed by the raw gear value (2 = 1st).
GEAR_TOP = {2: 75, 3: 115, 4: 155, 5: 195, 6: 235, 7: 275}
FRONT = (True, True, False, False)  # FL, FR, RL, RR
LEFT = (True, False, True, False)


class DemoSource:
    """Loops a 10 s 'lap': a straight, a trail-braked left-hander, then the exit."""

    def __init__(self):
        self._start = self._last = time.monotonic()
        self._speed = 90.0
        self._gear = 4
        self._shift_until = 0.0
        self._packet = 0
        # [wheel][inner, middle, outer], starting a little cold so the tyres visibly warm up.
        self._temps = [[62.0, 60.0, 58.0] for _ in range(4)]

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

        self._speed += (gas * 45 * (1 - self._speed / 290) - brake * 90 - 2) * dt
        self._speed = max(40.0, min(280.0, self._speed))

        rpm = self._speed / GEAR_TOP[self._gear] * MAX_RPM
        if rpm > MAX_RPM * 0.98 and self._gear < 7:
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
        return p

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
