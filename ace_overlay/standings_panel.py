"""Standings panel: a third pinnable window with the running order, worked out by standings.Standings.

The game publishes no names, cars or classes for other drivers, so rows are "Car N" (the car's slot in
the entry list); the player's row shows the player's name.
"""

import re
import time

from PySide6.QtCore import QPoint, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter

from .overlay import DIM, TEXT, TRACK, OverlayWindow, PinButton, font, icon_stopwatch, lap_time
from .panel import clock
from .standings import Standings, TrackMap, visible_rows

PAD = 10
HEADER_H, COLS_H = 24, 14  # session line, column titles
ROW_H, ROW_GAP, GROUP_GAP = 22, 2, 8  # GROUP_GAP separates the leaders from the rows around the player
POS_X, POS_W = PAD, 26
NAME_X, NAME_W = POS_X + POS_W + 8, 112
GAP_X, GAP_W = NAME_X + NAME_W, 54
BEST_X, BEST_W = GAP_X + GAP_W + 6, 70
LAST_X, LAST_W = BEST_X + BEST_W + 6, 70
ROW_W = LAST_X + LAST_W + 6 - PAD
BADGE_X, BADGE_W = PAD + ROW_W + 4, 22  # fastest-lap / pit badge, outside the row like the reference
PANEL_W = BADGE_X + BADGE_W + PAD
MESSAGE_ROWS = 3  # body height while there's nothing to list
SAVE_EVERY_S = 120  # how often a refined racing line is written back to the settings

PLAYER_BG = QColor(201, 168, 64, 150)
ROW_BG = QColor(255, 255, 255, 14)
POS_BG = QColor(0, 0, 0, 100)
PURPLE = QColor("#c77dff")
PURPLE_BG = QColor(123, 44, 191, 110)


def body_height(rows, split):
    return rows * (ROW_H + ROW_GAP) - ROW_GAP + (GROUP_GAP if split else 0)


def panel_height(rows, split=False):
    return PAD + HEADER_H + COLS_H + body_height(rows, split) + PAD


def gap_text(entry, is_race):
    """'–' for the leader, '3L' when lapped, '4.5' / '1:04.5' behind in a race, '+0.512' off the
    fastest lap otherwise, blank while unknown."""
    if entry.position == 1:
        return "–"
    if entry.laps_down:
        return f"{entry.laps_down}L"
    if entry.gap is None:
        return ""
    if not is_race:
        return f"+{entry.gap:.3f}"
    minutes, seconds = divmod(entry.gap, 60)
    return f"{int(minutes)}:{seconds:04.1f}" if minutes else f"{seconds:.1f}"


def lap(seconds):
    return lap_time(round(seconds * 1000)) if seconds else "–"


def line_key(track_key):
    return "tracks/" + re.sub(r"[^A-Za-z0-9]+", "_", " ".join(track_key)).strip("_") + "/line"


