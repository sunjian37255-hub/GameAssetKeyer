# SPDX-License-Identifier: MPL-2.0
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QImageReader, QPalette, QPixmap
from PySide6.QtWidgets import QLabel, QPushButton

ASSETS = Path(__file__).with_name("assets") / "wuxing_local"
MATERIAL_FILES = ("panel_build.png", "button_primary.png", "button_secondary.png")


def label(text, role="", wrap=False):
    result = QLabel(text)
    result.setObjectName(role)
    result.setWordWrap(wrap)
    return result


def button(text, callback=None, primary=False):
    result = QPushButton(text)
    if primary:
        result.setObjectName("primary")
    if callback:
        result.clicked.connect(callback)
    return result


def thumbnail(path, size=QSize(192, 116)):
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    dimensions = reader.size()
    if dimensions.isValid():
        reader.setScaledSize(dimensions.scaled(size, Qt.AspectRatioMode.KeepAspectRatio))
    return QIcon(QPixmap.fromImage(reader.read()))


def to_qimage(image):
    if image is None:
        return QImage()
    rgba = image.convert("RGBA")
    return QImage(rgba.tobytes(), rgba.width, rgba.height, rgba.width * 4, QImage.Format.Format_RGBA8888).copy()


def apply_theme(app, material=True):
    palette = QPalette()
    for role, color in [(QPalette.ColorRole.Window, "#14181f"), (QPalette.ColorRole.WindowText, "#dfe5ee"),
                        (QPalette.ColorRole.Base, "#141a23"), (QPalette.ColorRole.Text, "#dfe5ee"),
                        (QPalette.ColorRole.Button, "#293240"), (QPalette.ColorRole.ButtonText, "#dfe5ee"),
                        (QPalette.ColorRole.Highlight, "#365f55"), (QPalette.ColorRole.HighlightedText, "#ffffff")]:
        palette.setColor(role, QColor(color))
    app.setPalette(palette)
    theme = Path(__file__).with_name("theme.qss").read_text(encoding="utf-8")
    if material and all((ASSETS / name).is_file() for name in MATERIAL_FILES):
        theme += "\n" + Path(__file__).with_name("material.qss").read_text(encoding="utf-8").replace("@ASSETS@", ASSETS.as_posix())
    app.setStyleSheet(theme)
