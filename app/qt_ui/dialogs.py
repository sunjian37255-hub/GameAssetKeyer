"""Parent-owned Qt dialogs; validate before returning requests to the UI worker."""
# SPDX-License-Identifier: MPL-2.0
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (
    QColorDialog, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QHBoxLayout, QLineEdit, QMessageBox, QSpinBox, QVBoxLayout, QWidget,
)

from ..color_key_processor import TARGETS
from ..ui.create_project_dialog import validate_create_values
from .common import button, label


class FormDialog(QDialog):
    def __init__(self, parent, title):
        super().__init__(parent)
        self.t, self.say = parent.t, parent.say
        self.setWindowTitle(f"GameAssetKeyer · {title}")
        self.setMinimumWidth(480)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(20, 20, 20, 20)
        self.layout.setSpacing(12)
        self.layout.addWidget(label(title, "section"))
        self.form = QFormLayout()
        self.layout.addLayout(self.form)
        self.request = None

    def number(self, title, value, low=0, high=99999):
        field = QSpinBox()
        field.setRange(low, high)
        field.setValue(value)
        self.form.addRow(title, field)
        return field

    def finish(self, submit):
        self.buttons = QDialogButtonBox()
        self.buttons.addButton(self.t("action.cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        self.submit = self.buttons.addButton(submit, QDialogButtonBox.ButtonRole.AcceptRole)
        self.submit.setObjectName("primary")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.layout.addWidget(self.buttons)

    def fail(self, error):
        message = self.t(error.message_key) if hasattr(error, "message_key") else str(error)
        QMessageBox.warning(self, self.say("Invalid input", "输入有误"), message)


class CreateDialog(FormDialog):
    def __init__(self, parent, kind):
        super().__init__(parent, parent.t(f"create.title.{kind}"))
        self.kind = kind
        self.source = QLineEdit()
        browse = QWidget()
        row = QHBoxLayout(browse)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.source, 1)
        row.addWidget(button(self.t("create.browse"), self.browse))
        self.form.addRow(self.t("create.input_file"), browse)
        self.name = QLineEdit()
        self.form.addRow(self.t("create.project_name"), self.name)
        self.rows = self.number(self.t("create.rows"), 1, 1) if kind == "sheet" else None
        self.cols = self.number(self.t("create.cols"), 1, 1) if kind == "sheet" else None
        self.interval = self.number(self.t("create.frame_interval"), 1, 1) if kind == "video" else None
        self.mode = QComboBox()
        for key in ("black", "white", "green", "magenta", "custom"):
            self.mode.addItem(self.t(f"mode.{key}"), key)
        self.form.addRow(self.t("create.target_color"), self.mode)
        self.color = QLineEdit("#000000")
        color_row = QWidget()
        color_layout = QHBoxLayout(color_row)
        color_layout.setContentsMargins(0, 0, 0, 0)
        color_layout.addWidget(self.color)
        color_layout.addWidget(button(self.t("create.choose_color"), self.choose_color))
        self.form.addRow(self.t("create.custom_color"), color_row)
        self.mode.currentIndexChanged.connect(self.mode_changed)
        self.mode_changed()
        self.preview = label("", wrap=True)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMaximumHeight(170)
        self.layout.addWidget(self.preview)
        self.finish(self.t("create.submit"))

    def browse(self):
        filters = "Video (*.mp4 *.mov *.avi *.mkv *.webm);;All files (*)" if self.kind == "video" else "PNG (*.png)"
        path, _ = QFileDialog.getOpenFileName(self, self.t("create.input_file"), "", filters)
        if not path:
            return
        self.source.setText(path)
        if not self.name.text().strip():
            self.name.setText(Path(path).stem)
        if self.kind != "video":
            pixmap = QPixmap(path)
            self.preview.setPixmap(pixmap.scaled(360, 160, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def mode_changed(self):
        mode = self.mode.currentData()
        self.color.setEnabled(mode == "custom")
        if mode in TARGETS:
            self.color.setText("#{:02X}{:02X}{:02X}".format(*TARGETS[mode]))

    def choose_color(self):
        color = QColorDialog.getColor(QColor(self.color.text()), self)
        if color.isValid():
            self.mode.setCurrentIndex(self.mode.findData("custom"))
            self.color.setText(color.name().upper())

    def accept(self):
        values = {"source": self.source.text(), "name": self.name.text(), "target_mode": self.mode.currentData(),
                  "custom_color": self.color.text(), "rows": str(self.rows.value()) if self.rows else "1",
                  "cols": str(self.cols.value()) if self.cols else "1",
                  "frame_interval": str(self.interval.value()) if self.interval else "1"}
        try:
            self.request = validate_create_values(self.kind, values)
        except ValueError as error:
            self.fail(error)
            return
        super().accept()


class PostprocessDialog(FormDialog):
    def __init__(self, parent, operation):
        super().__init__(parent, parent.t("tools.trim" if operation == "trim" else "tools.align"))
        self.operation = operation
        if operation == "trim":
            self.threshold = self.number(self.say("Alpha threshold", "Alpha 阈值"), 8, 0, 255)
            self.padding = self.number(self.say("Padding / px", "保留边距 / px"), 0)
            hint = self.say("Apply one shared crop to every frame. Alignment is optional.", "所有帧使用统一裁切范围；之后可按需对齐。")
        else:
            self.mode = QComboBox()
            for key in ("none", "center", "bottom_center"):
                self.mode.addItem(self.t(f"align.{key}"), key)
            self.mode.setCurrentIndex(1)
            self.form.addRow(self.t("dialog.align_mode"), self.mode)
            hint = self.say("Use valid trimmed frames, or current pipeline output when no valid trim exists.",
                            "使用有效裁切结果；没有有效裁切时使用当前 Pipeline 输出。可以直接对齐。")
        self.layout.addWidget(label(hint, "muted", True))
        self.finish(self.say("Apply to all frames", "应用到全部帧"))

    def accept(self):
        self.request = (self.threshold.value(), self.padding.value()) if self.operation == "trim" else (self.mode.currentData(),)
        super().accept()
