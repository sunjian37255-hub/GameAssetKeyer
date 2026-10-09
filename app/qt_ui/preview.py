"""Qt-only viewport. Zoom and sampling never modify the image."""
# SPDX-License-Identifier: MPL-2.0
import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import QWidget


class Preview(QWidget):
    navigation = Signal(float, object)
    sampled = Signal(str)
    picked = Signal(object)

    def __init__(self):
        super().__init__()
        self.image = QImage()
        self.zoom = 1.0
        self.pan = QPointF()
        self.drag_start = None
        self.hover = None
        self.pick = False
        self.background = "checker"
        self.empty_text = "没有可显示的图像"
        self.setMinimumSize(130, 160)
        self.setMouseTracking(True)

    def set_image(self, path, empty_text="没有可显示的图像"):
        self.image = QImage(path) if isinstance(path, QImage) else QImage(str(path)) if path else QImage()
        self.empty_text = empty_text
        self.hover = None
        self.update()

    def image_rect(self):
        if self.image.isNull():
            return QRectF()
        scale = min(max(1, self.width() - 32) / self.image.width(),
                    max(1, self.height() - 32) / self.image.height()) * self.zoom
        width, height = self.image.width() * scale, self.image.height() * scale
        return QRectF((self.width() - width) / 2 + self.pan.x(),
                      (self.height() - height) / 2 + self.pan.y(), width, height)

    def image_point(self, point):
        rect = self.image_rect()
        if rect.isEmpty() or not rect.contains(point):
            return None
        x = math.floor((point.x() - rect.x()) * self.image.width() / rect.width())
        y = math.floor((point.y() - rect.y()) * self.image.height() / rect.height())
        if 0 <= x < self.image.width() and 0 <= y < self.image.height():
            return x, y
        return None

    def set_navigation(self, zoom, pan):
        self.zoom, self.pan = zoom, QPointF(pan)
        self.update()

    def fit(self):
        self.set_navigation(1.0, QPointF())
        self.navigation.emit(self.zoom, self.pan)

    def wheelEvent(self, event):
        old_zoom = self.zoom
        self.zoom = min(16.0, max(0.2, self.zoom * 1.2 ** (event.angleDelta().y() / 120)))
        anchor = event.position() - QPointF(self.width() / 2, self.height() / 2)
        self.pan = anchor - (anchor - self.pan) * (self.zoom / old_zoom)
        self.navigation.emit(self.zoom, self.pan)
        self.update()
        event.accept()

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self.pick:
            point = self.image_point(event.position())
            if point:
                color = self.image.pixelColor(*point)
                self.sampled.emit(f"{color.name().upper()}   α {color.alpha()}   ·   {point[0]}, {point[1]}")
                self.picked.emit(color.name().upper() if color.alpha() else None)
        else:
            self.drag_start = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event):
        self.hover = event.position()
        if self.drag_start is not None:
            self.pan += event.position() - self.drag_start
            self.drag_start = event.position()
            self.navigation.emit(self.zoom, self.pan)
        self.update()

    def mouseReleaseEvent(self, event):
        self.drag_start = None
        self.setCursor(Qt.CursorShape.CrossCursor if self.pick else Qt.CursorShape.OpenHandCursor)

    def leaveEvent(self, event):
        self.hover = None
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#11151b"))
        if self.image.isNull():
            painter.setPen(QColor("#929daf"))
            painter.drawText(self.rect().adjusted(16, 16, -16, -16),
                             Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self.empty_text)
            return
        rect = self.image_rect()
        painter.save()
        painter.setClipRect(rect)
        painter.fillRect(rect, QColor("#d9dde2" if self.background == "light" else "#252b34"))
        if self.background == "checker":
            # Paint only visible tiles, even when deeply zoomed into a large image.
            visible = rect.intersected(QRectF(self.rect()))
            for y in range(int(visible.top()) // 12 * 12, int(visible.bottom()) + 12, 12):
                for x in range(int(visible.left()) // 12 * 12, int(visible.right()) + 12, 12):
                    if (x // 12 + y // 12) % 2 == 0:
                        painter.fillRect(x, y, 12, 12, QColor("#303844"))
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, self.zoom < 3)
        painter.drawImage(rect, self.image)
        painter.restore()
        painter.setPen(QPen(QColor("#3b4554"), 1))
        painter.drawRect(rect)
        point = self.image_point(self.hover) if self.pick and self.hover is not None else None
        if point:
            # 19 source pixels at exactly 5x, independent of viewport scale and DPI.
            patch = QImage(19, 19, QImage.Format.Format_ARGB32)
            patch.fill(QColor("#303844"))
            patch_painter = QPainter(patch)
            patch_painter.drawImage(9 - point[0], 9 - point[1], self.image)
            patch_painter.end()
            x = max(4, min(self.width() - 100, int(self.hover.x()) + 20))
            y = max(4, min(self.height() - 100, int(self.hover.y()) + 20))
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
            painter.drawImage(QRectF(x, y, 95, 95), patch)
            painter.setPen(QPen(QColor("#77e1be"), 2))
            painter.drawRect(x, y, 95, 95)
            painter.drawRect(x + 45, y + 45, 5, 5)
