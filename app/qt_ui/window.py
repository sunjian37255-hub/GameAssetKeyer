"""Qt source workbench, using the existing project, pipeline and export services."""
# SPDX-License-Identifier: MPL-2.0
from pathlib import Path
import sys

from PySide6.QtCore import QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QFileDialog, QFrame, QGroupBox, QHBoxLayout,
    QInputDialog, QLineEdit, QListView, QListWidget, QListWidgetItem, QMainWindow,
    QMenu, QMessageBox, QProgressBar, QScrollArea, QSizePolicy, QSplitter,
    QStackedWidget, QVBoxLayout, QWidget,
)

from ..color_key_processor import DEFAULT_PARAMS
from ..compute_backend import configure_backend, current_backend, initialize_backend, save_backend_preference
from ..equal_grid_utils import normalize_equal_grid
from ..frame_sequence_composer import export_sprite_sheet
from ..i18n import I18n
from ..preset_manager import load_preset, save_preset
from ..project_manager import INITIAL_BASIC_PARAMS
from ..video_splitter import extract_video_range, unique_output_dir
from ..workers import PipelineFrameWorker, PipelineWorker
from .common import ASSETS, MATERIAL_FILES, apply_theme, button, label, thumbnail, to_qimage
from .animation import AnimationPanel
from .dialogs import CreateDialog, PostprocessDialog
from .editor import Editor
from .jobs import Jobs
from .preview import Preview
from .session import Session, render_preview
from .tools_dialog import ToolDialog