class StandingsPanel(OverlayWindow):
    BUTTONS = (PinButton,)

    def __init__(self, source, settings, config):
        super().__init__(settings, "standings/pos", QPoint(380, 240), PANEL_W, panel_height(MESSAGE_ROWS))
        self.source = source
        self.config = config
        self.standings = Standings(getattr(source, "time_scale", 1.0))
        self.graphics = None
        self.rows = []
        self.shown = []  # row indices on screen
        self.last_save = time.monotonic()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(50)  # 20 Hz: line crossings are interpolated between updates

    def tick(self):
        self.source.read()
        g = self.graphics = self.source.graphics
        now = time.monotonic()
        if self.standings.update(g, getattr(self.source, "static", None), now):
            self.load_line()
        track = self.standings.track
        if track.ready and track.dirty and now - self.last_save > SAVE_EVERY_S:
            self.save_line()
            self.last_save = now
        self.rows = self.standings.entries(g.last_laptime_ms, g.best_laptime_ms) if g is not None else []
        player = next((i for i, e in enumerate(self.rows) if e.car.is_player), None)
        self.shown = visible_rows(len(self.rows), player, self.config.standings_rows)
        split = any(b != a + 1 for a, b in zip(self.shown, self.shown[1:]))
        height = panel_height(max(len(self.shown), MESSAGE_ROWS), split)
        if height != self.height():
            self.setFixedSize(PANEL_W, height)
        self.update()

    # --- the learned racing line is kept per track, so it's ready from the first lap next time ----

    def load_line(self):
        track = TrackMap.loads(self.settings.value(line_key(self.standings.track_key), "", type=str))
        if track.ready:
            self.standings.track = track

    def save_line(self):
        self.settings.setValue(line_key(self.standings.track_key), self.standings.track.dumps())
        self.standings.track.dirty = False

    def hideEvent(self, event):
        super().hideEvent(event)
        if self.standings.track.ready and self.standings.track.dirty:
            self.save_line()

    # --- painting ------------------------------------------------------------

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        self.paint_background(p)
        g = self.graphics
        if g is None:
            self.message(p, "Waiting for Assetto Corsa EVO…")
            return
        self.draw_header(p, g)
        track = self.standings.track
        if not track.ready:
            self.message(p, "Learning the track: drive one lap", track.coverage)
            return
        if not self.rows:
            self.message(p, "No cars on track yet")
            return
        p.setFont(font(7, QFont.Bold))
        p.setPen(DIM)
        y = PAD + HEADER_H
        for x, w, title in ((GAP_X, GAP_W, "GAP"), (BEST_X, BEST_W, "FASTEST"), (LAST_X, LAST_W, "LAST")):
            p.drawText(QRectF(x, y, w - 4, COLS_H - 2), Qt.AlignRight | Qt.AlignVCenter, title)
        y += COLS_H
        for k, i in enumerate(self.shown):
            if k and i != self.shown[k - 1] + 1:
                y += GROUP_GAP
            self.draw_row(p, self.rows[i], y)
            y += ROW_H + ROW_GAP

    def message(self, p, line, progress=None):
        top = PAD + HEADER_H + COLS_H
        rect = QRectF(PAD, top, PANEL_W - 2 * PAD, body_height(MESSAGE_ROWS, False))
        p.setPen(DIM)
        p.setFont(font(9))
        p.drawText(rect.adjusted(0, 0, 0, -12 if progress is not None else 0), Qt.AlignCenter, line)
        if progress is not None:
            bar = QRectF(PANEL_W / 2 - 80, rect.center().y() + 8, 160, 4)
            p.setPen(Qt.NoPen)
            p.setBrush(TRACK)
            p.drawRoundedRect(bar, 2, 2)
            p.setBrush(TEXT)
            p.drawRoundedRect(QRectF(bar.x(), bar.y(), bar.width() * progress, bar.height()), 2, 2)

    def draw_header(self, p, g):
        session = g.session_state
        name = self.standings.session[1].upper() if self.standings.session else ""
        if session.total_lap > 0:
            detail = f"LAP {min(g.total_lap_count + 1, session.total_lap)}/{session.total_lap}"
        elif session.time_left_ms > 0:
            detail = f"{clock(session.time_left_ms)} LEFT"
        else:
            detail = ""
        rect = QRectF(PAD + 2, PAD, PANEL_W - 2 * PAD - 4, HEADER_H - 6)
        p.setPen(TEXT)
        p.setFont(font(10, QFont.Bold, tabular=True))
        p.drawText(rect, Qt.AlignLeft | Qt.AlignVCenter, "   ".join(s for s in (name, detail) if s))
        p.setPen(DIM)
        p.setFont(font(9))
        cars = len(self.rows) or g.active_cars
        p.drawText(rect, Qt.AlignRight | Qt.AlignVCenter, f"{cars} CARS" if cars else "")

    def draw_row(self, p, e, y):
        car = e.car
        p.setPen(Qt.NoPen)
        p.setBrush(PLAYER_BG if car.is_player else ROW_BG)
        p.drawRoundedRect(QRectF(PAD, y, ROW_W, ROW_H), 4, 4)
        p.setBrush(POS_BG)
        p.drawRoundedRect(QRectF(POS_X + 2, y + 3, POS_W - 4, ROW_H - 6), 3, 3)

        mid = Qt.AlignVCenter
        p.setPen(TEXT)
        p.setFont(font(9, QFont.Bold, tabular=True))
        p.drawText(QRectF(POS_X, y, POS_W, ROW_H), Qt.AlignHCenter | mid, str(e.position))
        p.setFont(font(9.5))
        name = (self.standings.player_name or "You") if car.is_player else f"Car {car.number}"
        p.drawText(QRectF(NAME_X, y, NAME_W, ROW_H), Qt.AlignLeft | mid,
                   p.fontMetrics().elidedText(name, Qt.ElideRight, NAME_W - 4))

        p.setFont(font(9, tabular=True))
        p.drawText(QRectF(GAP_X, y, GAP_W - 4, ROW_H), Qt.AlignRight | mid, gap_text(e, self.standings.is_race))
        if e.session_best:
            p.setPen(Qt.NoPen)
            p.setBrush(PURPLE_BG)
            p.drawRoundedRect(QRectF(BEST_X + 2, y + 3, BEST_W - 2, ROW_H - 6), 3, 3)
        p.setPen(PURPLE if e.session_best else TEXT)
        p.drawText(QRectF(BEST_X, y, BEST_W - 4, ROW_H), Qt.AlignRight | mid, lap(e.best_lap))
        p.setPen(PURPLE if e.session_best and e.last_lap == e.best_lap else TEXT)
        p.drawText(QRectF(LAST_X, y, LAST_W - 4, ROW_H), Qt.AlignRight | mid, lap(e.last_lap))

        badge = QRectF(BADGE_X, y + 1, BADGE_W, ROW_H - 2)
        if car.in_pit:
            p.setPen(Qt.NoPen)
            p.setBrush(TEXT)
            p.drawRoundedRect(badge, 3, 3)
            p.setPen(QColor("#111"))
            p.setFont(font(7, QFont.Bold))
            p.drawText(badge, Qt.AlignCenter, "PIT")
        elif e.session_best:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#7b2cbf"))
            p.drawRoundedRect(badge, 3, 3)
            icon_stopwatch(p, QRectF(badge.center().x() - 6, badge.center().y() - 6.5, 12, 12), TEXT)
