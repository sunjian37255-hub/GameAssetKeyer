"""Inline animation surface backed by the existing source resolver."""
# SPDX-License-Identifier: MPL-2.0
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QSlider, QSpinBox, QVBoxLayout, QWidget

from ..animation_preview import PreviewFrameCache, fps_interval_ms, next_frame_index, read_frame, resolve_animation_source
from .common import button, label, to_qimage
from .preview import Preview


class AnimationPanel(QWidget):
    back_requested = Signal()
    window_playback_requested = Signal()

    def __init__(self, parent):
        super().__init__(parent)
        self.parent_window = parent
        self.cache = PreviewFrameCache(max_items=8)
        self.source = None
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.advance)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.choice = QComboBox()
        for key in ("original", "input", "result", "final"):
            self.choice.addItem(parent.t(f"view.{key}"), key)
        self.choice.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.choice.setMinimumContentsLength(8)
        row.addWidget(self.choice, 1)
        row.addWidget(button(parent.say("Fit", "适应"), lambda: self.canvas.fit()))
        self.back = button(parent.say("■ Back", "■ 返回对比"), self.back_requested.emit)
        row.addWidget(self.back)
        layout.addLayout(row)
        row = QHBoxLayout()
        self.play = button(parent.t("animation.play"), self.toggle)
        row.addWidget(self.play)
        row.addWidget(label("FPS"))
        self.fps = QSpinBox()
        self.fps.setRange(1, 60)
        self.fps.setValue(12)
        self.fps.valueChanged.connect(lambda value: self.timer.setInterval(fps_interval_ms(value)))
        row.addWidget(self.fps)
        self.loop = QCheckBox(parent.say("Loop", "循环"))
        self.loop.setChecked(True)
        row.addWidget(self.loop)
        row.addStretch()
        layout.addLayout(row)
        self.window_playback = button(parent.say("Window playback", "完整界面播放"), self.window_playback_requested.emit)
        layout.addWidget(self.window_playback)
        self.canvas = Preview()
        self.canvas.background = parent.background.currentData()
        layout.addWidget(self.canvas, 1)
        self.seek = QSlider(Qt.Orientation.Horizontal)
        self.seek.valueChanged.connect(self.show_frame)
        layout.addWidget(self.seek)
        self.info = label("", "muted", True)
        layout.addWidget(self.info)
        self.choice.currentIndexChanged.connect(self.change_source)

    def set_window_playback(self, expanded):
        self.window_playback.setText(self.parent_window.say("Exit window playback", "退出完整界面播放") if expanded
                                     else self.parent_window.say("Window playback", "完整界面播放"))
        self.back.setText(self.parent_window.say("Exit", "退出") if expanded
                          else self.parent_window.say("■ Back", "■ 返回对比"))

    def activate(self, source_key):
        self.choice.blockSignals(True)
        self.choice.setCurrentIndex(self.choice.findData(source_key))
        self.choice.blockSignals(False)
        self.canvas.background = self.parent_window.background.currentData()
        self.load_source()
        if self.source:
            self.toggle()

    def change_source(self):
        playing = self.timer.isActive()
        self.load_source()
        if playing and self.source:
            self.toggle()

    def stop(self):
        self.timer.stop()
        self.play.setText(self.parent_window.t("animation.play"))

    def load_source(self):
        self.stop()
        self.cache.clear()
        session = self.parent_window.session
        try:
            self.source = resolve_animation_source(session.project, session.directory, self.choice.currentData(), session.stage_index)
            self.seek.blockSignals(True)
            self.seek.setRange(0, self.source.frame_count - 1)
            self.seek.setValue(0)
            self.seek.blockSignals(False)
            self.show_frame()
            self.play.setEnabled(self.source is not None)
        except Exception as error:
            self.source = None
            self.play.setEnabled(False)
            message = self.parent_window.t(error.message_key) if hasattr(error, "message_key") else str(error)
            self.canvas.set_image(None, message)
            self.info.setText(message)

    def show_frame(self):
        if self.source is None:
            return
        try:
            self.canvas.set_image(to_qimage(read_frame(self.source, self.seek.value(), self.cache)))
            self.info.setText(f"{self.seek.value() + 1} / {self.source.frame_count}")
        except Exception as error:
            self.stop()
            self.source = None
            self.play.setEnabled(False)
            self.canvas.set_image(None, str(error))
            self.info.setText(str(error))

    def toggle(self):
        if self.timer.isActive():
            self.stop()
        elif self.source:
            if self.seek.value() == self.source.frame_count - 1:
                self.seek.setValue(0)
            if self.source is None:
                return
            self.timer.start(fps_interval_ms(self.fps.value()))
            self.play.setText(self.parent_window.say("Pause", "暂停"))

    def advance(self):
        index = next_frame_index(self.seek.value(), self.source.frame_count, loop=self.loop.isChecked())
        if index is None:
            self.stop()
        else:
            self.seek.setValue(index)

    def cleanup(self):
        self.stop()
        self.cache.clear()
        self.source = None
        self.canvas.set_image(None)
