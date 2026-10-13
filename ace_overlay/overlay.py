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
BG = QColor(12, 12, 16, 180)
PILL_BG = QColor(10, 10, 14, 225)
EDGE = QColor(255, 255, 255, 40)
TRACK = QColor(255, 255, 255, 28)
DOT_OFF = QColor(255, 255, 255, 60)
TEXT = QColor("#f2f2f2")
DIM = QColor(255, 255, 255, 110)

# The pill: half-circle ends (TC left, ABS right), then left to right inside it:
# gear ring | dot shift lights over KPH/RPM and the trace | position. The chip hangs off the bottom edge.
PH = 112  # pill height
R = PH // 2  # end radius
CHIP_H = 26
H = PH + CHIP_H // 2 + 2
RING_CX, RING_CY, RING_R, RING_W = R + 52, R, 42, 7  # gear ring centre, radius (to stroke centre), stroke
CX0 = RING_CX + RING_R + 18  # start of the middle section
DOT_Y, DOT_D = 20, 9  # shift-light row centre and dot diameter
READ_W = 128  # KPH / RPM block
TRACE_X, TRACE_Y, TRACE_W, TRACE_H = CX0 + READ_W + 12, 36, 220, 52  # the time window is Config.trace_seconds
POS_X, POS_W = TRACE_X + TRACE_W + 12, 80
W = POS_X + POS_W + 4 + R
CHIP_CX = (CX0 + TRACE_X + TRACE_W) / 2  # chip centred under KPH/RPM + trace

SHIFT_LEDS = 15  # thresholds and colours come from Config
AID_HOLD_S = 0.15  # keep a TC/ABS light flashing briefly so single-step triggers are visible
HIDE_DELAY_S = 2.0  # "only while driving": stay up this long after driving stops, to avoid flicker

BASE_FLAGS = Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool


