"""User settings: persisted in QSettings and edited live from the settings window."""

from dataclasses import dataclass, fields

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QColorDialog, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QGroupBox,
                               QHBoxLayout, QPushButton, QSpinBox, QVBoxLayout, QWidget)


TRACE_MAX_SECONDS = 30


@dataclass
class Config:
    trace_seconds: float = 8.0  # time window shown in the input trace; longer = slower scroll
    # RPM lights, in % of max RPM. Each light takes the colour of the zone its own RPM % falls in.
    rpm_start: int = 80  # first light comes on
    rpm_zone2: int = 86  # colour 2 from here
    rpm_zone3: int = 92  # colour 3 from here
    rpm_flash: int = 97  # every light flashes (shift now)
    color1: str = "#3ddc84"
    color2: str = "#ffd23f"
    color3: str = "#ff4d4d"
    flash_color: str = "#4d7cff"

    @classmethod
    def load(cls, settings):
        config = cls()
        for f in fields(cls):
            default = getattr(config, f.name)
            setattr(config, f.name, settings.value(f"config/{f.name}", default, type=type(default)))
        return config

    def save(self, settings):
        for f in fields(self):
            settings.setValue(f"config/{f.name}", getattr(self, f.name))

    def rpm_color(self, pct):
        """Colour of a light standing for `pct` % of max RPM."""
        if pct >= self.rpm_zone3:
            return QColor(self.color3)
        if pct >= self.rpm_zone2:
            return QColor(self.color2)
        return QColor(self.color1)


class ColorButton(QPushButton):
    changed = Signal()

    def __init__(self, color):
        super().__init__()
        self.setFixedSize(44, 22)
        self.setCursor(Qt.PointingHandCursor)
        self.clicked.connect(self.pick)
        self.set_color(color)

    def set_color(self, color):
        self.color = color
        self.setStyleSheet(f"background: {color}; border: 1px solid #555; border-radius: 4px;")

    def pick(self):
        color = QColorDialog.getColor(QColor(self.color), self, "Pick a colour")
        if color.isValid():
            self.set_color(color.name())
            self.changed.emit()


class SettingsDialog(QDialog):
    """Edits the overlay's Config in place; every change is applied and saved immediately."""

    def __init__(self, overlay):
        super().__init__(None, Qt.Dialog | Qt.WindowStaysOnTopHint)
        self.setWindowTitle("Overlay settings")
        self.overlay = overlay
        self._loading = False

        self.trace_seconds = QDoubleSpinBox(minimum=2, maximum=TRACE_MAX_SECONDS, singleStep=1, decimals=0, suffix=" s")
        self.trace_seconds.setToolTip("How much time the input trace shows. Longer = slower scroll.")
        trace_box = QGroupBox("Input trace")
        trace_form = QFormLayout(trace_box)
        trace_form.addRow("Time window", self.trace_seconds)

        def pct_spin():
            return QSpinBox(minimum=1, maximum=100, suffix=" %")

        self.rpm_start, self.rpm_zone2, self.rpm_zone3, self.rpm_flash = (pct_spin() for _ in range(4))
        self.color1, self.color2, self.color3, self.flash_color = (ColorButton("#000") for _ in range(4))
        rpm_box = QGroupBox("RPM lights (% of max RPM)")
        rpm_form = QFormLayout(rpm_box)
        rpm_form.addRow("Lights start at", self.row(self.rpm_start, self.color1))
        rpm_form.addRow("Colour 2 from", self.row(self.rpm_zone2, self.color2))
        rpm_form.addRow("Colour 3 from", self.row(self.rpm_zone3, self.color3))
        rpm_form.addRow("Flash at", self.row(self.rpm_flash, self.flash_color))

        buttons = QDialogButtonBox(QDialogButtonBox.RestoreDefaults | QDialogButtonBox.Close)
        buttons.rejected.connect(self.close)
        buttons.button(QDialogButtonBox.RestoreDefaults).clicked.connect(self.restore_defaults)

        layout = QVBoxLayout(self)
        layout.addWidget(trace_box)
        layout.addWidget(rpm_box)
        layout.addWidget(buttons)

        self.load(overlay.config)
        for spin in (self.trace_seconds, self.rpm_start, self.rpm_zone2, self.rpm_zone3, self.rpm_flash):
            spin.valueChanged.connect(self.apply)
        for button in (self.color1, self.color2, self.color3, self.flash_color):
            button.changed.connect(self.apply)

    @staticmethod
    def row(spin, color_button):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(spin)
        h.addWidget(color_button)
        return w

    def load(self, c):
        self._loading = True
        self.rpm_flash.setMinimum(1)  # so the old start value can't clamp the new flash value
        self.trace_seconds.setValue(c.trace_seconds)
        for name in ("rpm_start", "rpm_zone2", "rpm_zone3", "rpm_flash"):
            getattr(self, name).setValue(getattr(c, name))
        for name in ("color1", "color2", "color3", "flash_color"):
            getattr(self, name).set_color(getattr(c, name))
        self.rpm_flash.setMinimum(c.rpm_start + 1)
        self._loading = False

    def apply(self):
        if self._loading:
            return
        # The lights spread from "start" to "flash", so flash must stay above start.
        self.rpm_flash.setMinimum(min(100, self.rpm_start.value() + 1))
        c = self.overlay.config
        c.trace_seconds = self.trace_seconds.value()
        for name in ("rpm_start", "rpm_zone2", "rpm_zone3", "rpm_flash"):
            setattr(c, name, getattr(self, name).value())
        for name in ("color1", "color2", "color3", "flash_color"):
            setattr(c, name, getattr(self, name).color)
        c.save(self.overlay.settings)
        self.overlay.update()

    def restore_defaults(self):
        self.load(Config())
        self.apply()