class Window(QMainWindow):
    def __init__(self, root):
        super().__init__()
        self.root = Path(root)
        self.session = Session(self.root)
        self.i18n = I18n(self.root)
        self.t = self.i18n.tr
        initialize_backend(self.root)
        self.jobs = Jobs(self)
        self.jobs.progress.connect(self.on_progress)
        self.jobs.finished.connect(self.on_finished)
        self.revision = self.preview_revision = 0
        self.preview_pending = self.dirty = False
        self.images = {}
        self.debounce = QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.setInterval(250)
        self.debounce.timeout.connect(self.request_preview)
        self.material = all((ASSETS / name).is_file() for name in MATERIAL_FILES)
        self.setWindowTitle("GameAssetKeyer" if getattr(sys, "frozen", False) else "GameAssetKeyer — Qt Source")
        self.setMinimumSize(1000, 640)
        screen = self.screen().availableGeometry()
        self.resize(min(1420, screen.width() - 50), min(850, screen.height() - 65))
        self.build_ui()
        self.refresh_projects()
        QShortcut(QKeySequence("Escape"), self, activated=self.escape_preview)

    def say(self, english, chinese):
        return chinese if self.i18n.locale == "zh_CN" else english

    def build_ui(self):
        old = self.takeCentralWidget()
        if old:
            old.deleteLater()
        container = QWidget()
        outer = QVBoxLayout(container)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.header = QFrame()
        self.header.setObjectName("header")
        row = QHBoxLayout(self.header)
        row.setContentsMargins(22, 12, 22, 12)
        row.addWidget(label("◈  GameAssetKeyer", "brand"))
        row.addWidget(button(self.t("nav.home"), self.show_home))
        row.addStretch()
        self.backend = QComboBox()
        self.backend.addItem("CPU", "cpu")
        self.backend.addItem("GPU · OpenCL", "gpu")
        self.backend.setCurrentIndex(self.backend.findData(current_backend()))
        self.backend.currentIndexChanged.connect(self.change_backend)
        self.backend.setEnabled(not getattr(sys, "frozen", False))
        row.addWidget(self.backend)
        self.language = QComboBox()
        self.language.addItem("English", "en_US")
        self.language.addItem("简体中文", "zh_CN")
        self.language.setCurrentIndex(self.language.findData(self.i18n.locale))
        self.language.currentIndexChanged.connect(self.change_language)
        row.addWidget(self.language)
        skin = button(self.say("Materials", "材质皮肤"))
        skin.setCheckable(True)
        skin.setChecked(self.material)
        skin.setEnabled(all((ASSETS / name).is_file() for name in MATERIAL_FILES))
        skin.setVisible(skin.isEnabled())
        skin.toggled.connect(self.change_theme)
        row.addWidget(skin)
        row.addWidget(label("QT / CPU" if getattr(sys, "frozen", False) else "QT / SOURCE", "badge"))
        outer.addWidget(self.header)
        self.pages = QStackedWidget()
        outer.addWidget(self.pages, 1)
        self.build_home()
        self.build_workbench()
        self.workspace_stack = QStackedWidget()
        self.workspace_stack.addWidget(container)
        self.setCentralWidget(self.workspace_stack)
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(220)
        self.progress.hide()
        # Status widgets are outside the rebuilt central widget.
        for widget in getattr(self, "old_status_widgets", []):
            self.statusBar().removeWidget(widget)
            widget.deleteLater()
        self.cancel_button = button(self.t("action.cancel"), self.jobs.cancel)
        self.cancel_button.hide()
        self.statusBar().addPermanentWidget(self.progress)
        self.statusBar().addPermanentWidget(self.cancel_button)
        self.old_status_widgets = [self.progress, self.cancel_button]
        apply_theme(QApplication.instance(), self.material)

    def build_home(self):
        page = QWidget()
        page.setObjectName("page")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 24, 30, 14)
        layout.setSpacing(15)
        layout.addWidget(label("YOUR LOCAL ASSET WORKSPACE", "eyebrow"))
        layout.addWidget(label(self.say("Let your assets take the stage.", "让素材，回归画面本身。"), "hero"))
        layout.addWidget(label(self.t("home.subtitle"), "muted", True))
        cards = QHBoxLayout()
        for index, kind, key in [(1, "image", "image"), (2, "sheet", "sheet"), (3, "video", "video")]:
            card = QFrame()
            card.setObjectName("card")
            box = QVBoxLayout(card)
            box.setContentsMargins(18, 14, 18, 14)
            top = QHBoxLayout()
            top.addWidget(label(self.t(f"home.{key}"), "section"))
            top.addStretch()
            top.addWidget(label(f"0{index}", "eyebrow"))
            box.addLayout(top)
            box.addWidget(label(self.t(f"home.{key}_subtitle"), "muted", True))
            box.addWidget(button(self.t("home.start"), lambda checked=False, k=kind: self.create_project(k)))
            cards.addWidget(card, 1)
        layout.addLayout(cards)
        tools = QHBoxLayout()
        tools.addWidget(label(self.t("home.standalone_tools"), "section"))
        for kind, key in [("compose", "sequence_composer"), ("video", "video_frame_extractor"), ("grid", "equal_grid")]:
            tools.addWidget(button(self.t(f"tools.{key}"), lambda checked=False, k=kind: self.run_tool(k)))
        tools.addStretch()
        layout.addLayout(tools)
        heading = QHBoxLayout()
        heading.addWidget(label(self.t("recent.title"), "section"))
        heading.addStretch()
        self.search = QLineEdit()
        self.search.setPlaceholderText(self.say("Search projects…", "搜索项目…"))
        self.search.setMaximumWidth(280)
        self.search.textChanged.connect(self.filter_projects)
        heading.addWidget(self.search)
        layout.addLayout(heading)
        self.project_list = QListWidget()
        self.project_list.setObjectName("projects")
        self.project_list.setViewMode(QListView.ViewMode.IconMode)
        self.project_list.setResizeMode(QListView.ResizeMode.Adjust)
        self.project_list.setMovement(QListView.Movement.Static)
        self.project_list.setIconSize(QSize(192, 116))
        self.project_list.setGridSize(QSize(245, 195))
        self.project_list.itemDoubleClicked.connect(lambda item: self.open_project(item.data(Qt.ItemDataRole.UserRole)))
        self.project_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.project_list.customContextMenuRequested.connect(self.project_menu)
        layout.addWidget(self.project_list, 1)
        self.pages.addWidget(page)

    def build_workbench(self):
        page = QWidget()
        page.setObjectName("page")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 14, 14, 8)
        self.project_title = label("", "section")
        self.project_title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.project_title)
        self.columns = QSplitter(Qt.Orientation.Horizontal)
        self.columns.setChildrenCollapsible(False)
        self.columns.setHandleWidth(7)
        frame_panel = QFrame()
        frame_panel.setObjectName("texturedPanel")
        frame_panel.setMinimumWidth(112)
        frame_layout = QVBoxLayout(frame_panel)
        frame_layout.setContentsMargins(8, 12, 8, 8)
        self.frame_heading = label(self.say("Frames", "帧"), "section")
        frame_layout.addWidget(self.frame_heading)
        self.frame_list = QListWidget()
        self.frame_list.setViewMode(QListView.ViewMode.IconMode)
        self.frame_list.setMovement(QListView.Movement.Static)
        self.frame_list.setFlow(QListView.Flow.TopToBottom)
        self.frame_list.setWrapping(False)
        self.frame_list.setGridSize(QSize(84, 92))
        self.frame_list.setIconSize(QSize(72, 60))
        self.frame_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.frame_list.currentRowChanged.connect(self.select_frame)
        frame_layout.addWidget(self.frame_list, 1)
        self.columns.addWidget(frame_panel)
        center = QWidget()
        center.setMinimumWidth(330)
        central = QVBoxLayout(center)
        central.setContentsMargins(0, 0, 0, 0)
        toolbar = QHBoxLayout()
        toolbar.addWidget(button(self.say("Fit", "适应"), self.fit_preview))
        self.pick_button = button(self.t("editor.eyedropper") + " · 5×")
        self.pick_button.setCheckable(True)
        self.pick_button.toggled.connect(self.toggle_picker)
        toolbar.addWidget(self.pick_button)
        toolbar.addStretch()
        self.background = QComboBox()
        for en, zh, key in [("Checker", "棋盘格", "checker"), ("Dark", "深色", "dark"), ("Light", "浅色", "light")]:
            self.background.addItem(self.say(en, zh), key)
        self.background.currentIndexChanged.connect(self.change_background)
        toolbar.addWidget(self.background)
        central.addLayout(toolbar)
        views = QSplitter(Qt.Orientation.Horizontal)
        views.setChildrenCollapsible(False)
        self.left, self.right = Preview(), Preview()
        self.left_source, self.right_source = QComboBox(), QComboBox()
        for combo, choices, canvas in [(self.left_source, ("original", "input"), self.left),
                                        (self.right_source, ("result", "final"), self.right)]:
            panel = QWidget()
            box = QVBoxLayout(panel)
            box.setContentsMargins(0, 0, 0, 0)
            for key in choices:
                combo.addItem(self.t(f"view.{key}"), key)
            combo.currentIndexChanged.connect(self.display_images)
            box.addWidget(combo)
            box.addWidget(canvas, 1)
            views.addWidget(panel)
            canvas.picked.connect(self.picked_color)
            canvas.sampled.connect(self.statusBar().showMessage)
        self.left_source.setCurrentIndex(1)
        self.left.navigation.connect(self.right.set_navigation)
        self.right.navigation.connect(self.left.set_navigation)
        self.preview_stack = QStackedWidget()
        self.preview_stack.addWidget(views)
        self.animation = AnimationPanel(self)
        self.animation.back_requested.connect(self.exit_animation_view)
        self.animation.window_playback_requested.connect(self.toggle_window_playback)
        self.preview_stack.addWidget(self.animation)
        central.addWidget(self.preview_stack, 1)
        self.animation_button = button(self.say("▶ Play preview", "▶ 播放预览"), self.animate)
        central.addWidget(self.animation_button)
        self.postprocess = QGroupBox(self.say("Post-processing · Final result", "后处理 · 最终结果"))
        post_layout = QVBoxLayout(self.postprocess)
        row = QHBoxLayout()
        self.trim_button = button(self.t("tools.trim"), lambda: self.postprocess_dialog("trim"))
        self.align_button = button(self.t("tools.align"), lambda: self.postprocess_dialog("align"))
        row.addWidget(self.trim_button)
        row.addWidget(self.align_button)
        post_layout.addLayout(row)
        self.export_button = button(self.t("tools.export"), self.export_result, True)
        post_layout.addWidget(self.export_button)
        self.final_info = label("", "muted", True)
        post_layout.addWidget(self.final_info)
        central.addWidget(self.postprocess)
        self.columns.addWidget(center)
        self.inspector = QFrame()
        self.inspector.setObjectName("texturedPanel")
        self.inspector.setMinimumWidth(315)
        side = QVBoxLayout(self.inspector)
        side.setContentsMargins(12, 12, 12, 10)
        side.addWidget(label(self.t("pipeline.title"), "section"))
        self.stage_list = QListWidget()
        self.stage_list.setMaximumHeight(118)
        self.stage_list.setMinimumHeight(65)
        self.stage_list.currentRowChanged.connect(self.select_stage)
        self.stage_list.itemChanged.connect(self.enable_stage)
        side.addWidget(self.stage_list)
        actions = QHBoxLayout()
        for text, action in [("+ Key", "add"), (self.t("despill.add"), "repair"), ("↑", "up"), ("↓", "down")]:
            actions.addWidget(button(text, lambda checked=False, a=action: self.change_stage(a)))
        side.addLayout(actions)
        actions = QHBoxLayout()
        for key, action in [("action.duplicate", "duplicate"), ("action.delete", "delete")]:
            actions.addWidget(button(self.t(key), lambda checked=False, a=action: self.change_stage(a)))
        side.addLayout(actions)
        self.editor = Editor(self.t, self.say)
        self.editor.changed.connect(self.parameters_changed)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        form = QWidget()
        form_box = QVBoxLayout(form)
        form_box.setContentsMargins(0, 0, 0, 0)
        form_box.addWidget(self.editor)
        self.override_label = label("", "muted", True)
        form_box.addWidget(self.override_label)
        frame_override = button(self.say("Frame override", "当前帧独立参数"), self.make_override)
        frame_override.setToolTip(self.say("Create separate settings before editing this frame.", "先启用独立参数，再调整当前帧。"))
        form_box.addWidget(frame_override)
        defaults = button(self.say("Stage defaults", "恢复阶段默认参数"), self.clear_override)
        defaults.setToolTip(self.t("action.clear_frame_override"))
        form_box.addWidget(defaults)
        presets = QHBoxLayout()
        for text, key, save in [(self.say("Load", "加载预设"), "preset.load", False),
                                (self.say("Save", "保存预设"), "preset.save", True)]:
            action = button(text, lambda checked=False, s=save: self.preset(s))
            action.setToolTip(self.t(key))
            presets.addWidget(action)
        form_box.addLayout(presets)
        self.scroll.setWidget(form)
        side.addWidget(self.scroll, 1)
        self.process_actions = QWidget()
        buttons = QVBoxLayout(self.process_actions)
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.addWidget(button(self.t("action.preview_stage"), self.request_preview))
        buttons.addWidget(button(self.t("action.process_frame"), lambda: self.process(False)))
        buttons.addWidget(button(self.t("action.process_all"), lambda: self.process(True), True))
        side.addWidget(self.process_actions)
        self.columns.addWidget(self.inspector)
        self.columns.setStretchFactor(0, 0)
        self.columns.setStretchFactor(1, 1)
        self.columns.setStretchFactor(2, 0)
        self.columns.setSizes([122, 925, 325])
        layout.addWidget(self.columns, 1)
        self.pages.addWidget(page)

    def fail(self, error):
        message = self.t(error.message_key) if hasattr(error, "message_key") else str(error)
        QMessageBox.warning(self, "GameAssetKeyer", message)

    def ready(self):
        if self.jobs.busy:
            self.statusBar().showMessage(self.say("Please wait for the current task.", "请等待当前任务完成。"))
            return False
        return self.flush_params()

    def refresh_projects(self):
        self.project_list.clear()
        try:
            projects = self.session.manager.list_projects()
        except Exception as error:
            self.fail(error)
            return
        for project in projects:
            frames = sorted((Path(project["path"]) / "01_frames_raw").glob("frame_*.png"))
            kind = "VIDEO" if project["project_type"] == "video" else "PNG" if len(frames) == 1 else "SPRITE SHEET"
            item = QListWidgetItem(f"{project['name']}\n{kind} / {len(frames)}")
            item.setData(Qt.ItemDataRole.UserRole, project["id"])
            item.setToolTip(project["name"])
            if frames:
                item.setIcon(thumbnail(frames[0]))
            self.project_list.addItem(item)
        self.filter_projects(self.search.text())

    def filter_projects(self, text):
        for index in range(self.project_list.count()):
            item = self.project_list.item(index)
            item.setHidden(text.casefold() not in item.text().casefold())

    def project_menu(self, position):
        item = self.project_list.itemAt(position)
        if not item or not self.ready():
            return
        project_id = item.data(Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        actions = {menu.addAction(self.t(f"project.menu.{key}")): key for key in ("open", "rename", "delete")}
        action = actions.get(menu.exec(self.project_list.viewport().mapToGlobal(position)))
        try:
            if action == "open":
                self.open_project(project_id)
            elif action == "rename":
                name, accepted = QInputDialog.getText(self, self.t("project.menu.rename"), self.t("create.project_name"),
                                                     text=item.toolTip())
                if accepted:
                    project = self.session.manager.rename_project(project_id, name)
                    if self.session.project_id == project_id:
                        self.session.project = project
                    self.refresh_projects()
            elif action == "delete" and self.confirm(self.t("project.delete.confirm", name=item.toolTip())):
                target = self.session.manager.project_path(project_id).resolve()
                if target.parent != self.session.manager.projects_root.resolve():
                    raise ValueError("Invalid project directory")
                self.session.manager.delete_project(project_id)
                if self.session.project_id == project_id:
                    self.session.project = self.session.project_id = None
                    self.session.frames = []
                    self.images = {}
                self.refresh_projects()
        except Exception as error:
            self.fail(error)

    def confirm(self, text):
        return QMessageBox.question(self, "GameAssetKeyer", text,
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                    QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes

    def show_home(self):
        if self.ready():
            self.stop_animation()
            self.debounce.stop()
            self.pick_button.setChecked(False)
            self.pages.setCurrentIndex(0)
            self.refresh_projects()

    def open_project(self, project_id):
        if not self.ready():
            return
        try:
            self.session.open(project_id)
            self.populate_project()
            self.invalidate_display()
            self.request_preview()
        except Exception as error:
            self.fail(error)

    def populate_project(self):
        self.project_title.setText(self.session.project.get("name", self.session.project_id))
        self.project_title.setToolTip(self.project_title.text())
        self.frame_list.blockSignals(True)
        self.frame_list.clear()
        for index, path in enumerate(self.session.frames):
            item = QListWidgetItem(f"{index + 1:04d}")
            item.setToolTip(path.name)
            # Keep project opening bounded; selected frames get their icon on demand.
            if index < 100:
                item.setIcon(thumbnail(path, QSize(72, 60)))
            self.frame_list.addItem(item)
        self.frame_list.setCurrentRow(self.session.frame_index)
        self.frame_list.blockSignals(False)
        self.frame_heading.setText(self.say("Frames", "帧") + f" · {len(self.session.frames)}")
        self.export_button.setText(self.t("tools.export_video" if self.session.project.get("project_type") == "video" else "tools.export"))
        self.refresh_stages()
        self.load_editor()
        self.pages.setCurrentIndex(1)

    def refresh_stages(self):
        self.stage_list.blockSignals(True)
        self.stage_list.clear()
        for index, stage in enumerate(self.session.stages):
            operation = self.t("despill.name") if stage["params"].get("operation") == "despill" else "Key"
            item = QListWidgetItem(f"{index + 1:02d} · {operation} · {self.t('stage.' + stage['status'])}")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if stage["enabled"] else Qt.CheckState.Unchecked)
            self.stage_list.addItem(item)
        self.stage_list.setCurrentRow(self.session.stage_index)
        self.stage_list.blockSignals(False)

    def load_editor(self):
        self.editor.load(self.session.params())
        self.override_label.setText(self.t("frame.override" if self.session.has_override() else "frame.default"))
        self.dirty = False

    def flush_params(self):
        self.debounce.stop()
        if not self.dirty or self.session.project is None:
            return True
        try:
            self.session.apply_params(self.editor.collect())
            self.dirty = False
            self.refresh_stages()
            return True
        except Exception as error:
            self.fail(error)
            return False

    def parameters_changed(self):
        if self.session.project is None:
            return
        self.dirty = True
        self.invalidate_display()
        self.debounce.start()

    def invalidate_display(self):
        self.stop_animation()
        self.revision += 1
        self.images = {}
        self.display_images()

    def select_frame(self, index):
        if index < 0 or not self.session.project:
            return
        if not self.flush_params():
            self.frame_list.blockSignals(True)
            self.frame_list.setCurrentRow(self.session.frame_index)
            self.frame_list.blockSignals(False)
            return
        self.session.frame_index = index
        self.frame_list.item(index).setIcon(thumbnail(self.session.frames[index], QSize(72, 60)))
        self.load_editor()
        self.invalidate_display()
        self.request_preview()

    def select_stage(self, index):
        if index < 0 or not self.session.project:
            return
        if not self.flush_params():
            self.refresh_stages()
            return
        self.session.stage_index = index
        self.refresh_stages()
        self.load_editor()
        self.invalidate_display()
        self.request_preview()

    def change_stage(self, action):
        if not self.session.project or not self.flush_params():
            return
        try:
            params = None
            if action in ("add", "repair"):
                params = {**DEFAULT_PARAMS, **INITIAL_BASIC_PARAMS, "target_mode": self.editor.mode.currentData(),
                          "custom_color": self.editor.color.text()}
                if action == "repair":
                    params.update(operation="despill", despill_method="repair")
                action = "add"
            self.session.change_stage(action, params=params)
            self.refresh_stages()
            self.load_editor()
            self.invalidate_display()
            self.request_preview()
        except Exception as error:
            self.fail(error)

    def enable_stage(self, item):
        index = self.stage_list.row(item)
        enabled = item.checkState() == Qt.CheckState.Checked
        if not self.flush_params():
            self.refresh_stages()
            return
        # A checkbox may belong to a stage other than the selected editor.
        from ..pipeline import set_stage_enabled
        try:
            set_stage_enabled(self.session.project, index, enabled)
            self.session.save()
            self.refresh_stages()
            self.invalidate_display()
            self.request_preview()
        except Exception as error:
            self.fail(error)

    def make_override(self):
        if not self.flush_params():
            return
        try:
            self.session.apply_params(self.editor.collect(), frame_only=True)
            self.load_editor()
            self.invalidate_display()
            self.request_preview()
        except Exception as error:
            self.fail(error)

    def clear_override(self):
        if not self.flush_params():
            return
        try:
            self.session.clear_override()
            self.load_editor()
            self.invalidate_display()
            self.request_preview()
        except Exception as error:
            self.fail(error)

    def request_preview(self):
        if self.session.project is None or not self.flush_params():
            return
        if self.jobs.busy:
            self.preview_pending = True
            return
        self.preview_pending = False
        self.preview_revision = self.revision
        args = self.session.preview_request()
        self.start_job("preview", lambda: render_preview(*args))

    def display_images(self):
        if not hasattr(self, "left_source"):
            return
        for canvas, combo in [(self.left, self.left_source), (self.right, self.right_source)]:
            key = combo.currentData()
            hint = self.say("No valid final result. Process all frames first.", "暂无有效最终结果，请先处理全部帧。") if key == "final" else self.say("Updating preview…", "正在更新预览…")
            canvas.set_image(to_qimage(self.images.get(key)), hint)
        if hasattr(self, "final_info"):
            self.final_info.setText(self.say("Final preview and export use the same validated source.", "最终预览与导出使用同一份有效结果。") if self.images.get("final") is not None
                                   else self.say("No valid final result · process all frames first", "暂无有效最终结果 · 请先处理全部帧"))

    def toggle_picker(self, enabled):
        for canvas in (self.left, self.right):
            canvas.pick = enabled
            canvas.setCursor(Qt.CursorShape.CrossCursor if enabled else Qt.CursorShape.OpenHandCursor)
            canvas.update()

    def picked_color(self, color):
        if color is None:
            self.statusBar().showMessage(self.say("Transparent pixel: select a visible edge or color.", "该像素完全透明，请选择可见边缘或颜色。"))
            return
        self.editor.set_picked_color(color)
        self.pick_button.setChecked(False)

    def change_background(self):
        for canvas in (self.left, self.right, self.animation.canvas):
            canvas.background = self.background.currentData()
            canvas.update()

    def start_job(self, kind, function=None, worker=None):
        self.stop_animation()
        self.debounce.stop()
        self.pick_button.setChecked(False)
        self.jobs.start(kind, function, worker)
        heavy = kind != "preview"
        self.header.setEnabled(False)
        self.pages.widget(0).setEnabled(False)
        self.inspector.setEnabled(not heavy)
        self.frame_list.setEnabled(not heavy)
        self.process_actions.setEnabled(False)
        self.postprocess.setEnabled(False)
        self.animation_button.setEnabled(False)
        self.pick_button.setEnabled(not heavy)
        self.progress.setRange(0, 0)
        self.progress.show()
        self.cancel_button.setVisible(kind in ("pipeline", "frame", "tool_video"))
        self.statusBar().showMessage(self.say("Working…", "正在处理…"))

    def on_progress(self, event):
        if "percent" in event:
            self.progress.setRange(0, 100)
            self.progress.setValue(int(event["percent"]))

    def on_finished(self, kind, result, error):
        self.header.setEnabled(True)
        self.pages.widget(0).setEnabled(True)
        self.inspector.setEnabled(True)
        self.frame_list.setEnabled(True)
        self.process_actions.setEnabled(True)
        self.postprocess.setEnabled(True)
        self.animation_button.setEnabled(True)
        self.pick_button.setEnabled(True)
        self.progress.hide()
        self.cancel_button.hide()
        self.statusBar().showMessage(error or self.say("Ready", "就绪"))
        try:
            if kind in ("pipeline", "frame"):
                self.session.save()  # Persist valid completed portions even after cancellation.
                self.refresh_stages()
            if error:
                if kind == "preview":
                    self.statusBar().showMessage(error)
                else:
                    self.fail(error)
            elif kind == "preview":
                if self.preview_revision == self.revision:
                    self.images = result
                    self.display_images()
            elif kind == "create":
                self.open_project(result["id"])
                return
            elif kind == "export" or kind.startswith("tool_"):
                self.open_output(result)
            if kind in ("pipeline", "frame", "trim", "align"):
                self.invalidate_display()
                if not error and kind in ("trim", "align"):
                    self.right_source.setCurrentIndex(self.right_source.findData("final"))
                self.preview_pending = True
        except Exception as failure:
            self.fail(failure)
        if self.preview_pending:
            self.request_preview()

    def create_project(self, kind):
        if not self.ready():
            return
        dialog = CreateDialog(self, kind)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        request = dialog.request
        def create():
            common = dict(name=request["name"], target_mode=request["target_mode"], custom_color=request["custom_color"])
            if kind == "video":
                return self.session.manager.create_video_project(request["source"], frame_interval=request["frame_interval"], **common)
            return self.session.manager.create_project(request["source"], rows=request.get("rows", 1), cols=request.get("cols", 1), **common)
        self.start_job("create", create)

    def process(self, all_frames):
        if not self.ready() or not self.session.project:
            return
        if not all_frames:
            self.session.apply_params(self.editor.collect(), frame_only=True)
            self.load_editor()
        self.invalidate_display()
        worker = PipelineWorker(self.session.project, self.session.directory, self.jobs.events) if all_frames else PipelineFrameWorker(
            self.session.project, self.session.directory, self.session.frame_name, self.jobs.events)
        self.start_job("pipeline" if all_frames else "frame", worker=worker)

    def postprocess_dialog(self, operation):
        if not self.ready():
            return
        dialog = PostprocessDialog(self, operation)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.start_job(operation, lambda: getattr(self.session, operation)(*dialog.request))

    def export_result(self):
        if not self.ready():
            return
        filename = "sheet_transparent.png"
        if self.session.project.get("project_type") != "video":
            filename, accepted = QInputDialog.getText(self, self.t("tools.export"), self.say("PNG filename", "PNG 文件名"), text=filename)
            if not accepted:
                return
        target = self.session.directory / "exports" / ("final_frames" if self.session.project.get("project_type") == "video" else filename)
        if target.exists() and not self.confirm(self.say("Replace the existing output?\n", "替换已有输出？\n") + str(target)):
            return
        self.start_job("export", lambda: self.session.export(filename))

    def open_output(self, directory):
        path = Path(directory)
        if not path.is_dir():
            raise FileNotFoundError(str(path))
        self.statusBar().showMessage(self.say("Saved: ", "已保存：") + str(path))
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve()))):
            self.fail(self.say("Saved successfully, but the folder could not be opened:\n", "保存成功，但无法自动打开文件夹：\n") + str(path))

    def run_tool(self, kind):
        if not self.ready():
            return
        dialog = ToolDialog(self, kind)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        request = dialog.request.copy()
        if kind == "video":
            request["output_dir"] = unique_output_dir(request["output_dir"])
        def execute():
            if kind == "video":
                extract_video_range(**request, cancelled=self.jobs.cancel_event.is_set,
                                    progress=lambda saved, total: self.jobs.events.put({"type": "progress", "percent": saved * 100 / max(1, total)}))
                return request["output_dir"]
            if kind == "compose":
                export_sprite_sheet(**request)
            else:
                normalize_equal_grid(**request)
            return request["output_path"].parent
        self.start_job("tool_" + kind, execute)

    def preset(self, save):
        if not self.flush_params():
            return
        chooser = QFileDialog.getSaveFileName if save else QFileDialog.getOpenFileName
        path, _ = chooser(self, self.t("preset.save" if save else "preset.load"), str(self.root / "presets"), "JSON (*.json)")
        if path:
            try:
                if save:
                    save_preset(Path(path), self.editor.collect())
                else:
                    self.editor.load(load_preset(Path(path)))
                    self.parameters_changed()
            except Exception as error:
                self.fail(error)

    def animate(self):
        if self.workspace_stack.currentWidget() is self.animation or self.preview_stack.currentIndex() == 1:
            self.stop_animation()
        elif self.ready() and self.session.project:
            self.pick_button.setChecked(False)
            self.pick_button.setEnabled(False)
            self.preview_stack.setCurrentIndex(1)
            self.animation_button.setText(self.say("■ Stop preview", "■ 停止预览"))
            self.animation.activate(self.right_source.currentData())

    def fit_preview(self):
        canvas = self.animation.canvas if self.workspace_stack.currentWidget() is self.animation or self.preview_stack.currentIndex() == 1 else self.left
        canvas.fit()

    def toggle_window_playback(self):
        if self.workspace_stack.currentWidget() is self.animation:
            self.restore_inline_playback()
        elif not self.jobs.busy and self.preview_stack.currentWidget() is self.animation:
            self.preview_stack.removeWidget(self.animation)
            self.workspace_stack.addWidget(self.animation)
            self.workspace_stack.setCurrentWidget(self.animation)
            self.animation.set_window_playback(True)
            self.statusBar().hide()

    def restore_inline_playback(self):
        if self.workspace_stack.currentWidget() is not self.animation:
            return
        self.workspace_stack.setCurrentIndex(0)
        self.workspace_stack.removeWidget(self.animation)
        self.preview_stack.addWidget(self.animation)
        self.preview_stack.setCurrentWidget(self.animation)
        self.animation.set_window_playback(False)
        self.statusBar().show()

    def exit_animation_view(self):
        if self.workspace_stack.currentWidget() is self.animation:
            self.restore_inline_playback()
        else:
            self.stop_animation()

    def stop_animation(self):
        self.restore_inline_playback()
        self.animation.cleanup()
        self.preview_stack.setCurrentIndex(0)
        self.animation_button.setText(self.say("▶ Play preview", "▶ 播放预览"))
        self.pick_button.setEnabled(not self.jobs.busy or self.jobs.kind == "preview")

    def escape_preview(self):
        self.pick_button.setChecked(False)
        self.exit_animation_view()

    def change_theme(self, material):
        self.material = material
        apply_theme(QApplication.instance(), material)

    def change_language(self):
        code = self.language.currentData()
        if not self.ready():
            self.language.blockSignals(True)
            self.language.setCurrentIndex(self.language.findData(self.i18n.locale))
            self.language.blockSignals(False)
            return
        was_open = self.pages.currentIndex() == 1
        self.stop_animation()
        self.i18n.set_locale(code)
        self.build_ui()
        self.refresh_projects()
        if was_open:
            self.populate_project()
            self.display_images()

    def change_backend(self):
        if not self.ready():
            return
        requested = self.backend.currentData()
        selected = configure_backend(requested)
        save_backend_preference(self.root, selected)
        self.backend.blockSignals(True)
        self.backend.setCurrentIndex(self.backend.findData(selected))
        self.backend.blockSignals(False)
        if selected != requested:
            self.fail(self.say("OpenCL GPU unavailable; CPU remains active.", "OpenCL GPU 当前不可用，继续使用 CPU。"))
        if self.session.project:
            self.invalidate_display()
            self.request_preview()

    def closeEvent(self, event):
        if self.jobs.busy:
            self.jobs.cancel()
            self.statusBar().showMessage(self.say("Waiting for work to finish. Close again when ready.", "正在等待后台任务结束，就绪后请再次关闭。"))
            event.ignore()
        elif not self.flush_params():
            event.ignore()
        else:
            self.stop_animation()
            event.accept()


def run(root):
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    window = Window(root)
    window.show()
    return app.exec()
