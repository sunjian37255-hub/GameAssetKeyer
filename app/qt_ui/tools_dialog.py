"""Single-window requests for independent asset tools; processing runs in Jobs."""
# SPDX-License-Identifier: MPL-2.0
import math
from pathlib import Path

import cv2
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QComboBox, QDoubleSpinBox, QFileDialog, QHBoxLayout, QLineEdit, QMessageBox, QSlider, QWidget

from ..frame_sequence_composer import calculate_layout, list_png_files, natural_sort_key
from ..video_splitter import inspect_video, validate_time_range
from ..ui.equal_grid_dialog import validate_equal_grid_values
from .common import button, label
from .dialogs import FormDialog


class ToolDialog(FormDialog):
    def __init__(self, parent, kind):
        keys = {"compose": "tools.sequence_composer", "video": "tools.video_frame_extractor", "grid": "tools.equal_grid"}
        super().__init__(parent, parent.t(keys[kind]))
        self.kind, self.files, self.metadata = kind, [], None
        self.source = QLineEdit()
        source_row = QWidget()
        row = QHBoxLayout(source_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.source)
        row.addWidget(button(self.t("create.browse"), self.browse))
        if kind == "compose":
            self.source.setReadOnly(True)
            row.addWidget(button(self.say("Folder", "文件夹"), self.browse_folder))
        self.form.addRow(self.t("create.input_file"), source_row)
        self.output = QLineEdit()
        output_row = QWidget()
        row = QHBoxLayout(output_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.output)
        row.addWidget(button(self.t("create.browse"), self.browse_output))
        self.form.addRow(self.say("Output", "输出位置"), output_row)
        self.fields = {}
        if kind in ("compose", "grid"):
            self.fields["rows"] = self.number(self.t("dialog.rows"), 1, 1)
            self.fields["cols"] = self.number(self.t("dialog.cols"), 1, 1)
        if kind == "compose":
            self.fields["padding"] = self.number(self.say("Padding / px", "边距 / px"), 0, 0, 256)
            self.alignment = QComboBox()
            for key in ("center", "bottom_center"):
                self.alignment.addItem({"center": self.t("align.center"),
                                        "bottom_center": self.t("align.bottom_center")}[key], key)
            self.form.addRow(self.t("dialog.align_mode"), self.alignment)
            self.fields["rows"].valueChanged.connect(lambda: self.update_grid("rows"))
            self.fields["cols"].valueChanged.connect(lambda: self.update_grid("cols"))
            self.fields["padding"].valueChanged.connect(lambda: self.update_grid("cols"))
        elif kind == "grid":
            self.fields["cell_width"] = self.number(self.say("Cell width (0 = auto)", "单元宽度（0 = 自动）"), 0)
            self.fields["cell_height"] = self.number(self.say("Cell height (0 = auto)", "单元高度（0 = 自动）"), 0)
            self.background = QComboBox()
            for key, en, zh in [("auto", "Auto", "自动"), ("transparent", "Transparent", "透明"),
                                ("black", "Black", "黑色"), ("green", "Green", "绿色")]:
                self.background.addItem(self.say(en, zh), key)
            self.form.addRow(self.say("Background", "背景"), self.background)
            self.assignment = QComboBox()
            for key, en, zh in [("cell", "By cell", "按单元"), ("component", "By component", "按连通块")]:
                self.assignment.addItem(self.say(en, zh), key)
            self.form.addRow(self.say("Assignment", "分配方式"), self.assignment)
            self.fields["alpha_threshold"] = self.number(self.say("Alpha threshold", "Alpha 阈值"), 8, 0, 255)
            self.fields["black_threshold"] = self.number(self.say("Black threshold", "黑色阈值"), 20, 0, 255)
        else:
            for key, en, zh, default in [("start", "Start / seconds", "开始 / 秒", 0), ("end", "End / seconds", "结束 / 秒", 1)]:
                field = QDoubleSpinBox()
                field.setDecimals(3)
                field.setRange(0, 999999)
                field.setValue(default)
                self.fields[key] = field
                self.form.addRow(self.say(en, zh), field)
            self.preview = label("", wrap=True)
            self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.preview.setMinimumHeight(150)
            self.layout.addWidget(self.preview)
            self.seek = QSlider(Qt.Orientation.Horizontal)
            self.seek.setRange(0, 1000)
            self.seek.sliderReleased.connect(self.preview_video)
            self.layout.addWidget(self.seek)
            markers = QHBoxLayout()
            markers.addWidget(button(self.say("Set start here", "设为开始"), lambda: self.set_marker("start")))
            markers.addWidget(button(self.say("Set end here", "设为结束"), lambda: self.set_marker("end")))
            self.layout.addLayout(markers)
        self.info = label("", "muted", True)
        self.layout.addWidget(self.info)
        self.finish(self.say("Run tool", "开始处理"))

    def browse(self):
        if self.kind == "compose":
            paths, _ = QFileDialog.getOpenFileNames(self, self.t("create.input_file"), "", "PNG (*.png)")
            if paths:
                self.set_files([Path(path) for path in paths])
            return
        filters = "Video (*.mp4 *.avi *.mov *.mkv *.webm);;All files (*)" if self.kind == "video" else "PNG (*.png)"
        path, _ = QFileDialog.getOpenFileName(self, self.t("create.input_file"), "", filters)
        if path:
            self.source.setText(path)
            source = Path(path)
            self.output.setText(str(source.with_name(source.stem + ("_frames" if self.kind == "video" else "_expanded.png"))))
            if self.kind == "video":
                try:
                    self.metadata = inspect_video(source)
                    self.fields["end"].setValue(self.metadata.duration_seconds)
                    self.info.setText(f"{self.metadata.width} × {self.metadata.height}  ·  {self.metadata.fps:.3f} FPS  ·  {self.metadata.duration_seconds:.3f} s")
                    self.preview_video()
                except Exception as error:
                    self.fail(error)

    def browse_folder(self):
        directory = QFileDialog.getExistingDirectory(self, self.say("PNG folder", "PNG 文件夹"))
        if directory:
            self.set_files(list_png_files(Path(directory)))

    def set_files(self, paths):
        self.files = sorted(paths, key=natural_sort_key)
        self.source.setText(self.say(f"{len(paths)} PNG files", f"{len(paths)} 张 PNG"))
        if self.files:
            self.output.setText(str(self.files[0].parent / "sheet_composed.png"))
            self.fields["cols"].setValue(max(1, math.ceil(math.sqrt(len(self.files)))))
            self.update_grid("cols")

    def update_grid(self, changed):
        if not self.files:
            return
        count = len(self.files)
        other = "cols" if changed == "rows" else "rows"
        field = self.fields[other]
        field.blockSignals(True)
        field.setValue(max(1, math.ceil(count / self.fields[changed].value())))
        field.blockSignals(False)
        try:
            layout = calculate_layout(self.files, self.fields["cols"].value(), self.fields["padding"].value())
            self.info.setText(f"{layout.frame_count} PNG  ·  {layout.columns} × {layout.rows}  ·  {layout.output_width} × {layout.output_height} px")
        except Exception as error:
            self.info.setText(str(error))

    def browse_output(self):
        if self.kind == "video":
            parent = QFileDialog.getExistingDirectory(self, self.say("Output parent folder", "输出父文件夹"))
            if parent:
                self.output.setText(str(Path(parent) / (Path(self.source.text()).stem + "_frames")))
        else:
            path, _ = QFileDialog.getSaveFileName(self, self.say("Output PNG", "输出 PNG"), self.output.text(), "PNG (*.png)")
            if path:
                self.output.setText(path)

    def set_marker(self, key):
        if self.metadata:
            self.fields[key].setValue(self.seek.value() / 1000 * self.metadata.duration_seconds)
            self.preview_video()

    def preview_video(self):
        if self.metadata is None:
            return
        capture = cv2.VideoCapture(str(self.metadata.path))
        try:
            frame = min(self.metadata.frame_count - 1, int(self.seek.value() / 1000 * self.metadata.frame_count))
            capture.set(cv2.CAP_PROP_POS_FRAMES, frame)
            ok, pixels = capture.read()
            if ok:
                rgb = cv2.cvtColor(pixels, cv2.COLOR_BGR2RGB)
                image = QImage(rgb.data, rgb.shape[1], rgb.shape[0], rgb.strides[0], QImage.Format.Format_RGB888).copy()
                self.preview.setPixmap(QPixmap.fromImage(image).scaled(420, 220, Qt.AspectRatioMode.KeepAspectRatio,
                                                                     Qt.TransformationMode.SmoothTransformation))
        finally:
            capture.release()

    def accept(self):
        try:
            if not self.output.text().strip():
                raise ValueError(self.say("Choose an output path", "请选择输出位置"))
            output = Path(self.output.text().strip()).resolve()
            if self.kind == "compose":
                if not self.files or output.suffix.lower() != ".png":
                    raise ValueError(self.say("Select PNG inputs and a PNG output", "请选择 PNG 输入和 PNG 输出文件"))
                if output in [p.resolve() for p in self.files]:
                    raise ValueError(self.say("Output cannot overwrite an input frame", "输出不能覆盖输入帧"))
                calculate_layout(self.files, self.fields["cols"].value(), self.fields["padding"].value())
                self.request = dict(source=self.files, output_path=output, columns=self.fields["cols"].value(),
                                    padding=self.fields["padding"].value(), alignment=self.alignment.currentData())
            elif self.kind == "video":
                metadata = inspect_video(Path(self.source.text()))
                start, end = self.fields["start"].value(), self.fields["end"].value()
                validate_time_range(metadata, start, end)
                self.request = dict(video_path=metadata.path, start_seconds=start, end_seconds=end, output_dir=output)
            else:
                values = {key: str(field.value()) for key, field in self.fields.items()}
                values.update(source=self.source.text(), output=str(output), background_mode=self.background.currentData(),
                              assignment_mode=self.assignment.currentData())
                validated = validate_equal_grid_values(values)
                self.request = {key: field.value() for key, field in self.fields.items()}
                self.request.update(image_path=validated["source"], output_path=validated["output"],
                                    background_mode=self.background.currentData(), assignment_mode=self.assignment.currentData())
            if self.kind != "video" and output.exists():
                if QMessageBox.question(self, self.say("Replace file?", "覆盖文件？"), str(output),
                                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                        QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
                    return
        except Exception as error:
            self.fail(error)
            return
        super().accept()
