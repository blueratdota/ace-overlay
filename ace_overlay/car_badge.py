"""Match telemetry model names to emblems from the local game."""

import re
from functools import lru_cache

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainterPath, QPen
from .evo_badges import find_package, load_badges

ALIASES = {"chevy": "chevrolet", "mercedes": "mercedesbenz", "mercedesamg": "mercedesbenz", "vw": "volkswagen"}


@lru_cache(maxsize=1)
def game_badges():
    package = find_package()
    return load_badges(package) if package is not None else {}


@lru_cache(maxsize=128)
def manufacturer_badge(model):
    words = re.findall(r"[a-z0-9]+", model.lower())
    if words[:1] in (["ks"], ["ace"]):
        words = words[1:]
    for length in range(min(len(words), 2), 0, -1):
        prefix = "".join(words[:length])
        badge = game_badges().get(ALIASES.get(prefix, prefix))
        if badge is not None:
            return badge
    return None


def draw_car_badge(p, rect, car):
    badge = manufacturer_badge(car)
    if badge is not None:
        p.drawImage(rect, badge)
    else:
        icon_car(p, rect)


def icon_car(p, r):
    """Draw a front-view car emblem in a square of any size."""
    p.save()
    p.translate(r.topLeft())
    p.scale(r.width() / 16, r.height() / 16)
    p.setPen(QPen(QColor("#f2f2f2"), 1.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(QRectF(1, 7, 14, 6), 2, 2)
    roof = QPainterPath(QPointF(3, 7))
    roof.lineTo(5, 3)
    roof.lineTo(11, 3)
    roof.lineTo(13, 7)
    p.drawPath(roof)
    for x in (3, 13):
        p.drawLine(QPointF(x, 13), QPointF(x, 15))
    p.drawLine(QPointF(3.5, 9.5), QPointF(5.5, 9.5))
    p.drawLine(QPointF(10.5, 9.5), QPointF(12.5, 9.5))
    p.restore()
