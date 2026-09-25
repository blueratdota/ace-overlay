"""Regenerate the README images in docs/images from the demo telemetry.

    .venv\\Scripts\\python tools\\screenshots.py

Needs Pillow for the animated GIF (pip install -e .[dev]). A simulated clock drives the demo so
every still lands on the exact moment it shows (ABS on turn-in, TC on exit, shift flash).
"""

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["QT_SCALE_FACTOR"] = "2"  # so the settings-window grab is 2x like the other stills

from PIL import Image  # noqa: E402
from PySide6.QtCore import QPoint, QPointF, QSettings  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter, QRadialGradient, QLinearGradient  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

import ace_overlay.demo as demo_module  # noqa: E402
import ace_overlay.overlay as overlay_module  # noqa: E402
from ace_overlay.config import Config  # noqa: E402
from ace_overlay.demo import DemoSource  # noqa: E402
from ace_overlay.overlay import InputsOverlay, SideButton  # noqa: E402

OUT = ROOT / "docs" / "images"
TICK = 1 / 60
MARGIN = 28
GIF_FPS = 20  # GIF delays are whole centiseconds; 20 fps = exactly 50 ms


class Clock:
    """Stand-in for the `time` module so the demo and overlay run on simulated time."""

    def __init__(self):
        self.t = 1000.0

    def monotonic(self):
        return self.t


def backdrop(p, w, h):
    """Dark, softly lit background so the overlay's translucency reads like it does over a game."""
    grad = QLinearGradient(0, 0, 0, h)
    grad.setColorAt(0, QColor("#1c2431"))
    grad.setColorAt(1, QColor("#0b0f16"))
    p.fillRect(0, 0, w, h, grad)
    for cx, cy, r, color in ((0.18, 0.2, 0.55, "#2b6f7a"), (0.85, 0.9, 0.5, "#7a4a2b")):
        glow = QRadialGradient(QPointF(w * cx, h * cy), w * r)
        c = QColor(color)
        c.setAlpha(90)
        glow.setColorAt(0, c)
        c.setAlpha(0)
        glow.setColorAt(1, c)
        p.fillRect(0, 0, w, h, glow)


def render(overlay, scale, buttons=False):
    """The overlay (plus optionally its pin/gear buttons) composited on the backdrop."""
    extra = SideButton.GAP + SideButton.SIZE if buttons else 0
    w, h = overlay.width() + extra + 2 * MARGIN, overlay.height() + 2 * MARGIN
    image = QImage(int(w * scale), int(h * scale), QImage.Format_ARGB32_Premultiplied)
    image.setDevicePixelRatio(scale)
    p = QPainter(image)
    p.setRenderHint(QPainter.Antialiasing)
    backdrop(p, w, h)
    p.translate(MARGIN, MARGIN)
    overlay.render(p, QPoint(0, 0), renderFlags=QWidget.RenderFlag.DrawChildren)
    if buttons:
        for button in overlay.side_buttons:
            p.save()
            p.translate(overlay.width() + SideButton.GAP, button.SLOT * (SideButton.SIZE + SideButton.GAP))
            button.render(p, QPoint(0, 0), renderFlags=QWidget.RenderFlag.DrawChildren)
            p.restore()
    p.end()
    return image


def to_pil(image):
    image = image.convertToFormat(QImage.Format_RGBA8888)
    return Image.frombuffer("RGBA", (image.width(), image.height()), bytes(image.constBits()), "raw", "RGBA", 0, 1)


def save_png(image, name):
    to_pil(image).convert("RGB").save(OUT / name, optimize=True)
    print("wrote", name)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    app = QApplication(sys.argv)  # noqa: F841
    clock = Clock()
    demo_module.time = overlay_module.time = clock

    settings = QSettings(str(Path(tempfile.mkdtemp()) / "screenshots.ini"), QSettings.IniFormat)
    overlay = InputsOverlay(DemoSource(), settings)
    overlay.timer.stop()

    def step():
        clock.t += TICK
        overlay.tick()

    def lap_time():
        return (clock.t - 1000.0) % 10.0

    def run_until(predicate, limit=20.0):
        end = clock.t + limit
        while clock.t < end:
            step()
            if predicate(overlay.frame):
                return
        raise RuntimeError("moment not reached")

    for _ in range(int(20 / TICK)):  # warm tyres and fill the trace
        step()

    # --- animated lap ---------------------------------------------------
    frames = []
    for i in range(int(10 / TICK)):  # exactly one lap, so the GIF loops seamlessly
        step()
        if i % (60 // GIF_FPS) == 0:
            frames.append(to_pil(render(overlay, 1)).convert("RGB"))
    # One shared palette and no dithering: unchanged pixels stay identical frame to frame,
    # which is what lets GIF compression drop them. The palette is built from a spread of frames
    # plus a strip of every exact UI colour, so brief saturated colours (flash, TC/ABS) survive.
    samples = frames[::10]
    fw, fh = frames[0].size
    sheet = Image.new("RGB", (fw, fh * (len(samples) + 1)))
    for k, frame in enumerate(samples):
        sheet.paste(frame, (0, fh * k))
    ui = [overlay_module.THROTTLE, overlay_module.BRAKE, overlay_module.CLUTCH, overlay_module.YELLOW,
          overlay_module.ORANGE, overlay_module.TEXT, QColor(Config().flash_color),
          *(color for _, color in overlay_module.TYRE_STOPS)]
    block = fw // len(ui)
    for k, color in enumerate(ui):
        sheet.paste(color.name(), (k * block, fh * len(samples), (k + 1) * block, fh * (len(samples) + 1)))
    palette = sheet.quantize(colors=256, method=Image.Quantize.MEDIANCUT)
    frames = [f.quantize(palette=palette, dither=Image.Dither.NONE) for f in frames]
    frames[0].save(OUT / "overlay-demo.gif", save_all=True, append_images=frames[1:],
                   duration=round(1000 / GIF_FPS), loop=0, optimize=True)
    print("wrote overlay-demo.gif", f"({(OUT / 'overlay-demo.gif').stat().st_size / 1e6:.1f} MB)")

    # --- stills (2x for sharpness) ---------------------------------------
    def still(name, **kw):
        overlay.blink = 0  # flashing lights in their "on" phase
        save_png(render(overlay, 2, **kw), name)

    run_until(lambda f: f.rpms >= 0.97 * f.currentMaxRpm)
    still("shift-lights.png")

    # Wait until only the left light is on (the right side's hold from straight-line braking has expired).
    run_until(lambda f: overlay.aid_until["abs", 0] > clock.t >= overlay.aid_until["abs", 1])
    still("abs-trail-braking.png")

    run_until(lambda f: f.tcInAction and 8.2 < lap_time() < 8.6)
    still("tc-exit.png")

    run_until(lambda f: 4.5 < lap_time() < 4.6)
    overlay.set_locked(False)
    overlay.hide()
    still("move-mode.png", buttons=True)
    overlay.set_locked(True)
    overlay.hide()

    # Custom RPM colours + the settings window.
    overlay.config = Config(rpm_start=60, rpm_zone2=72, rpm_zone3=84, rpm_flash=95,
                            color1="#00e5ff", color2="#b266ff", color3="#ff2d95", flash_color="#ffffff")
    run_until(lambda f: 0.86 * f.currentMaxRpm < f.rpms < 0.9 * f.currentMaxRpm)
    still("custom-rpm-colours.png")
    overlay.open_settings()
    dialog = overlay.settings_dialog
    save_png(dialog.grab().toImage(), "settings.png")
    dialog.close()


if __name__ == "__main__":
    main()