def font(size, weight=QFont.DemiBold):
    """Bahnschrift (built into Windows 10+) for the dash look, falling back to Segoe UI."""
    f = QFont()
    f.setFamilies(["Bahnschrift", "Segoe UI"])
    f.setPointSizeF(size)
    f.setWeight(weight)
    return f


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
        self.trace = deque()  # (time, gas, brake, clutch, tc_working, abs_working) for every tick
        self.aid_until = {"tc": 0.0, "abs": 0.0}  # time each light stops flashing
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
        now = time.monotonic()
        if is_driving(self.graphics):
            self.last_driving = now
        self.update_visibility(now)
        if f is not None:
            for aid, active in (("tc", f.tcInAction), ("abs", f.absInAction)):
                if active:
                    self.aid_until[aid] = now + AID_HOLD_S
            # Keep every reading for the longest window the settings allow, with whether TC / ABS were
            # working (held like the lights, so a flickering flag gives a solid stretch of colour).
            self.trace.append((now, f.gas, f.brake, f.clutch, now < self.aid_until["tc"], now < self.aid_until["abs"]))
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

        self.draw_caps(p)
        self.draw_ring(p, f)
        self.draw_dots(p, f)
        self.draw_readouts(p, f)
        self.draw_trace(p)
        self.draw_position(p)
        self.draw_chip(p, f)

    def draw_caps(self, p):
        """The pill's half-circle ends are the TC (left) and ABS (right) lights."""
        now = time.monotonic()
        flash_on = (self.blink // 4) % 2 == 0  # ~7.5 Hz at 60 fps
        inset = 4
        disc = QRectF(inset, inset, PH - 2 * inset, PH - 2 * inset)
        for aid, label, color, x0, start in (("tc", "TC", YELLOW, 0, 90), ("abs", "ABS", ORANGE, W - PH, 270)):
            on = now < self.aid_until[aid] and flash_on
            half = QPainterPath()
            half.moveTo(x0 + R, R)
            half.arcTo(disc.translated(x0, 0), start, 180)
            half.closeSubpath()
            p.setPen(Qt.NoPen)
            p.setBrush(color if on else TRACK)
            p.drawPath(half)
            # Label centred in the half that's inside the pill.
            text_x = x0 + inset if aid == "tc" else x0 + R
            p.setPen(QColor("#111") if on else DIM)
            p.setFont(font(9, QFont.Bold))
            p.drawText(QRectF(text_x, 0, R - inset, PH), Qt.AlignCenter, label)

    def draw_ring(self, p, f):
        """Gear in a ring: throttle fills 3/4 of it clockwise over the top (green), brake fills the
        bottom quarter the other way (red). Both start at the bottom-left."""
        box = QRectF(RING_CX - RING_R, RING_CY - RING_R, 2 * RING_R, 2 * RING_R)
        gap = 4  # degrees between the two tracks
        throttle = (225 - gap / 2, -(270 - gap))  # (start, full span), Qt angles: CCW from 3 o'clock
        brake = (225 + gap / 2, 90 - gap)
        for (start, span), value, color in ((throttle, f.gas, THROTTLE), (brake, f.brake, BRAKE)):
            p.setPen(QPen(TRACK, RING_W, Qt.SolidLine, Qt.FlatCap))
            p.drawArc(box, int(start * 16), int(span * 16))
            value = max(0.0, min(1.0, value))
            if value > 0.005:
                p.setPen(QPen(color, RING_W, Qt.SolidLine, Qt.FlatCap))
                p.drawArc(box, int(start * 16), int(span * value * 16))
        gear = "R" if f.gear == 0 else "N" if f.gear == 1 else str(f.gear - 1)
        p.setPen(TEXT)
        p.setFont(font(30, QFont.Bold))
        p.drawText(box, Qt.AlignCenter, gear)

    def draw_dots(self, p, f):
        """Shift lights as dots, spread evenly from rpm_start to rpm_flash; each takes the colour of
        its own RPM %."""
        c = self.config
        pct = 100 * f.rpms / f.currentMaxRpm if f.currentMaxRpm > 0 else 0.0
        flash = pct >= c.rpm_flash
        x0, x1 = CX0 + DOT_D / 2, TRACE_X + TRACE_W - DOT_D / 2
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

    def draw_readouts(self, p, f):
        half = READ_W / 2
        for i, (label, value) in enumerate((("KPH", f"{f.speedKmh:.0f}"), ("RPM", f"{f.rpms}"))):
            x = CX0 + i * half
            p.setPen(DIM)
            p.setFont(font(8))
            p.drawText(QRectF(x, 36, half, 14), Qt.AlignLeft | Qt.AlignVCenter, label)
            p.setPen(TEXT)
            p.setFont(font(19, QFont.Bold))
            p.drawText(QRectF(x, 48, half + 8, 34), Qt.AlignLeft | Qt.AlignVCenter, value)

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

    def draw_position(self, p):
        g = self.graphics
        pos = g.current_pos if g is not None else 0
        p.setPen(ORANGE if pos else DIM)
        p.setFont(font(24, QFont.Bold))
        p.drawText(QRectF(POS_X, 26, POS_W, 40), Qt.AlignRight | Qt.AlignVCenter, f"P{pos}" if pos else "P–")
        if pos and g.total_drivers:
            p.setPen(DIM)
            p.setFont(font(8))
            p.drawText(QRectF(POS_X, 64, POS_W, 14), Qt.AlignRight | Qt.AlignVCenter, f"OF {g.total_drivers}")

    def draw_chip(self, p, f):
        """Track temperature · air temperature · current lap, in a chip over the pill's bottom edge."""
        g = self.graphics
        air, road = air_temp(f, g), track_temp(f)
        items = [(icon_road, f"{road:.0f} °C" if road is not None else "–"),
                 (icon_wind, f"{air:.0f} °C" if air is not None else "–"),
                 (icon_stopwatch, lap_time(g.current_lap_time_ms) if g is not None else "–")]
        p.setFont(font(10))
        metrics = p.fontMetrics()
        icon, gap, pad, spacing = 12, 5, 12, 16
        widths = [icon + gap + metrics.horizontalAdvance(text) for _, text in items]
        chip_w = sum(widths) + spacing * (len(items) - 1) + 2 * pad
        chip = QRectF(CHIP_CX - chip_w / 2, PH - CHIP_H / 2, chip_w, CHIP_H)
        p.setPen(QPen(EDGE, 1))
        p.setBrush(QColor(28, 28, 34, 240))
        p.drawRoundedRect(chip, CHIP_H / 2, CHIP_H / 2)
        x = chip.x() + pad
        for (draw_icon, text), width in zip(items, widths):
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
