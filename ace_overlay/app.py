import argparse
import signal
import sys
import time
import traceback
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)  # running as the packaged .exe
APP_DIR = Path(sys.executable).parent if FROZEN else None


def dump(source):
    """Print the fields the overlay uses, to check them against the in-game HUD."""
    while True:
        f = source.read()
        if f is None:
            print("waiting for AC EVO shared memory...", end="\r", flush=True)
        else:
            tyres = " ".join(f"{name}={f.tyreTempI[w]:3.0f}/{f.tyreTempM[w]:3.0f}/{f.tyreTempO[w]:3.0f}"
                             for w, name in enumerate(("FL", "FR", "RL", "RR")))
            print(f"pkt={f.packetId:<9} gas={f.gas:4.2f} brk={f.brake:4.2f} clu={f.clutch:4.2f} "
                  f"gear={f.gear} rpm={f.rpms:<5}/{f.currentMaxRpm:<5} kmh={f.speedKmh:6.1f} "
                  f"tc={f.tcInAction} abs={f.absInAction} tyres(I/M/O) {tyres}   ", end="\r", flush=True)
        time.sleep(0.1)


def attach_console():
    """The packaged .exe is a windowed app with no console; borrow the launching one (or open one) for --dump."""
    import ctypes
    kernel32 = ctypes.windll.kernel32
    if not kernel32.AttachConsole(-1):  # ATTACH_PARENT_PROCESS
        kernel32.AllocConsole()
    sys.stdout = open("CONOUT$", "w")
    sys.stderr = sys.stdout


def log_crashes():
    """The packaged .exe has nowhere to print errors, so write them next to it."""
    def hook(kind, value, tb):
        with open(APP_DIR / "error.log", "a", encoding="utf-8") as log:
            log.write(time.strftime("\n--- %Y-%m-%d %H:%M:%S ---\n"))
            log.write("".join(traceback.format_exception(kind, value, tb)))
    sys.excepthook = hook


def app_icon(size):
    """Three pedal bars (clutch, brake, throttle) on a dark tile. Used for the tray and the .exe."""
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QColor, QImage, QPainter

    image = QImage(size, size, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    p = QPainter(image)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    s = size / 32
    p.setBrush(QColor("#16161c"))
    p.drawRoundedRect(QRectF(0, 0, size, size), 7 * s, 7 * s)
    for i, (color, height) in enumerate((("#4da3ff", 0.35), ("#ff4d4d", 0.6), ("#3ddc84", 0.9))):
        bar_h = 22 * s * height
        p.setBrush(QColor(color))
        p.drawRoundedRect(QRectF((5 + i * 8) * s, 27 * s - bar_h, 6 * s, bar_h), 1.5 * s, 1.5 * s)
    p.end()
    return image


def main():
    parser = argparse.ArgumentParser(prog="ace-overlay", description="Inputs overlay for Assetto Corsa EVO")
    parser.add_argument("--demo", action="store_true", help="use fake telemetry instead of the game")
    parser.add_argument("--dump", action="store_true", help="print raw telemetry to the console, no overlay")
    args = parser.parse_args()

    if FROZEN:
        log_crashes()
        if args.dump:
            attach_console()

    if args.demo:
        from .demo import DemoSource
        source = DemoSource()
    else:
        from .shm import LiveSource
        source = LiveSource()

    if args.dump:
        try:
            dump(source)
        except KeyboardInterrupt:
            print()
        return

    from PySide6.QtCore import QSettings
    from PySide6.QtGui import QAction, QIcon, QPixmap
    from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

    from .overlay import InputsOverlay

    signal.signal(signal.SIGINT, signal.SIG_DFL)  # let Ctrl+C in the console quit
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    # The packaged .exe is portable: settings live beside it, not in the registry.
    settings = (QSettings(str(APP_DIR / "settings.ini"), QSettings.IniFormat) if FROZEN
                else QSettings("ace-overlay", "ace-overlay"))
    overlay = InputsOverlay(source, settings)
    overlay.show()

    menu = QMenu()
    move_action = QAction("Move overlay", menu, checkable=True)
    move_action.toggled.connect(lambda on: overlay.set_locked(not on))
    overlay.locked_changed.connect(lambda locked: move_action.setChecked(not locked))
    menu.addAction(move_action)
    menu.addAction("Settings…", overlay.open_settings)
    menu.addSeparator()
    menu.addAction("Quit", app.quit)

    tray = QSystemTrayIcon(QIcon(QPixmap.fromImage(app_icon(64))))
    tray.setToolTip("AC EVO overlay")
    tray.setContextMenu(menu)
    tray.show()

    sys.exit(app.exec())
