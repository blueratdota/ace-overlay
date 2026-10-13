"""Transparent, always-on-top, click-through HUD: a compact "pill" dash."""

import time
from collections import deque
from itertools import islice

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from .config import TRACE_MAX_SECONDS, Config, SettingsDialog
from .shm import air_temp, is_driving, track_temp

THROTTLE = QColor("#3ddc84")
BRAKE = QColor("#ff4d4d")
CLUTCH = QColor("#4da3ff")
YELLOW = QColor("#ffd23f")
ORANGE = QColor("#ff8c3f")
CHARGE = QColor("#29d3e6")  # energy ring: battery charge
POWER = QColor("#ffb547")  # energy ring: engine power (cars without a battery)
OUTPUT = QColor("#b07cff")  # energy ring: battery deploying / engine torque
REGEN = QColor("#5ee6a8")  # energy ring: battery recovering energy
BG = QColor(12, 12, 16, 180)
PILL_BG = QColor(10, 10, 14, 225)
EDGE = QColor(255, 255, 255, 40)
TRACK = QColor(255, 255, 255, 28)
DOT_OFF = QColor(255, 255, 255, 60)
TEXT = QColor("#f2f2f2")
DIM = QColor(255, 255, 255, 110)

# The pill. Its rounded ends carry the TC / ABS arcs (left end = car's left wheels, right end = right
# wheels; upper quarter TC, lower quarter ABS). Inside the left end: the energy ring (battery, or power
# and torque) around the position. Then the dot shift lights along the top edge over the trace. Inside
# the right end: the pedal ring around the gear and speed. The chip hangs below the bottom edge.
PH = 100  # pill height
R = PH // 2  # end radius
CHIP_H, CHIP_OVERLAP = 24, 6  # the chip only tucks this far up into the pill
H = PH + CHIP_H - CHIP_OVERLAP + 1
ARC_R, ARC_W = R - 5, 3.5  # TC / ABS end arcs: radius (to stroke centre) and stroke
RING_R, RING_W = 37, 6  # both rings: radius (to stroke centre) and stroke
ENERGY_CX = R  # energy ring, concentric with the left end
DOT_Y, DOT_D = 9, 8  # shift-light row centre (close to the top edge) and dot diameter
TRACE_X, TRACE_Y, TRACE_W = ENERGY_CX + RING_R + 16, 20, 360  # the time window is Config.trace_seconds
TRACE_H = PH - CHIP_OVERLAP - 4 - TRACE_Y  # down to just above the chip
RING_CX, RING_CY = TRACE_X + TRACE_W + 16 + RING_R, R  # pedal ring, concentric with the right end
W = RING_CX + R
CHIP_CX = TRACE_X + TRACE_W / 2  # chip centred under the trace
POWER_FLOOR_HP, TORQUE_FLOOR_NM = 100.0, 100.0  # minimum full scale for the power / torque halves

SHIFT_LEDS = 26  # thresholds and colours come from Config
AID_HOLD_S = 0.15  # keep a TC/ABS light flashing briefly so single-step triggers are visible
SIDE_SLIP_SHARE = 0.7  # a side lights if its wheel slip is at least this share of the worst side
HIDE_DELAY_S = 2.0  # "only while driving": stay up this long after driving stops, to avoid flicker

BASE_FLAGS = Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool


def font(size, weight=QFont.DemiBold, tabular=False):
    """Bahnschrift (built into Windows 10+) for the dash look, falling back to Segoe UI. `tabular`
    gives every digit the same width, so ticking numbers don't make the text jitter."""
    f = QFont()
    f.setFamilies(["Bahnschrift", "Segoe UI"])
    f.setPointSizeF(size)
    f.setWeight(weight)
    if tabular:
        f.setFeature(QFont.Tag.fromString("tnum"), 1)
    return f


def slipping_sides(slip_ratio):
    """(left, right) - which side(s) of the car a TC/ABS intervention is working on.

    The game only reports TC/ABS as a single flag, so the side is taken from per-wheel slip:
    a side lights if its worst wheel slips at least SIDE_SLIP_SHARE as much as the worst
    wheel overall. With no slip data, both sides light.
    """
    left = max(abs(slip_ratio[0]), abs(slip_ratio[2]))  # FL, RL
    right = max(abs(slip_ratio[1]), abs(slip_ratio[3]))  # FR, RR
    worst = max(left, right)
    if worst < 1e-3:
        return True, True
    return left >= worst * SIDE_SLIP_SHARE, right >= worst * SIDE_SLIP_SHARE


