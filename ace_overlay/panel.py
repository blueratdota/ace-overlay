"""Info panel: a second pinnable window with timing, fuel strategy, tyre pressures and car settings."""

import math

from PySide6.QtCore import QPoint, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter

from .overlay import BRAKE, CLUTCH, DIM, TEXT, THROTTLE, TRACK, YELLOW, OverlayWindow, PinButton

PANEL_W, PANEL_H, PAD = 300, 350, 12
PSI_PER_NORMALISED = 3.0  # psi per unit of the game's normalised pressure (see pressure_adjust)
PRESSURE_WINDOW_EPS = 0.005  # normalised pressure this close to 1.0 counts as inside the window


def lap_time(ms):
    """1:48.978, or an en dash when there's no time yet."""
    if ms <= 0:
        return "–"
    minutes, rest = divmod(ms, 60_000)
    return f"{minutes}:{rest / 1000:06.3f}"


def clock(ms):
    minutes, seconds = divmod(max(0, ms) // 1000, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02}:{seconds:02}" if hours else f"{minutes}:{seconds:02}"


def signed(value, digits):
    """+0.352 / −0.352 with a real minus sign."""
    return f"{'+' if value >= 0 else '−'}{abs(value):.{digits}f}"


def laps_to_finish(g):
    """Laps still to drive, counting what's left of the current lap, or None if unknown.

    Lap races: total laps minus completed laps. Timed sessions: finish the current lap, then keep
    lapping at the reference pace until the clock runs out, plus the lap in progress at zero.
    """
    session = g.session_state
    lap_ms = g.last_laptime_ms if g.last_laptime_ms > 0 else g.best_laptime_ms
    rest_of_lap = max(0.0, 1.0 - g.npos)
    if session.total_lap > 0:
        return max(0.0, session.total_lap - g.total_lap_count - g.npos)
    if session.time_left_ms > 0 and lap_ms > 0:
        after_this_lap = session.time_left_ms - rest_of_lap * lap_ms
        return rest_of_lap + (math.ceil(after_this_lap / lap_ms) if after_this_lap > 0 else 0)
    return None


def pressure_adjust(tyre):
    """psi to add (+) or remove (−) to bring the tyre into its compound's ideal window, 0.0 when it's
    in the window, or None if the game gives no verdict.

    The game doesn't publish a target pressure. Its normalised pressure is exactly 1.0 anywhere
    inside the ideal window, and moves away from 1.0 outside it. Measured live on the SuperCar
    compound, that's 1/3 per psi below the window (26.0 psi read 0.669 against a 27.0 psi lower
    edge); the same slope is assumed above it.
    """
    norm = tyre.normalized_pressure
    if norm <= 0:
        return None
    if abs(norm - 1.0) < PRESSURE_WINDOW_EPS:
        return 0.0
    return (1.0 - norm) * PSI_PER_NORMALISED


class InfoPanel(OverlayWindow):
    BUTTONS = (PinButton,)

    def __init__(self, source, settings, config):
        super().__init__(settings, "panel/pos", QPoint(60, 240), PANEL_W, PANEL_H)
        self.source = source
        self.config = config
        self.frame = self.graphics = None
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(100)  # everything here changes slowly; 10 Hz is plenty

    def tick(self):
        self.frame = self.source.read()
        self.graphics = self.source.graphics
        self.update()

    # --- drawing helpers ---------------------------------------------------

    @staticmethod
    def label(p, rect, text, align=Qt.AlignLeft):
        p.setPen(DIM)
        p.setFont(QFont("Segoe UI", 7, QFont.Bold))
        p.drawText(rect, align | Qt.AlignVCenter, text)

    @staticmethod
    def value(p, rect, text, size=11, color=TEXT, align=Qt.AlignLeft, mono=True):
        p.setPen(color)
        p.setFont(QFont("Consolas" if mono else "Segoe UI", size, QFont.Bold))
        p.drawText(rect, align | Qt.AlignVCenter, text)

    @staticmethod
    def separator(p, y):
        p.setPen(Qt.NoPen)
        p.setBrush(TRACK)
        p.drawRect(QRectF(PAD, y, PANEL_W - 2 * PAD, 1))

    def chip(self, p, rect, text, color, text_color=QColor("#111")):
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        p.drawRoundedRect(rect, 4, 4)
        p.setPen(text_color)
        p.setFont(QFont("Segoe UI", 7, QFont.Bold))
        p.drawText(rect, Qt.AlignCenter, text)

    # --- painting ------------------------------------------------------------

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        self.paint_background(p)
        f, g = self.frame, self.graphics
        if f is None or g is None:
            p.setPen(DIM)
            p.setFont(QFont("Segoe UI", 10))
            p.drawText(self.rect(), Qt.AlignCenter, "Waiting for Assetto Corsa EVO…")
            return
        self.draw_header(p, g, PAD)
        self.draw_timing(p, g, 46)
        self.separator(p, 124)
        self.draw_fuel(p, g, 132)
        self.separator(p, 198)
        self.draw_pressures(p, g, 206)
        self.separator(p, 280)
        self.draw_car(p, f, g, 288)

    def draw_header(self, p, g, y):
        col = (PANEL_W - 2 * PAD) / 3
        session = g.session_state
        lap = g.total_lap_count + 1
        laps = f"{lap}/{session.total_lap}" if session.total_lap > 0 else f"{lap}"
        pos = f"{g.current_pos}/{g.total_drivers}" if g.current_pos > 0 else "–"
        left = clock(session.time_left_ms) if session.time_left_ms > 0 else "–"
        for i, (name, text) in enumerate((("LAP", laps), ("POS", pos), ("LEFT", left))):
            x = PAD + i * col
            align = (Qt.AlignLeft, Qt.AlignHCenter, Qt.AlignRight)[i]
            self.label(p, QRectF(x, y, col, 10), name, align)
            self.value(p, QRectF(x, y + 8, col, 16), text, 10, align=align)
        if g.is_in_pit_lane:
            self.chip(p, QRectF(PANEL_W / 2 + 34, y + 1, 30, 14), "PIT", YELLOW)

    def draw_timing(self, p, g, y):
        on_lap = not g.is_in_pit_lane and g.best_laptime_ms > 0 and g.predicted_lap_time_ms > 0
        delta = g.delta_time_ms / 1000
        color = (THROTTLE if delta <= 0 else BRAKE) if on_lap else DIM
        self.label(p, QRectF(PAD, y, 100, 10), "DELTA TO BEST")
        self.value(p, QRectF(PAD, y + 8, 150, 28), signed(delta, 3) if on_lap else "–", 20, color)
        self.label(p, QRectF(PANEL_W - PAD - 120, y, 120, 10), "PREDICTED", Qt.AlignRight)
        self.value(p, QRectF(PANEL_W - PAD - 120, y + 8, 120, 28),
                   lap_time(g.predicted_lap_time_ms) if on_lap else "–", 12, align=Qt.AlignRight)

        y += 40
        col = (PANEL_W - 2 * PAD) / 3
        invalid = not g.is_valid_lap and not g.is_in_pit_lane
        for i, (name, ms) in enumerate((("CURRENT", g.current_lap_time_ms), ("LAST", g.last_laptime_ms),
                                        ("BEST", g.best_laptime_ms))):
            x = PAD + i * col
            align = (Qt.AlignLeft, Qt.AlignHCenter, Qt.AlignRight)[i]
            self.label(p, QRectF(x, y, col, 10), name, align)
            self.value(p, QRectF(x, y + 10, col, 18), lap_time(ms), 10, BRAKE if i == 0 and invalid else TEXT, align)
        if invalid:
            self.chip(p, QRectF(PAD + 48, y, 40, 11), "INVALID", BRAKE)

    def draw_fuel(self, p, g, y):
        fuel = g.fuel_liter_current_quantity
        per_lap = g.fuel_liter_per_lap if g.fuel_liter_per_lap > 0 else g.fuel_per_lap
        self.label(p, QRectF(PAD, y, 100, 10), "FUEL")
        col = (PANEL_W - 2 * PAD) / 3
        cells = ((f"{fuel:.1f}", "L"), (f"{per_lap:.2f}" if per_lap > 0 else "–", "L/LAP"),
                 (f"{fuel / per_lap:.1f}" if per_lap > 0 else "–", "LAPS"))
        for i, (text, unit) in enumerate(cells):
            x = PAD + i * col
            align = (Qt.AlignLeft, Qt.AlignHCenter, Qt.AlignRight)[i]
            p.setPen(TEXT)
            p.setFont(QFont("Consolas", 13, QFont.Bold))
            width = p.fontMetrics().horizontalAdvance(text)
            p.setFont(QFont("Segoe UI", 7, QFont.Bold))
            unit_w = p.fontMetrics().horizontalAdvance(unit) + 3
            start = {Qt.AlignLeft: x, Qt.AlignHCenter: x + (col - width - unit_w) / 2,
                     Qt.AlignRight: x + col - width - unit_w}[align]
            self.value(p, QRectF(start, y + 10, width + 2, 22), text, 13)
            self.label(p, QRectF(start + width + 3, y + 15, unit_w, 14), unit)

        bar = QRectF(PAD, y + 36, PANEL_W - 2 * PAD, 5)
        frac = max(0.0, min(1.0, fuel / g.max_fuel)) if g.max_fuel > 0 else 0.0
        p.setPen(Qt.NoPen)
        p.setBrush(TRACK)
        p.drawRoundedRect(bar, 2.5, 2.5)
        p.setBrush(BRAKE if per_lap > 0 and fuel / per_lap < 2 else YELLOW if frac < 0.2 else THROTTLE)
        p.drawRoundedRect(QRectF(bar.x(), bar.y(), bar.width() * frac, bar.height()), 2.5, 2.5)

        laps = laps_to_finish(g)
        if laps is not None and per_lap > 0:
            need = laps * per_lap - fuel
            self.label(p, QRectF(PAD, y + 46, 150, 14), f"TO END OF SESSION  ≈{laps:.1f} LAPS")
            text, color = ((f"ADD {need:.1f} L", BRAKE) if need > 0 else (f"SPARE {-need:.1f} L", THROTTLE))
            self.value(p, QRectF(PANEL_W - PAD - 130, y + 46, 130, 14), text, 9, color, Qt.AlignRight)

    def draw_pressures(self, p, g, y):
        self.label(p, QRectF(PAD, y, 260, 10), "TYRE PRESSURE  psi   (vs. the compound's ideal window)")
        cell_w = (PANEL_W - 2 * PAD - 16) / 2
        for w, tyre in enumerate(g.tyres):  # FL, FR, RL, RR
            x = PAD + (w % 2) * (cell_w + 16)
            cy = y + 14 + (w // 2) * 26
            adjust = pressure_adjust(tyre)
            if adjust is None:
                color, detail = TEXT, ""
            elif adjust == 0.0:
                color, detail = THROTTLE, "OK"
            elif adjust > 0:
                color, detail = CLUTCH, f"ADD ≈{adjust:.1f}"
            else:
                color, detail = BRAKE, f"REMOVE ≈{-adjust:.1f}"
            p.setPen(Qt.NoPen)
            p.setBrush(TRACK)
            p.drawRoundedRect(QRectF(x, cy, cell_w, 22), 4, 4)
            p.setBrush(color)
            p.drawRoundedRect(QRectF(x, cy, 4, 22), 2, 2)
            self.value(p, QRectF(x + 10, cy, 44, 22), f"{tyre.pressure:.1f}", 12, color)
            self.value(p, QRectF(x + 50, cy, cell_w - 56, 22), detail, 8, DIM, Qt.AlignRight)

    def draw_car(self, p, f, g, y):
        e = g.electronics
        chips = [("BB", f"{e.brake_bias * 100:.1f}" if e.brake_bias > 0 else "–"),
                 ("TC", str(e.tc_level)), ("ABS", str(e.abs_level)), ("MAP", str(e.engine_map_level))]
        chip_w = (PANEL_W - 2 * PAD - 3 * 6) / 4
        for i, (name, text) in enumerate(chips):
            r = QRectF(PAD + i * (chip_w + 6), y, chip_w, 28)
            p.setPen(Qt.NoPen)
            p.setBrush(TRACK)
            p.drawRoundedRect(r, 5, 5)
            self.label(p, QRectF(r.x(), r.y() + 2, r.width(), 10), name, Qt.AlignHCenter)
            self.value(p, QRectF(r.x(), r.y() + 11, r.width(), 16), text, 10, align=Qt.AlignHCenter)

        y += 34
        self.label(p, QRectF(PAD, y, 40, 14), "AIR")
        self.value(p, QRectF(PAD + 20, y, 40, 14), f"{f.airTemp:.0f}°", 9)
        self.label(p, QRectF(PAD + 58, y, 40, 14), "TRACK")
        self.value(p, QRectF(PAD + 90, y, 40, 14), f"{f.roadTemp:.0f}°", 9)
        if g.gap_ahead or g.gap_behind:
            self.label(p, QRectF(PANEL_W - PAD - 130, y, 30, 14), "GAP")
            self.value(p, QRectF(PANEL_W - PAD - 110, y, 110, 14),
                       f"▲{abs(g.gap_ahead):.1f}  ▼{abs(g.gap_behind):.1f}", 9, align=Qt.AlignRight)
