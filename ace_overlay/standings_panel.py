"""Pinnable leaderboard with bridge data when available and estimated standings otherwise."""

import re
import time

from PySide6.QtCore import QPoint, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter

from .car_badge import draw_car_badge
from .hud_standings import HudStandings
from .overlay import DIM, TEXT, TRACK, OverlayWindow, PinButton, font, icon_stopwatch, lap_time
from .panel import clock
from .shm import player_position, text
from .standings import Standings, TrackMap, visible_rows

PAD = 10
HEADER_H, SUMMARY_H, COLS_H = 24, 40, 18  # session line, player timing, column titles
ROW_H, ROW_GAP, GROUP_GAP = 22, 2, 8  # GROUP_GAP separates the leaders from the rows around the player
MEDIUM_ROW_H, LARGE_ROW_H = 26, 33  # Large gives the car model its own line
POS_X, POS_W = PAD, 26
NAME_X, NAME_W = POS_X + POS_W + 8, 188
CAR_LOGO_SIZE, CAR_LOGO_SLOT = 18, 24
GAP_X, GAP_W = NAME_X + NAME_W, 54
BEST_X, BEST_W = GAP_X + GAP_W + 6, 70
LAST_X, LAST_W = BEST_X + BEST_W + 6, 70
ROW_W = LAST_X + LAST_W + 6 - PAD
BADGE_X, BADGE_W = PAD + ROW_W + 4, 22  # fastest-lap / pit badge, outside the row like the reference
PANEL_W = BADGE_X + BADGE_W + PAD
LAST_COL_W = LAST_X - BEST_X
MESSAGE_ROWS = 2  # body height while there's nothing to list
SAVE_EVERY_S = 120  # how often a refined racing line is written back to the settings

PLAYER_BG = QColor(201, 168, 64, 150)
ROW_BG = QColor(255, 255, 255, 14)
POS_BG = QColor(0, 0, 0, 100)
PURPLE = QColor("#c77dff")
PURPLE_BG = QColor(123, 44, 191, 110)


def body_height(rows, split, row_height=ROW_H):
    return rows * (row_height + ROW_GAP) - ROW_GAP + (GROUP_GAP if split else 0)