def lap_time(ms):
    """1:48.978, or an en dash when there's no time yet."""
    if ms <= 0:
        return "–"
    minutes, rest = divmod(ms, 60_000)
    return f"{minutes}:{rest / 1000:06.3f}"


class SideButton(QWidget):
    """Small button stacked beside the overlay's top-right corner.

    Each one is a separate window because the locked overlay is click-through, so a
    button drawn inside the overlay couldn't be clicked.
    """

    SIZE, GAP = 24, 4
    SLOT = 0  # position in the stack, top to bottom

    def __init__(self, overlay):
        super().__init__(None, BASE_FLAGS | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setCursor(Qt.PointingHandCursor)
        self.overlay = overlay
        self.hovered = False
        overlay.locked_changed.connect(self.on_locked_changed)
        self.on_locked_changed(overlay.locked)

    def follow(self):
        """Sit just right of the overlay, or just left if that would be off-screen."""
        o = self.overlay.frameGeometry()
        x = o.right() + 1 + self.GAP
        screen = self.overlay.screen()
        if screen and x + self.SIZE > screen.availableGeometry().right():
            x = o.left() - self.GAP - self.SIZE
        self.move(x, o.top() + self.SLOT * (self.SIZE + self.GAP))

    def on_locked_changed(self, locked):
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked()

    def enterEvent(self, _event):
        self.hovered = True
        self.update()

    def leaveEvent(self, _event):
        self.hovered = False
        self.update()

    def paintEvent(self, _event):
        locked = self.overlay.locked
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        # Fade out while pinned so it doesn't distract when driving; full strength on hover.
        p.setOpacity(1.0 if self.hovered or not locked else 0.45)
        p.setPen(QPen(YELLOW, 1.5) if not locked else Qt.NoPen)
        p.setBrush(BG)
        p.drawRoundedRect(QRectF(0.75, 0.75, self.SIZE - 1.5, self.SIZE - 1.5), 6, 6)
        p.translate(self.SIZE / 2, self.SIZE / 2)
        self.draw_icon(p, TEXT if locked else YELLOW)


class PinButton(SideButton):
    SLOT = 0

    def on_locked_changed(self, locked):
        self.setToolTip("Unpin to move the overlay" if locked else "Pin the overlay in place")
        self.update()

    def clicked(self):
        self.overlay.set_locked(not self.overlay.locked)

    def draw_icon(self, p, color):
        # Upright when pinned, tilted when free to move.
        if not self.overlay.locked:
            p.rotate(40)
        p.setPen(QPen(color, 2, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPoint(0, 1), QPoint(0, 8))  # needle
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        p.drawRoundedRect(QRectF(-5, -2, 10, 3), 1, 1)  # collar
        p.drawRoundedRect(QRectF(-3, -8, 6, 7), 2, 2)  # head


class ConfigButton(SideButton):
    SLOT = 1

    def on_locked_changed(self, locked):
        self.setToolTip("Overlay settings")
        self.update()

    def clicked(self):
        self.overlay.open_settings()

    def draw_icon(self, p, color):
        """Gear: eight teeth around a ring."""
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        for _ in range(8):
            p.drawRoundedRect(QRectF(-1.75, -8.5, 3.5, 4), 1, 1)
            p.rotate(45)
        p.setPen(QPen(color, 3))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPoint(0, 0), 4.5, 4.5)


class OverlayWindow(QWidget):
    """A pinnable HUD window: click-through while pinned, draggable while unpinned, and its
    position is remembered under `pos_key`. Subclasses pick their side buttons with BUTTONS."""

    locked_changed = Signal(bool)
    BUTTONS = (PinButton,)

    def __init__(self, settings, pos_key, default_pos, width, height):
        super().__init__(None, BASE_FLAGS | Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedSize(width, height)
        self.settings = settings
        self.pos_key = pos_key
        self.locked = True
        self.side_buttons = tuple(button(self) for button in self.BUTTONS)
        self.move(settings.value(pos_key, default_pos))

    def set_locked(self, locked):
        """Locked = click-through. Unlocked = drag the window to reposition it."""
        if locked == self.locked:
            return
        self.locked = locked
        visible = self.isVisible()
        self.setWindowFlags(BASE_FLAGS | Qt.WindowTransparentForInput if locked else BASE_FLAGS)
        if visible:  # changing flags hides a window; don't reveal one the user has turned off
            self.show()
        if locked:
            self.settings.setValue(self.pos_key, self.pos())
        self.locked_changed.emit(locked)

    def showEvent(self, _event):
        for button in self.side_buttons:
            button.follow()
            button.show()
            button.raise_()

    def hideEvent(self, _event):
        for button in self.side_buttons:
            button.hide()

    def moveEvent(self, _event):
        for button in self.side_buttons:
            button.follow()

    def mousePressEvent(self, event):
        if not self.locked and event.button() == Qt.LeftButton:
            self.windowHandle().startSystemMove()

    def paint_background(self, p, rect=None, radius=8, fill=BG, edge=None):
        """Translucent card (the whole window unless `rect` is given), plus a dashed yellow outline
        while unpinned."""
        rect = rect or QRectF(0, 0, self.width(), self.height())
        p.setPen(QPen(edge, 1) if edge else Qt.NoPen)
        p.setBrush(fill)
        p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
        if not self.locked:
            p.setPen(QPen(YELLOW, 2, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(rect.adjusted(1, 1, -1, -1), radius - 1, radius - 1)


class InputsOverlay(OverlayWindow):
    config_changed = Signal()  # emitted by the settings window after every change
    BUTTONS = (PinButton, ConfigButton)

    def __init__(self, source, settings):
        super().__init__(settings, "pos", QPoint(60, 60), W, H)
        self.source = source
        self.config = Config.load(settings)
        self.config_changed.connect(self.update)
        self.settings_dialog = None
        self.frame = self.graphics = None
        self.last_driving = float("-inf")  # last time is_driving() was true
        self.engine_car, self.peak_hp, self.peak_torque = None, 0.0, 0.0  # see track_engine()
        self.trace = deque()  # (time, gas, brake, clutch, tc_working, abs_working) for every tick
        self.aid_trace_until = {"tc": 0.0, "abs": 0.0}  # car-wide, for the trace colouring
        # (aid, side) -> time that end arc stops flashing; side 0 = left, 1 = right
        self.aid_until = {(aid, side): 0.0 for aid in ("tc", "abs") for side in (0, 1)}
        self.blink = 0

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(16)

    # --- behaviour -------------------------------------------------------

    def open_settings(self):
        if self.settings_dialog is None:
            self.settings_dialog = SettingsDialog(self)
            self.settings_dialog.adjustSize()
            o = self.frameGeometry()
            self.settings_dialog.move(o.left(), o.bottom() + 12)
        self.settings_dialog.show()
        self.settings_dialog.raise_()
        self.settings_dialog.activateWindow()

    def tick(self):
        f = self.frame = self.source.read()
        self.graphics = self.source.graphics
        if self.graphics is not None:
            self.track_engine(self.graphics)
        now = time.monotonic()
        if is_driving(self.graphics):
            self.last_driving = now
        self.update_visibility(now)
        if f is not None:
            for aid, active in (("tc", f.tcInAction), ("abs", f.absInAction)):
                if active:
                    self.aid_trace_until[aid] = now + AID_HOLD_S
                    for side, lit in enumerate(slipping_sides(f.slipRatio)):
                        if lit:
                            self.aid_until[aid, side] = now + AID_HOLD_S
            # Keep every reading for the longest window the settings allow, with whether TC / ABS were
            # working (held like the lights, so a flickering flag gives a solid stretch of colour).
            self.trace.append((now, f.gas, f.brake, f.clutch,
                               now < self.aid_trace_until["tc"], now < self.aid_trace_until["abs"]))
            while self.trace[0][0] < now - TRACE_MAX_SECONDS:
                self.trace.popleft()
        self.blink = (self.blink + 1) % 16
        self.update()

    def update_visibility(self, now):
        """With "only while driving" on, the HUD hides in menus, the garage, replays and pause. A short
        delay stops it flickering on transitions, and it always shows while unpinned for positioning."""
        want = (not self.config.hide_until_driving or not self.locked
                or now - self.last_driving < HIDE_DELAY_S)
        if want != self.isVisible():
            self.setVisible(want)

    # --- drawing ---------------------------------------------------------

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        self.paint_background(p, QRectF(0, 0, W, PH), R, PILL_BG, EDGE)

        f = self.frame
        if f is None:
            p.setPen(DIM)
            p.setFont(font(11, QFont.Normal))
            p.drawText(QRectF(0, 0, W, PH), Qt.AlignCenter, "Waiting for Assetto Corsa EVO…")
            return

        self.draw_end_arcs(p)
        self.draw_ring(p, f)
        self.draw_dots(p, f)
        self.draw_trace(p)
        self.draw_energy(p, f)
        self.draw_chip(p, f)

    def draw_end_arcs(self, p):
        """TC / ABS as lines along the pill's rounded ends: the left end for the car's left wheels, the
        right end for its right wheels; upper quarter TC (yellow), lower quarter ABS (orange)."""
        now = time.monotonic()
        flash_on = (self.blink // 4) % 2 == 0  # ~7.5 Hz at 60 fps
        gap = 6  # degrees between the TC and ABS quarter on each end
        # (side, end centre x, TC quarter start, ABS quarter start); Qt angles go CCW from 3 o'clock.
        for side, cx, tc_start, abs_start in ((0, R, 90, 180), (1, W - R, 0, 270)):
            box = QRectF(cx - ARC_R, R - ARC_R, 2 * ARC_R, 2 * ARC_R)
            for aid, start, color in (("tc", tc_start, YELLOW), ("abs", abs_start, ORANGE)):
                on = now < self.aid_until[aid, side] and flash_on
                p.setPen(QPen(color if on else TRACK, ARC_W + (1.5 if on else 0), Qt.SolidLine, Qt.FlatCap))
                p.drawArc(box, int((start + gap / 2) * 16), int((90 - gap) * 16))

    @staticmethod
    def draw_tracks(p, cx, tracks):
        """A ring of arc tracks centred on (cx, R): each track is (start, full span, value 0..1, colour)
        in Qt angles (degrees, CCW from 3 o'clock), filled from its start."""
        box = QRectF(cx - RING_R, R - RING_R, 2 * RING_R, 2 * RING_R)
        for start, span, value, color in tracks:
            p.setPen(QPen(TRACK, RING_W, Qt.SolidLine, Qt.FlatCap))
            p.drawArc(box, int(start * 16), int(span * 16))
            value = max(0.0, min(1.0, value))
            if value > 0.005:
                p.setPen(QPen(color, RING_W, Qt.SolidLine, Qt.FlatCap))
                p.drawArc(box, int(start * 16), int(span * value * 16))

    def draw_ring(self, p, f):
        """Gear and speed in a ring: throttle fills 3/4 of it clockwise over the top and right
        (green), brake fills the west quarter downwards (red). Both start at the top-left."""
        gap = 4  # degrees between the two tracks
        self.draw_tracks(p, RING_CX, ((135 - gap / 2, -(270 - gap), f.gas, THROTTLE),
                                      (135 + gap / 2, 90 - gap, f.brake, BRAKE)))
        gear = "R" if f.gear == 0 else "N" if f.gear == 1 else str(f.gear - 1)
        cx, cy, w = RING_CX, RING_CY, 56
        p.setPen(TEXT)
        p.setFont(font(19, QFont.Bold))
        p.drawText(QRectF(cx - w / 2, cy - 28, w, 30), Qt.AlignHCenter | Qt.AlignBottom, gear)
        p.setFont(font(12, QFont.Bold))
        p.drawText(QRectF(cx - w / 2, cy + 2, w, 16), Qt.AlignCenter, f"{f.speedKmh:.0f}")
        p.setPen(DIM)
        p.setFont(font(6))
        p.drawText(QRectF(cx - w / 2, cy + 17, w, 9), Qt.AlignCenter, "KPH")

    def draw_dots(self, p, f):
        """Shift lights as dots, spread evenly from rpm_start to rpm_flash; each takes the colour of
        its own RPM %."""
        c = self.config
        pct = 100 * f.rpms / f.currentMaxRpm if f.currentMaxRpm > 0 else 0.0
        flash = pct >= c.rpm_flash
        x0, x1 = TRACE_X + DOT_D / 2, TRACE_X + TRACE_W - DOT_D / 2
        step = (x1 - x0) / (SHIFT_LEDS - 1)
        p.setPen(Qt.NoPen)
        for i in range(SHIFT_LEDS):
            led_pct = c.rpm_start + (c.rpm_flash - c.rpm_start) * i / SHIFT_LEDS
            if flash:
                color = QColor(c.flash_color) if self.blink < 8 else DOT_OFF
            elif pct >= led_pct:
                color = c.rpm_color(led_pct)
            else:
                color = DOT_OFF
            p.setBrush(color)
            p.drawEllipse(QPointF(x0 + i * step, DOT_Y), DOT_D / 2, DOT_D / 2)

    def draw_trace(self, p):
        """Each reading is placed by its real age, so the right edge is always the live input and
        changing the time window rescales the whole trace at once."""
        x0, y0, w, h = TRACE_X, TRACE_Y, TRACE_W, TRACE_H
        p.setPen(Qt.NoPen)
        p.setBrush(TRACK)
        p.drawRoundedRect(QRectF(x0, y0, w, h), 6, 6)
        if len(self.trace) < 2:
            return
        now = self.trace[-1][0]
        px_per_s = w / self.config.trace_seconds
        cutoff = now - self.config.trace_seconds
        # Start one reading before the window so the line runs right up to the left edge.
        first = next((i for i, s in enumerate(self.trace) if s[0] >= cutoff), len(self.trace) - 1)
        visible = list(islice(self.trace, max(0, first - 1), None))
        p.save()
        p.setClipRect(QRectF(x0, y0, w, h))
        p.setBrush(Qt.NoBrush)
        # (value index, colour, width, flag index, colour while that aid works): the brake line turns
        # orange while ABS works and the throttle line yellow while TC cuts, like the lights.
        for idx, color, width, flag, aid_color in ((3, CLUTCH, 1.5, None, None), (2, BRAKE, 2, 5, ORANGE),
                                                   (1, THROTTLE, 2, 4, YELLOW)):
            points = [(x0 + w - (now - s[0]) * px_per_s, y0 + h - 3 - (h - 6) * max(0.0, min(1.0, s[idx])),
                       flag is not None and s[flag]) for s in visible]
            # Split the line into runs of one colour; a segment takes the state of its newer point.
            run, run_lit = QPainterPath(QPointF(*points[0][:2])), points[1][2]
            for (x, y, lit) in points[1:]:
                if lit != run_lit:
                    p.setPen(QPen(aid_color if run_lit else color, width + (0.5 if run_lit else 0)))
                    p.drawPath(run)
                    run, run_lit = QPainterPath(run.currentPosition()), lit
                run.lineTo(x, y)
            p.setPen(QPen(aid_color if run_lit else color, width + (0.5 if run_lit else 0)))
            p.drawPath(run)
        p.restore()

    def track_engine(self, g):
        """Peak power and torque for the current car, the full scale of the energy ring's halves.
        Reset when the car changes."""
        car = bytes(g.car_model)
        if car != self.engine_car:
            self.engine_car, self.peak_hp, self.peak_torque = car, 0.0, 0.0
        self.peak_hp = max(self.peak_hp, g.current_bhp)
        self.peak_torque = max(self.peak_torque, g.current_torque)

    def energy(self, f, g):
        """(label, top value, top colour, bottom value, bottom colour) for the energy ring: battery
        charge and live usage on hybrids, otherwise power and torque against this car's session peak.

        Verified live on the Ferrari SF25: kers_charge_perc is the charge (0..1) and kers_current_perc the
        live flow, -1..+1 (positive deploying on throttle, negative recovering under braking). The
        physics kersCharge / kersInput / kersCurrentKJ stay 0 in EVO.
        """
        if g is None:
            return "PWR · TRQ", 0.0, POWER, 0.0, OUTPUT
        if g.has_kers:
            flow = g.kers_current_perc
            return "BATT", g.kers_charge_perc, CHARGE, abs(flow), OUTPUT if flow >= 0 else REGEN
        return ("PWR · TRQ", g.current_bhp / max(self.peak_hp, POWER_FLOOR_HP), POWER,
                g.current_torque / max(self.peak_torque, TORQUE_FLOOR_NM), OUTPUT)

    def draw_energy(self, p, f):
        """Ring in the left end around the position: the top half fills clockwise from the west with
        battery charge (or power), the bottom half the other way with live battery flow (purple
        deploying, green recovering) or torque."""
        g = self.graphics
        label, top, top_color, bottom, bottom_color = self.energy(f, g)
        gap = 4
        self.draw_tracks(p, ENERGY_CX, ((180 - gap / 2, -(180 - gap), top, top_color),
                                        (180 + gap / 2, 180 - gap, bottom, bottom_color)))
        cx, cy, w = ENERGY_CX, R, 56
        pos = g.current_pos if g is not None else 0
        p.setPen(ORANGE if pos else DIM)
        p.setFont(font(15, QFont.Bold))
        p.drawText(QRectF(cx - w / 2, cy - 21, w, 22), Qt.AlignHCenter | Qt.AlignBottom, f"P{pos}" if pos else "P–")
        p.setPen(DIM)
        if pos and g.total_drivers:
            p.setFont(font(6.5))
            p.drawText(QRectF(cx - w / 2, cy + 2, w, 10), Qt.AlignCenter, f"OF {g.total_drivers}")
        p.setFont(font(5.5))
        p.drawText(QRectF(cx - w / 2, cy + 13, w, 9), Qt.AlignCenter, label)

    def draw_chip(self, p, f):
        """Track temperature · air temperature · current lap, in a chip hanging below the pill."""
        g = self.graphics
        air, road = air_temp(f, g), track_temp(f)
        # (icon, text, widest expected text): each item reserves its template's width, so the chip
        # keeps one size while the lap time ticks.
        items = [(icon_road, f"{road:.0f} °C" if road is not None else "–", "88 °C"),
                 (icon_wind, f"{air:.0f} °C" if air is not None else "–", "88 °C"),
                 (icon_stopwatch, lap_time(g.current_lap_time_ms) if g is not None else "–", "8:88.888")]
        p.setFont(font(10, tabular=True))
        metrics = p.fontMetrics()
        icon, gap, pad, spacing = 12, 5, 12, 16
        widths = [icon + gap + max(metrics.horizontalAdvance(text), metrics.horizontalAdvance(template))
                  for _, text, template in items]
        chip_w = sum(widths) + spacing * (len(items) - 1) + 2 * pad
        chip = QRectF(CHIP_CX - chip_w / 2, PH - CHIP_OVERLAP, chip_w, CHIP_H)
        p.setPen(QPen(EDGE, 1))
        p.setBrush(QColor(28, 28, 34, 240))
        p.drawRoundedRect(chip, CHIP_H / 2, CHIP_H / 2)
        x = chip.x() + pad
        for (draw_icon, text, _), width in zip(items, widths):
            draw_icon(p, QRectF(x, chip.center().y() - icon / 2, icon, icon))
            p.setPen(TEXT)
            p.drawText(QRectF(x + icon + gap, chip.y(), width, CHIP_H), Qt.AlignLeft | Qt.AlignVCenter, text)
            x += width + spacing


# --- chip icons (12 px line drawings) --------------------------------------------------------------

def icon_road(p, r):
    """A road narrowing into the distance, with a dashed centre line."""
    p.setPen(QPen(DIM, 1.4))
    p.drawLine(QPointF(r.left() + 1, r.bottom()), QPointF(r.center().x() - 2, r.top()))
    p.drawLine(QPointF(r.right() - 1, r.bottom()), QPointF(r.center().x() + 2, r.top()))
    p.setPen(QPen(DIM, 1.4, Qt.DashLine))
    p.drawLine(QPointF(r.center().x(), r.bottom()), QPointF(r.center().x(), r.top() + 1))


def icon_wind(p, r):
    """Three gusts with curled ends."""
    p.setPen(QPen(DIM, 1.4, Qt.SolidLine, Qt.RoundCap))
    p.setBrush(Qt.NoBrush)
    for dy, length in ((2.5, 0.75), (6, 1.0), (9.5, 0.6)):
        y = r.top() + dy
        end = r.left() + r.width() * length
        p.drawLine(QPointF(r.left(), y), QPointF(end - 2, y))
        p.drawArc(QRectF(end - 4, y - 2.5, 3, 2.5), -90 * 16, 270 * 16)


def icon_stopwatch(p, r):
    """Watch face with a crown and a hand."""
    p.setPen(QPen(DIM, 1.4, Qt.SolidLine, Qt.RoundCap))
    p.setBrush(Qt.NoBrush)
    face = QRectF(r.left() + 1, r.top() + 2.5, r.width() - 2, r.height() - 2.5)
    p.drawEllipse(face)
    p.drawLine(QPointF(face.center().x(), r.top()), QPointF(face.center().x(), face.top()))
    p.drawLine(face.center(), QPointF(face.center().x() + 2, face.center().y() - 2.5))
