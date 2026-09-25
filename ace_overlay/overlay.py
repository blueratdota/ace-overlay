"""Transparent, always-on-top, click-through inputs overlay."""

import time
from collections import deque
from itertools import islice

from PySide6.QtCore import QPoint, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from .config import TRACE_MAX_SECONDS, Config, SettingsDialog

THROTTLE = QColor("#3ddc84")
BRAKE = QColor("#ff4d4d")
CLUTCH = QColor("#4da3ff")
YELLOW = QColor("#ffd23f")
ORANGE = QColor("#ff8c3f")
BG = QColor(12, 12, 16, 180)
TRACK = QColor(255, 255, 255, 28)
TEXT = QColor("#f2f2f2")
DIM = QColor(255, 255, 255, 110)

PAD = 10
SHIFT_H = 14  # full-width shift-light strip along the top
CT = PAD + SHIFT_H + 8  # top of the content row below it
CH = 96  # content row height
H = CT + CH + PAD

# Content row, left to right: TC/ABS (left side) | pedals | trace | gear/speed/rpm | tyres | TC/ABS (right side)
AID_W = 34
PEDAL_X, PEDAL_W, PEDAL_GAP = PAD + AID_W + PAD, 26, 4
TRACE_X = PEDAL_X + 3 * PEDAL_W + 2 * PEDAL_GAP + PAD
TRACE_W = 240  # the time window it shows is Config.trace_seconds
DASH_X = TRACE_X + TRACE_W + PAD
DASH_W = 138
TYRE_X = DASH_X + DASH_W + PAD
TYRE_W = 120
AID_RIGHT_X = TYRE_X + TYRE_W + PAD
W = AID_RIGHT_X + AID_W + PAD

SHIFT_LEDS = 15  # thresholds and colours come from Config
AID_HOLD_S = 0.15  # keep a TC/ABS light flashing briefly so single-step triggers are visible
SIDE_SLIP_SHARE = 0.7  # a side lights if its wheel slip is at least this share of the worst side

# Tyre surface temperature (°C) -> colour. Generic racing-slick window; tune per compound.
TYRE_STOPS = [(50, QColor("#3b6cff")), (75, THROTTLE), (95, THROTTLE), (105, YELLOW), (115, BRAKE)]

BASE_FLAGS = Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool


def tyre_color(temp):
    if temp <= TYRE_STOPS[0][0]:
        return TYRE_STOPS[0][1]
    for (t0, c0), (t1, c1) in zip(TYRE_STOPS, TYRE_STOPS[1:]):
        if temp <= t1:
            k = (temp - t0) / (t1 - t0)
            return QColor(int(c0.red() + (c1.red() - c0.red()) * k),
                          int(c0.green() + (c1.green() - c0.green()) * k),
                          int(c0.blue() + (c1.blue() - c0.blue()) * k))
    return TYRE_STOPS[-1][1]


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


