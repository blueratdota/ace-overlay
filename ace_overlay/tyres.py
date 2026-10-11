"""Tyre pressure recommendations that account for temperature.

What the game does (measured live on the Golf 8 R's SuperCar tyres, 2026-09-29):

- Pressure is a linear function of the tyre's bulk temperature (TyreState.temperature_c, the same value
  as physics tyreCoreTemperature): psi = garage psi + 0.096 * (temperature - 40 °C). That fit had R² =
  1.000 on all four tyres, and 40 °C is the garage reference: a tyre set to 26.0 reads 26.0 at 40 °C.
- The game judges pressure and temperature against a per-compound ideal window, and publishes the
  verdict as a normalised value: exactly 1.0 anywhere inside the window, and moving away linearly
  outside it (pressure: 1/3 per psi; surface temperature: 1/30 per °C; core: 1/20 per °C).

So a recommendation has to project each tyre to its ideal operating temperature before judging its
pressure. A cold tyre at 26 psi isn't "low" if it'll be at 30 psi once warm. The windows are learned
from the normalised values as they come in, so they work for any compound.
"""

PSI_PER_C = 0.096  # pressure rise per °C of bulk tyre temperature
GARAGE_C = 40.0  # temperature at which the garage (cold) pressure applies
EPS = 0.002  # normalised values this close to 1.0 count as inside the window


class Window:
    """One compound's ideal window for one quantity, learned from (value, normalised) readings.

    Outside the window, normalised = 1 ± distance / scale. A reading on either side pins that edge
    exactly once the scale is known. The scale comes from two readings on the same side, falling
    back to `default_scale` until then. Inside readings only prove the window reaches at least that far.
    """

    def __init__(self, default_scale):
        self.default_scale = default_scale
        self.low = self.high = None
        self.inside_min = self.inside_max = None
        self._last = {}  # side -> (value, normalised), to measure the scale
        self.scale = {"low": None, "high": None}

    def observe(self, value, norm):
        if norm <= 0:
            return
        if abs(norm - 1.0) <= EPS:
            self.inside_min = value if self.inside_min is None else min(self.inside_min, value)
            self.inside_max = value if self.inside_max is None else max(self.inside_max, value)
            return
        side = "low" if norm < 1 else "high"
        prev = self._last.get(side)
        if prev and abs(value - prev[0]) > 0.05 and abs(norm - prev[1]) > 1e-4:
            self.scale[side] = abs((value - prev[0]) / (norm - prev[1]))
        self._last[side] = (value, norm)
        scale = self.scale[side] or self.default_scale
        if side == "low":
            self.low = value + (1.0 - norm) * scale
        else:
            self.high = value - (norm - 1.0) * scale

    def target(self):
        """Middle of the window, or None until both edges are known."""
        if self.low is None or self.high is None:
            return None
        return (self.low + self.high) / 2


class Compound:
    def __init__(self):
        self.pressure = Window(default_scale=3.0)
        self.surface = Window(default_scale=30.0)
        self.core = Window(default_scale=20.0)

    def target_temperature(self):
        """Bulk temperature to judge pressure at: the middle of the core window, else of the surface window."""
        return self.core.target() or self.surface.target()


class Advice:
    def __init__(self, hot_psi, target_psi, adjust, garage_psi):
        self.hot_psi = hot_psi  # this tyre's pressure once at the target temperature
        self.target_psi = target_psi  # the middle of the pressure window
        self.adjust = adjust  # psi to add (+) or remove (−); the same at the garage and on track
        self.garage_psi = garage_psi  # recommended garage (40 °C) pressure


class TyreAdvisor:
    """Learns each compound's windows from live readings and advises a pressure per tyre.

    Upper edges are only seen when a tyre runs over-pressure or overheats, so learned edges are
    saved in the settings and survive restarts.
    """

    QUANTITIES = ("pressure", "surface", "core")

    def __init__(self, settings=None):
        self.settings = settings
        self.compounds = {}
        self._saved = {}

    def load(self):
        for key in self.settings.allKeys() if self.settings else ():
            parts = key.split("/")
            if len(parts) == 4 and parts[0] == "tyres" and parts[2] in self.QUANTITIES:
                window = getattr(self.compound(parts[1]), parts[2])
                value = float(self.settings.value(key))
                if parts[3] in ("low", "high"):
                    setattr(window, parts[3], value)
                elif parts[3] in ("scale_low", "scale_high"):
                    window.scale[parts[3][6:]] = value

    def save(self):
        """Write learned edges that changed (a no-op without settings)."""
        if not self.settings:
            return
        for name, c in self.compounds.items():
            for q in self.QUANTITIES:
                window = getattr(c, q)
                values = {"low": window.low, "high": window.high,
                          "scale_low": window.scale["low"], "scale_high": window.scale["high"]}
                for field, value in values.items():
                    key = f"tyres/{name}/{q}/{field}"
                    if value is not None and self._saved.get(key) != round(value, 3):
                        self.settings.setValue(key, round(value, 3))
                        self._saved[key] = round(value, 3)

    def compound(self, name):
        return self.compounds.setdefault(name, Compound())

    def observe(self, graphics):
        for w, tyre in enumerate(graphics.tyres):
            c = self.compound(compound_name(tyre, w))
            c.pressure.observe(tyre.pressure, tyre.normalized_pressure)
            c.surface.observe(tyre.temperature_center, tyre.normalized_temperature_center)
            c.core.observe(tyre.temperature_c, tyre.normalized_temperature_core)

    def advise(self, tyre, wheel):
        """Advice for one tyre, or None until the windows for its compound are known."""
        c = self.compound(compound_name(tyre, wheel))
        target_c, target_psi = c.target_temperature(), c.pressure.target()
        if target_c is None or target_psi is None or tyre.temperature_c <= 0:
            return None
        hot = tyre.pressure + PSI_PER_C * (target_c - tyre.temperature_c)
        garage_now = tyre.pressure - PSI_PER_C * (tyre.temperature_c - GARAGE_C)
        adjust = target_psi - hot
        return Advice(hot, target_psi, adjust, garage_now + adjust)


def compound_name(tyre, wheel):
    raw = tyre.compound_front if wheel < 2 else tyre.compound_rear
    # "/" would split the settings key.
    return (raw.decode(errors="ignore") or "?").replace("/", "-")
