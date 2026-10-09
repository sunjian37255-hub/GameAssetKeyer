"""Editable stage inspector; the window decides when to save and process."""
# SPDX-License-Identifier: MPL-2.0
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLineEdit, QSlider, QVBoxLayout, QWidget

from ..color_key_processor import DEFAULT_PARAMS, TARGETS, parse_color
from .common import button, label


class Editor(QWidget):
    changed = Signal()

    def __init__(self, t, say):
        super().__init__()
        self.t, self.say = t, say
        self.loading = False
        self.fields = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 8, 0)
        self.mode = QComboBox()
        for key in ("black", "white", "green", "magenta", "custom"):
            self.mode.addItem(t(f"mode.{key}"), key)
        layout.addWidget(label(t("editor.target_color"), "muted"))
        layout.addWidget(self.mode)
        self.color = QLineEdit()
        self.color.setPlaceholderText("#RRGGBB")
        layout.addWidget(self.color)
        self.mode.currentIndexChanged.connect(self.mode_changed)
        self.color.editingFinished.connect(self.emit_change)
        self.key_body = QWidget()
        key_form = QFormLayout(self.key_body)
        key_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        key_form.setContentsMargins(0, 4, 0, 0)
        intensity_header = QHBoxLayout()
        intensity_header.addWidget(label(t("editor.intensity"), wrap=True))
        intensity_header.addStretch()
        self.intensity_value = label("3 / 5", "muted")
        intensity_header.addWidget(self.intensity_value)
        key_form.addRow(intensity_header)
        intensity = QSlider(Qt.Orientation.Horizontal)
        intensity.setRange(1, 5)
        intensity.setSingleStep(1)
        intensity.setPageStep(1)
        intensity.setTickInterval(1)
        intensity.setTickPosition(QSlider.TickPosition.TicksBelow)
        intensity.setValue(3)
        intensity.setAccessibleName(t("editor.intensity"))
        intensity.setMinimumHeight(28)
        self.fields["intensity"] = intensity
        intensity.valueChanged.connect(self.emit_change)
        key_form.addRow(intensity)
        self.intensity_hint = label("", "muted", True)
        key_form.addRow(self.intensity_hint)
        for key, title, low, high, step, decimals in [
            ("background_threshold", "param.background_threshold", 0, 1, .01, 3),
            ("foreground_threshold", "param.foreground_threshold", 0, 1, .01, 3),
            ("feather_radius", "param.feather", 0, 10, .1, 2),
            ("edge_erode", "param.edge_erode", 0, 8, 1, 0),
        ]:
            self.add_number(key_form, key, t(title), low, high, step, decimals)
        layout.addWidget(self.key_body)
        self.repair_body = QWidget()
        repair_form = QFormLayout(self.repair_body)
        repair_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        repair_form.setContentsMargins(0, 4, 0, 0)
        self.method = QComboBox()
        self.method.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.method.setMinimumContentsLength(14)
        self.method.addItem(t("despill.repair"), "repair")
        self.method.addItem(t("despill.legacy"), "legacy")
        repair_form.addRow(self.method)
        self.method.currentIndexChanged.connect(self.emit_change)
        for key, title, low, high, step, decimals in [
            ("despill_strength", "despill.strength", 0, 1, .05, 2),
            ("despill_width", "despill.width", 1, 32, 1, 0),
            ("despill_tolerance", "despill.tolerance", .01, 1, .05, 2),
        ]:
            self.add_number(repair_form, key, t(title), low, high, step, decimals)
        repair_form.addRow(label(t("despill.hint"), "muted", True))
        layout.addWidget(self.repair_body)
        self.advanced_toggle = button(say("Advanced ▸", "高级参数 ▸"))
        self.advanced_toggle.setToolTip(t("param.advanced_closed"))
        self.advanced_toggle.setCheckable(True)
        layout.addWidget(self.advanced_toggle)
        self.advanced = QWidget()
        advanced_form = QFormLayout(self.advanced)
        advanced_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        advanced_form.setContentsMargins(0, 0, 0, 0)
        for key, title, low, high, step, decimals in [
            ("min_hole_size", "param.min_hole", 0, 9999, 1, 0),
            ("alpha_gamma", "param.alpha_gamma", .1, 4, .1, 2),
            ("saturation_protect", "param.saturation_protect", 0, 1, .01, 2),
            ("output_alpha", "param.output_alpha", 0, 1, .01, 2),
        ]:
            self.add_number(advanced_form, key, t(title), low, high, step, decimals)
        for key, title in [("keep_sparks", "param.keep_sparks"), ("enable_hole_punch", "param.hole_punch")]:
            field = QCheckBox()
            field.setAccessibleName(t(title))
            caption = label(t(title), wrap=True)
            caption.setBuddy(field)
            self.fields[key] = field
            field.toggled.connect(self.emit_change)
            advanced_form.addRow(field, caption)
        layout.addWidget(self.advanced)
        self.advanced.hide()
        self.advanced_toggle.toggled.connect(self.advanced.setVisible)
        layout.addStretch()
        self.operation = "key"

    def add_number(self, form, key, title, low, high, step, decimals):
        field = QDoubleSpinBox()
        field.setRange(low, high)
        field.setDecimals(decimals)
        field.setSingleStep(step)
        field.setKeyboardTracking(False)
        field.setMaximumWidth(105)
        self.fields[key] = field
        field.valueChanged.connect(self.emit_change)
        caption = label(title, wrap=True)
        caption.setMinimumWidth(105)
        caption.setMaximumWidth(165)
        form.addRow(caption, field)

    def load(self, params):
        self.loading = True
        config = {**DEFAULT_PARAMS, **params}
        self.operation = config["operation"]
        self.mode.setCurrentIndex(self.mode.findData(config["target_mode"]))
        self.color.setText(config["custom_color"])
        self.method.setCurrentIndex(self.method.findData(config["despill_method"]))
        for key, field in self.fields.items():
            if isinstance(field, QCheckBox):
                field.setChecked(bool(config[key]))
            elif isinstance(field, QSlider):
                field.setValue(int(config[key]))
            else:
                field.setValue(config[key])
        repair = self.operation == "despill"
        self.key_body.setVisible(not repair)
        self.repair_body.setVisible(repair)
        self.advanced_toggle.setVisible(not repair)
        self.advanced.setVisible(not repair and self.advanced_toggle.isChecked())
        self.color.setEnabled(self.mode.currentData() == "custom")
        self.loading = False
        self.update_hint()

    def collect(self):
        result = DEFAULT_PARAMS.copy()
        result.update(operation=self.operation, target_mode=self.mode.currentData(),
                      custom_color=self.color.text().strip(), despill_method=self.method.currentData())
        parse_color(result["target_mode"], result["custom_color"])
        for key, field in self.fields.items():
            value = field.isChecked() if isinstance(field, QCheckBox) else field.value()
            result[key] = int(value) if isinstance(DEFAULT_PARAMS[key], int) and not isinstance(value, bool) else value
        return result

    def mode_changed(self):
        mode = self.mode.currentData()
        self.color.setEnabled(mode == "custom")
        if mode in TARGETS:
            self.color.setText("#{:02X}{:02X}{:02X}".format(*TARGETS[mode]))
        self.emit_change()

    def update_hint(self):
        mode = self.mode.currentData() or "black"
        level = int(self.fields["intensity"].value())
        self.intensity_value.setText(f"{level} / 5")
        self.intensity_hint.setText(self.t(f"intensity.{mode}.{level}"))

    def emit_change(self, *_):
        if self.loading:
            return
        self.update_hint()
        self.changed.emit()

    def set_picked_color(self, value):
        self.loading = True
        self.mode.setCurrentIndex(self.mode.findData("custom"))
        self.color.setText(value)
        self.loading = False
        self.emit_change()