class InputsOverlay(QWidget):
    locked_changed = Signal(bool)

    def __init__(self, source, settings):
        super().__init__(None, BASE_FLAGS | Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedSize(W, H)

        self.source = source
        self.settings = settings
        self.config = Config.load(settings)
        self.settings_dialog = None
        self.locked = True
        self.frame = None
        self.trace = deque()  # (time, gas, brake, clutch) for every tick
        self.blink = 0
        # (aid, side) -> time the light stops flashing; side 0 = left, 1 = right
        self.aid_until = {(aid, side): 0.0 for aid in ("tc", "abs") for side in (0, 1)}

        self.side_buttons = (PinButton(self), ConfigButton(self))
        self.move(settings.value("pos", QPoint(60, 60)))

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(16)

    # --- behaviour -------------------------------------------------------

    def set_locked(self, locked):
        """Locked = click-through. Unlocked = drag the overlay to reposition it."""
        if locked == self.locked:
            return
        self.locked = locked
        flags = BASE_FLAGS | Qt.WindowTransparentForInput if locked else BASE_FLAGS
        self.setWindowFlags(flags)
        self.show()
        if locked:
            self.settings.setValue("pos", self.pos())
        self.locked_changed.emit(locked)

    def open_settings(self):
        if self.settings_dialog is None:
            self.settings_dialog = SettingsDialog(self)
            self.settings_dialog.adjustSize()
            o = self.frameGeometry()
            self.settings_dialog.move(o.left(), o.bottom() + 12)
        self.settings_dialog.show()
        self.settings_dialog.raise_()
        self.settings_dialog.activateWindow()

    def showEvent(self, _event):
        for button in self.side_buttons:
            button.follow()
            button.show()
            button.raise_()

    def moveEvent(self, _event):
        for button in self.side_buttons:
            button.follow()

    def mousePressEvent(self, event):
        if not self.locked and event.button() == Qt.LeftButton:
            self.windowHandle().startSystemMove()

    def tick(self):
        f = self.frame = self.source.read()
        if f is not None:
            now = time.monotonic()
            # Keep every reading for the longest window the settings allow.
            self.trace.append((now, f.gas, f.brake, f.clutch))
            while self.trace[0][0] < now - TRACE_MAX_SECONDS:
                self.trace.popleft()
            for aid, active in (("tc", f.tcInAction), ("abs", f.absInAction)):
                if active:
                    for side, lit in enumerate(slipping_sides(f.slipRatio)):
                        if lit:
                            self.aid_until[aid, side] = now + AID_HOLD_S
        self.blink = (self.blink + 1) % 16
        self.update()

    # --- drawing ---------------------------------------------------------

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(BG)
        p.drawRoundedRect(QRectF(0, 0, W, H), 8, 8)

        if not self.locked:
            p.setPen(QPen(YELLOW, 2, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(QRectF(1, 1, W - 2, H - 2), 8, 8)

        f = self.frame
        if f is None:
            p.setPen(DIM)
            p.setFont(QFont("Segoe UI", 11))
            p.drawText(self.rect(), Qt.AlignCenter, "Waiting for Assetto Corsa EVO…")
            return

        self.draw_shift_lights(p, f)
        self.draw_pedals(p, f)
        self.draw_trace(p)
        self.draw_gear_speed(p, f)
        self.draw_aids(p)
        self.draw_tyres(p, f)

    def draw_shift_lights(self, p, f):
        """Lights spread evenly from rpm_start to rpm_flash; each takes the colour of its own RPM %."""
        c = self.config
        gap = 4
        led_w = (W - 2 * PAD - (SHIFT_LEDS - 1) * gap) / SHIFT_LEDS
        pct = 100 * f.rpms / f.currentMaxRpm if f.currentMaxRpm > 0 else 0.0
        flash = pct >= c.rpm_flash
        for i in range(SHIFT_LEDS):
            led_pct = c.rpm_start + (c.rpm_flash - c.rpm_start) * i / SHIFT_LEDS
            if flash:
                color = QColor(c.flash_color) if self.blink < 8 else TRACK
            elif pct >= led_pct:
                color = c.rpm_color(led_pct)
            else:
                color = TRACK
            p.setPen(Qt.NoPen)
            p.setBrush(color)
            p.drawRoundedRect(QRectF(PAD + i * (led_w + gap), PAD, led_w, SHIFT_H), 3, 3)

    def draw_pedals(self, p, f):
        label_h = 14
        bar_h = CH - label_h
        p.setFont(QFont("Consolas", 8, QFont.Bold))
        for i, (value, color) in enumerate(((f.clutch, CLUTCH), (f.brake, BRAKE), (f.gas, THROTTLE))):
            value = max(0.0, min(1.0, value))
            x = PEDAL_X + i * (PEDAL_W + PEDAL_GAP)
            p.setPen(Qt.NoPen)
            p.setBrush(TRACK)
            p.drawRoundedRect(QRectF(x, CT, PEDAL_W, bar_h), 3, 3)
            fill = bar_h * value
            p.setBrush(color)
            p.drawRoundedRect(QRectF(x, CT + bar_h - fill, PEDAL_W, fill), 3, 3)
            p.setPen(color)
            p.drawText(QRectF(x - 2, CT + bar_h, PEDAL_W + 4, label_h), Qt.AlignCenter, f"{value * 100:.0f}%")

    def draw_trace(self, p):
        """Each reading is placed by its real age, so the right edge is always the live input and
        changing the time window rescales the whole trace at once."""
        x0, w = TRACE_X, TRACE_W
        p.setPen(Qt.NoPen)
        p.setBrush(TRACK)
        p.drawRoundedRect(QRectF(x0, CT, w, CH), 4, 4)
        if len(self.trace) < 2:
            return
        now = self.trace[-1][0]
        px_per_s = w / self.config.trace_seconds
        cutoff = now - self.config.trace_seconds
        # Start one reading before the window so the line runs right up to the left edge.
        first = next((i for i, s in enumerate(self.trace) if s[0] >= cutoff), len(self.trace) - 1)
        visible = list(islice(self.trace, max(0, first - 1), None))
        p.save()
        p.setClipRect(QRectF(x0, CT, w, CH))
        for idx, color, width in ((3, CLUTCH, 1.5), (2, BRAKE, 2), (1, THROTTLE, 2)):
            path = QPainterPath()
            for i, sample in enumerate(visible):
                x = x0 + w - (now - sample[0]) * px_per_s
                y = CT + CH - 2 - (CH - 4) * max(0.0, min(1.0, sample[idx]))
                if i:
                    path.lineTo(x, y)
                else:
                    path.moveTo(x, y)
            p.setPen(QPen(color, width))
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)
        p.restore()

    def draw_gear_speed(self, p, f):
        gear = "R" if f.gear == 0 else "N" if f.gear == 1 else str(f.gear - 1)
        p.setPen(TEXT)
        p.setFont(QFont("Segoe UI", 46, QFont.Bold))
        p.drawText(QRectF(DASH_X, CT, 62, CH), Qt.AlignCenter, gear)

        right_x, right_w = DASH_X + 64, DASH_W - 64
        p.setFont(QFont("Consolas", 22, QFont.Bold))
        p.drawText(QRectF(right_x, CT + 6, right_w, 32), Qt.AlignRight | Qt.AlignVCenter, f"{f.speedKmh:.0f}")
        p.setPen(DIM)
        p.setFont(QFont("Segoe UI", 8))
        p.drawText(QRectF(right_x, CT + 36, right_w, 14), Qt.AlignRight, "km/h")

        p.setFont(QFont("Segoe UI", 7, QFont.Bold))
        p.drawText(QRectF(right_x, CT + 60, right_w, 12), Qt.AlignRight, "RPM")
        p.setPen(TEXT)
        p.setFont(QFont("Consolas", 13, QFont.Bold))
        p.drawText(QRectF(right_x, CT + 72, right_w, 20), Qt.AlignRight | Qt.AlignVCenter, f"{f.rpms}")

    def draw_aids(self, p):
        """TC above ABS on each side of the overlay; a side flashes while that side is intervening."""
        now = time.monotonic()
        flash_on = (self.blink // 4) % 2 == 0  # ~7.5 Hz at 60 fps
        chip_h = (CH - 6) / 2
        p.setFont(QFont("Segoe UI", 9, QFont.Bold))
        for side, x in enumerate((PAD, AID_RIGHT_X)):
            for row, (aid, label, color) in enumerate((("tc", "TC", YELLOW), ("abs", "ABS", ORANGE))):
                r = QRectF(x, CT + row * (chip_h + 6), AID_W, chip_h)
                on = now < self.aid_until[aid, side] and flash_on
                p.setPen(Qt.NoPen)
                p.setBrush(color if on else TRACK)
                p.drawRoundedRect(r, 5, 5)
                p.setPen(QColor("#111") if on else DIM)
                p.drawText(r, Qt.AlignCenter, label)

    def draw_tyres(self, p, f):
        """Top-down car: each tyre split into surface bands, outer edge facing outward."""
        num_w, tyre_w, tyre_h, mid_gap = 30, 22, 42, 10
        x_left_tyre = TYRE_X + num_w + 3
        x_right_tyre = x_left_tyre + tyre_w + mid_gap
        rows = (CT, CT + CH - tyre_h)
        p.setFont(QFont("Consolas", 10, QFont.Bold))
        for wheel in range(4):  # FL, FR, RL, RR
            left_side = wheel % 2 == 0
            x = x_left_tyre if left_side else x_right_tyre
            y = rows[wheel // 2]
            inner, middle, outer = f.tyreTempI[wheel], f.tyreTempM[wheel], f.tyreTempO[wheel]
            bands = (outer, middle, inner) if left_side else (inner, middle, outer)

            clip = QPainterPath()
            clip.addRoundedRect(QRectF(x, y, tyre_w, tyre_h), 5, 5)
            p.save()
            p.setClipPath(clip)
            p.setPen(Qt.NoPen)
            for b, temp in enumerate(bands):
                p.setBrush(tyre_color(temp))
                p.drawRect(QRectF(x + b * tyre_w / 3, y, tyre_w / 3 + 0.5, tyre_h))
            p.restore()

            avg = (inner + middle + outer) / 3
            num_x = TYRE_X if left_side else x_right_tyre + tyre_w + 3
            align = (Qt.AlignRight if left_side else Qt.AlignLeft) | Qt.AlignVCenter
            p.setPen(TEXT)
            p.drawText(QRectF(num_x, y, num_w, tyre_h), align, f"{avg:.0f}°")