def panel_height(rows, split=False, row_height=ROW_H):
    return PAD + HEADER_H + SUMMARY_H + COLS_H + body_height(rows, split, row_height) + PAD


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
        width = PANEL_W - LAST_COL_W if config.standings_layout == "small" else PANEL_W
        super().__init__(settings, "standings/pos", QPoint(380, 240), width, panel_height(MESSAGE_ROWS))
        self.source = source
        self.config = config
        self.standings = Standings(getattr(source, "time_scale", 1.0))
        self.hud = None if getattr(source, "time_scale", 1.0) != 1.0 else HudStandings()
        self.hud_rows = []
        self.graphics = None
        self.rows = []
        self.shown = []  # row indices on screen
        self.last_save = time.monotonic()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(50)  # 20 Hz: line crossings are interpolated between updates

    @property
    def small(self):
        return self.config.standings_layout == "small"

    @property
    def show_model(self):
        return self.config.standings_layout not in ("small", "medium")

    @property
    def row_height(self):
        if self.show_model:
            return LARGE_ROW_H
        return ROW_H if self.small else MEDIUM_ROW_H

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
        self.hud_rows = self.hud.read() if g is not None and self.hud is not None else []
        if self.hud_rows:
            player = next((i for i, row in enumerate(self.hud_rows) if row.is_player), None)
            count = len(self.hud_rows)
        else:
            player = next((i for i, e in enumerate(self.rows) if e.car.is_player), None)
            count = len(self.rows)
        self.shown = visible_rows(count, player, self.config.standings_rows)
        split = any(b != a + 1 for a, b in zip(self.shown, self.shown[1:]))
        height = panel_height(len(self.shown), split, self.row_height) if self.shown else panel_height(MESSAGE_ROWS)
        width = PANEL_W - LAST_COL_W if self.small else PANEL_W
        if (width, height) != (self.width(), self.height()):
            self.setFixedSize(width, height)
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
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        self.paint_background(p)
        g = self.graphics
        if g is None:
            self.message(p, "Waiting for Assetto Corsa EVO…")
            return
        self.draw_header(p, g)
        self.draw_player_summary(p, g)
        track = self.standings.track
        if not self.hud_rows and not track.ready:
            self.message(p, "Learning the track: drive one lap", track.coverage)
            return
        if not self.hud_rows and not self.rows:
            self.message(p, "No cars on track yet")
            return
        p.setFont(font(7, QFont.Bold))
        p.setPen(DIM)
        y = PAD + HEADER_H + SUMMARY_H
        p.drawText(QRectF(PAD + 2, y, NAME_X + NAME_W - PAD, COLS_H - 2),
                   Qt.AlignLeft | Qt.AlignVCenter, "GAME LEADERBOARD" if self.hud_rows else "ESTIMATED ORDER")
        for x, w, title in ((GAP_X, GAP_W, "GAP"), (BEST_X, BEST_W, "FASTEST"), (LAST_X, LAST_W, "LAST")):
            if self.small and x == LAST_X:
                break
            p.drawText(QRectF(x, y, w - 4, COLS_H - 2), Qt.AlignRight | Qt.AlignVCenter, title)
        y += COLS_H
        position_offset = 1 if self.hud_rows and self.hud_rows[0].position == 0 else 0
        for k, i in enumerate(self.shown):
            if k and i != self.shown[k - 1] + 1:
                y += GROUP_GAP
            if self.hud_rows:
                self.draw_hud_row(p, self.hud_rows[i], y, position_offset)
            else:
                self.draw_row(p, self.rows[i], y)
            y += self.row_height + ROW_GAP

    def draw_hud_row(self, p, row, y, position_offset):
        height = self.row_height
        p.setPen(Qt.NoPen)
        p.setBrush(PLAYER_BG if row.is_player else ROW_BG)
        p.drawRoundedRect(QRectF(PAD, y, self.width() - PANEL_W + ROW_W, height), 4, 4)
        p.setBrush(POS_BG)
        p.drawRoundedRect(QRectF(POS_X + 2, y + 3, POS_W - 4, height - 6), 3, 3)
        p.setPen(TEXT)
        p.setFont(font(9, QFont.Bold, tabular=True))
        p.drawText(QRectF(POS_X, y, POS_W, height), Qt.AlignCenter, str(row.position + position_offset))
        model = row.model.strip()
        if not model and row.is_player:
            model = text(self.graphics.car_model)
        self.draw_row_logo(p, model, y, height)
        labels = [(row.name or "–", y, 17 if self.show_model else height, 9, TEXT)]
        if self.show_model:
            labels.append((model, y + 17, 14, 8, DIM))
        for value, top, label_height, size, color in labels:
            p.setFont(font(size))
            p.setPen(color)
            label = p.fontMetrics().elidedText(value, Qt.ElideRight, NAME_W - CAR_LOGO_SLOT - 4)
            p.drawText(QRectF(NAME_X + CAR_LOGO_SLOT, top, NAME_W - CAR_LOGO_SLOT, label_height),
                       Qt.AlignLeft | Qt.AlignVCenter, label)
        p.setFont(font(9, tabular=True))
        p.setPen(TEXT)
        for x, width, value in ((GAP_X, GAP_W, row.gap), (BEST_X, BEST_W, row.best), (LAST_X, LAST_W, row.last)):
            if self.small and x == LAST_X:
                break
            label = p.fontMetrics().elidedText(value or "–", Qt.ElideRight, width - 4)
            p.drawText(QRectF(x, y, width - 4, height), Qt.AlignRight | Qt.AlignVCenter, label)

    @staticmethod
    def draw_row_logo(p, model, y, height):
        draw_car_badge(p, QRectF(NAME_X, y + (height - CAR_LOGO_SIZE) / 2, CAR_LOGO_SIZE, CAR_LOGO_SIZE), model)

    def message(self, p, line, progress=None):
        top = PAD + HEADER_H + SUMMARY_H + COLS_H
        rect = QRectF(PAD, top, self.width() - 2 * PAD, body_height(MESSAGE_ROWS, False))
        p.setPen(DIM)
        p.setFont(font(9))
        p.drawText(rect.adjusted(0, 0, 0, -12 if progress is not None else 0), Qt.AlignCenter, line)
        if progress is not None:
            bar = QRectF(self.width() / 2 - 80, rect.center().y() + 8, 160, 4)
            p.setPen(Qt.NoPen)
            p.setBrush(TRACK)
            p.drawRoundedRect(bar, 2, 2)
            p.setBrush(TEXT)
            p.drawRoundedRect(QRectF(bar.x(), bar.y(), bar.width() * progress, bar.height()), 2, 2)

    def draw_header(self, p, g):
        session = g.session_state
        name = self.standings.session[1].upper() if self.standings.session else ""
        detail = f"{clock(session.time_left_ms)} LEFT" if session.time_left_ms > 0 else ""
        rect = QRectF(PAD + 2, PAD, self.width() - 2 * PAD - 4, HEADER_H - 6)
        p.setPen(TEXT)
        p.setFont(font(10, QFont.Bold, tabular=True))
        p.drawText(rect, Qt.AlignLeft | Qt.AlignVCenter, name or "STANDINGS")
        p.setPen(DIM)
        p.setFont(font(9))
        p.drawText(rect, Qt.AlignRight | Qt.AlignVCenter, detail)

    def draw_player_summary(self, p, g):
        rank = player_position(g)
        position = f"{rank} / {g.total_drivers}" if rank else "–"
        total_laps = g.session_state.total_lap
        lap_number = max(1, g.total_lap_count + 1)
        current_lap = f"{min(lap_number, total_laps)} / {total_laps}" if total_laps > 0 else str(lap_number)
        values = (
            ("YOUR POSITION", position),
            ("LAP", current_lap),
            ("YOUR BEST", lap_time(g.best_laptime_ms) if g.best_laptime_ms > 0 else "–"),
            ("YOUR LAST", lap_time(g.last_laptime_ms) if g.last_laptime_ms > 0 else "–"),
        )
        y = PAD + HEADER_H
        spacing = 4
        width = (self.width() - 2 * PAD - 3 * spacing) / 4
        for i, (label, value) in enumerate(values):
            x = PAD + i * (width + spacing)
            p.setPen(Qt.NoPen)
            p.setBrush(ROW_BG)
            p.drawRoundedRect(QRectF(x, y, width, SUMMARY_H - 4), 4, 4)
            p.setFont(font(7, QFont.Bold))
            p.setPen(DIM)
            p.drawText(QRectF(x, y + 3, width, 12), Qt.AlignCenter, label)
            p.setFont(font(11, QFont.Bold, tabular=True))
            p.setPen(TEXT)
            p.drawText(QRectF(x, y + 15, width, 18), Qt.AlignCenter, value)

    def draw_row(self, p, e, y):
        car = e.car
        height = self.row_height
        p.setPen(Qt.NoPen)
        p.setBrush(PLAYER_BG if car.is_player else ROW_BG)
        p.drawRoundedRect(QRectF(PAD, y, self.width() - PANEL_W + ROW_W, height), 4, 4)
        p.setBrush(POS_BG)
        p.drawRoundedRect(QRectF(POS_X + 2, y + 3, POS_W - 4, height - 6), 3, 3)

        mid = Qt.AlignVCenter
        p.setPen(TEXT)
        p.setFont(font(9, QFont.Bold, tabular=True))
        p.drawText(QRectF(POS_X, y, POS_W, height), Qt.AlignHCenter | mid, str(e.position))
        p.setFont(font(9.5))
        name = (self.standings.player_name or "You") if car.is_player else f"Car {car.number}"
        model = text(self.graphics.car_model) if car.is_player else ""
        self.draw_row_logo(p, model, y, height)
        p.drawText(QRectF(NAME_X + CAR_LOGO_SLOT, y, NAME_W - CAR_LOGO_SLOT, height), Qt.AlignLeft | mid,
                   p.fontMetrics().elidedText(name, Qt.ElideRight, NAME_W - CAR_LOGO_SLOT - 4))

        p.setFont(font(9, tabular=True))
        p.drawText(QRectF(GAP_X, y, GAP_W - 4, height), Qt.AlignRight | mid, gap_text(e, self.standings.is_race))
        if e.session_best:
            p.setPen(Qt.NoPen)
            p.setBrush(PURPLE_BG)
            p.drawRoundedRect(QRectF(BEST_X + 2, y + 3, BEST_W - 2, height - 6), 3, 3)
        p.setPen(PURPLE if e.session_best else TEXT)
        p.drawText(QRectF(BEST_X, y, BEST_W - 4, height), Qt.AlignRight | mid, lap(e.best_lap))
        if not self.small:
            p.setPen(PURPLE if e.session_best and e.last_lap == e.best_lap else TEXT)
            p.drawText(QRectF(LAST_X, y, LAST_W - 4, height), Qt.AlignRight | mid, lap(e.last_lap))

        badge = QRectF(self.width() - PANEL_W + BADGE_X, y + 1, BADGE_W, height - 2)
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
