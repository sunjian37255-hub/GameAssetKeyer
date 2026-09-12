from __future__ import annotations

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0

import os
import queue
import tkinter as tk
from copy import deepcopy
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from PIL import Image

from .align_utils import align_frames
from .animation_preview import (
    AnimationPreviewError,
    AnimationSource,
    PreviewFrameCache,
    fps_interval_ms,
    next_frame_index,
    read_frame,
    resolve_animation_source,
    validate_fps,
)
from .branding import APP_NAME
from .color_key_processor import DEFAULT_PARAMS
from .compute_backend import (
    CPU,
    GPU,
    configure_backend,
    current_backend,
    gpu_available,
    initialize_backend,
    is_frozen_build,
    opencl_device_name,
    save_backend_preference,
)
from .equal_grid_utils import normalize_equal_grid
from .frame_sequence_exporter import export_png_frame_sequence
from .final_result import (
    resolve_final_result_source,
    resolve_pipeline_result_source,
    resolve_pre_alignment_source,
)
from .i18n import I18n
from .pipeline import (
    add_stage,
    delete_stage,
    duplicate_stage,
    effective_stage_params,
    ensure_pipeline,
    move_stage,
    process_pipeline_image,
    clear_frame_params,
    set_frame_params,
    set_stage_enabled,
    update_stage,
)
from .preset_manager import ensure_default_presets, load_preset, save_preset
from .project_manager import ProjectManager
from .sheet_exporter import export_sheet
from .trim_utils import trim_frames
from .ui.create_project_dialog import CreateProjectDialog
from .ui.equal_grid_dialog import EqualGridDialog
from .ui.frame_sequence_composer_dialog import FrameSequenceComposerDialog
from .ui.project_name_dialog import ProjectNameDialog
from .ui.video_frame_extractor_dialog import VideoFrameExtractorDialog
from .ui.theme import (
    ACCENT,
    ACCENT_HOVER,
    BG_DEFAULT,
    BG_CARD,
    BG_INPUT,
    BG_PANEL,
    BG_ROOT,
    DISABLED_BG,
    DISABLED_TEXT,
    TEXT_MUTED,
    TEXT_ON_ACCENT,
    TEXT_PRIMARY,
)
from .ui.widgets import ImageCanvas, ScrollableFrame
from .workers import PipelineFrameWorker, PipelineWorker

MODE_KEYS = ("green", "black", "white", "magenta", "custom")
LANGUAGE_NAMES = {"zh_CN": "简体中文", "en_US": "English"}


class GameAssetKeyerApp:
    def __init__(self, app_root: Path):
        self.app_root = app_root
        self.i18n = I18n(app_root)
        self.compute_backend = initialize_backend(app_root)
        self.pm = ProjectManager(app_root)
        self.presets_dir = app_root / "presets"
        ensure_default_presets(self.presets_dir)
        self.root = tk.Tk()
        self.root.title(APP_NAME)
        self.root.geometry("1360x820")
        self.root.minsize(960, 640)
        self.current_project_id: str | None = None
        self.current_project: dict = {}
        self.current_frame_index = 1
        self.selected_stage_index = 0
        self.worker: PipelineWorker | None = None
        self.worker_events: queue.Queue[dict] = queue.Queue()
        self.preview_images: dict[str, Image.Image] = {}
        self.current_view = "result"
        self._animation_playing = False
        self._animation_after_id: str | None = None
        self._animation_frame_index = 0
        self._animation_source: AnimationSource | None = None
        self._animation_restore_frame = 1
        self._animation_restore_view = "result"
        self._animation_restore_project_id: str | None = None
        self._animation_cache = PreviewFrameCache(max_items=32)
        self._stage_loaded = False
        self._eyedropper_active = False
        self._configure_style()
        self._create_variables()
        self._build_shell()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.bind("<Escape>", self.cancel_eyedropper, add="+")
        self.show_home()

    def run(self) -> None:
        self.root.mainloop()

    def _configure_style(self) -> None:
        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        self.root.configure(background=BG_ROOT)
        style.configure(".", background=BG_DEFAULT, foreground=TEXT_PRIMARY, fieldbackground=BG_INPUT, font=("Segoe UI", 10))
        style.configure("TFrame", background=BG_DEFAULT)
        style.configure("Panel.TFrame", background=BG_PANEL)
        style.configure("Card.TFrame", background=BG_CARD, relief="flat")
        style.configure("TLabel", background=BG_DEFAULT, foreground=TEXT_PRIMARY)
        style.configure("Muted.TLabel", foreground=TEXT_MUTED)
        style.configure("Title.TLabel", font=("Segoe UI Semibold", 18))
        style.configure("Section.TLabel", font=("Segoe UI Semibold", 11))
        style.configure("TButton", padding=(10, 7))
        style.configure("Primary.TButton", background=ACCENT, foreground=TEXT_ON_ACCENT)
        style.map("Primary.TButton", background=[("active", ACCENT_HOVER), ("disabled", DISABLED_BG)], foreground=[("disabled", DISABLED_TEXT)])
        style.configure("Stage.TButton", anchor="w", padding=(10, 8))
        style.configure("Selected.Stage.TButton", background=ACCENT, foreground=TEXT_ON_ACCENT, anchor="w", padding=(10, 8))
        style.configure("Disabled.Stage.TButton", background=BG_CARD, foreground=DISABLED_TEXT, anchor="w", padding=(10, 8))
        style.map("Disabled.Stage.TButton", foreground=[("active", DISABLED_TEXT), ("disabled", DISABLED_TEXT)])
        style.configure("Treeview", background=BG_INPUT, fieldbackground=BG_INPUT, foreground=TEXT_PRIMARY, rowheight=28)
        style.configure("TNotebook", background=BG_ROOT)
        style.configure("TProgressbar", background=ACCENT)

    def _create_variables(self) -> None:
        self.status_var = tk.StringVar(value=self.t("status.ready"))
        self.progress_text_var = tk.StringVar(value="")
        self.progress_var = tk.DoubleVar(value=0)
        self.frame_override_var = tk.StringVar(value="")
        self.mode_var = tk.StringVar(value=self.t("mode.black"))
        self.custom_color_var = tk.StringVar(value="#000000")
        self.operation_var = tk.StringVar(value="key")
        self.despill_strength_var = tk.DoubleVar(value=0.8)
        self.despill_width_var = tk.IntVar(value=3)
        self.despill_tolerance_var = tk.DoubleVar(value=0.35)
        self.intensity_var = tk.IntVar(value=3)
        self.intensity_label_var = tk.StringVar(value=self.t("intensity.black.3"))
        self.bg_threshold_var = tk.DoubleVar(value=0.40)
        self.fg_threshold_var = tk.DoubleVar(value=0.76)
        self.feather_var = tk.DoubleVar(value=1.5)
        self.edge_erode_var = tk.IntVar(value=0)
        self.min_hole_var = tk.IntVar(value=4)
        self.alpha_gamma_var = tk.DoubleVar(value=1.0)
        self.saturation_var = tk.DoubleVar(value=0.35)
        self.output_alpha_var = tk.DoubleVar(value=1.0)
        self.keep_sparks_var = tk.BooleanVar(value=True)
        self.enable_hole_var = tk.BooleanVar(value=True)
        self.left_view_var = tk.StringVar(value="input")
        self.right_view_var = tk.StringVar(value="result")
        self.animation_fps_var = tk.StringVar(value="12")
        self.compute_backend_var = tk.StringVar(value="")
        self._create_dialog: CreateProjectDialog | None = None

    def _build_shell(self) -> None:
        self.header = ttk.Frame(self.root, padding=(16, 10), style="Panel.TFrame")
        self.header.pack(fill="x")
        ttk.Label(self.header, text=APP_NAME, style="Title.TLabel").pack(side="left")
        ttk.Button(self.header, text=self.t("nav.home"), command=self.show_home).pack(side="right", padx=(8, 0))
        ttk.Label(self.header, text=self.t("language.label")).pack(side="right", padx=(8, 4))
        self.language_combo = ttk.Combobox(self.header, values=list(LANGUAGE_NAMES.values()), state="readonly", width=12)
        self.language_combo.set(LANGUAGE_NAMES[self.i18n.locale])
        self.language_combo.pack(side="right")
        self.language_combo.bind("<<ComboboxSelected>>", self.on_language_change)
        self.page = ttk.Frame(self.root, style="Panel.TFrame")
        self.page.pack(fill="both", expand=True)
        self.footer = ttk.Frame(self.root, padding=(12, 6), style="Panel.TFrame")
        self.footer.pack(fill="x")
        ttk.Label(self.footer, textvariable=self.status_var, style="Muted.TLabel").pack(side="left")
        ttk.Label(self.footer, textvariable=self.progress_text_var).pack(side="right")

    def t(self, key: str, **values: object) -> str:
        return self.i18n.tr(key, **values)

    def mode_labels(self) -> dict[str, str]:
        return {key: self.t(f"mode.{key}") for key in MODE_KEYS}

    def mode_key(self) -> str:
        current = self.mode_var.get()
        return next((key for key, label in self.mode_labels().items() if label == current), "black")

    def on_language_change(self, _event=None) -> None:
        self.stop_animation()
        selected = next((code for code, name in LANGUAGE_NAMES.items() if name == self.language_combo.get()), "en_US")
        if selected == self.i18n.locale:
            return
        if self.current_project:
            self.save_selected_stage(silent=True)
        self.i18n.set_locale(selected)
        for widget in (self.header, self.page, self.footer):
            widget.destroy()
        self._build_shell()
        if self.current_project_id:
            stage_index = self.selected_stage_index
            frame_index = self.current_frame_index
            self._stage_loaded = False
            self.build_workbench()
            self.refresh_frame_list()
            self.current_frame_index = min(frame_index, max(1, self.frame_listbox.size()))
            if self.frame_listbox.size():
                self.frame_listbox.selection_clear(0, "end")
                self.frame_listbox.selection_set(self.current_frame_index - 1)
            self.refresh_stage_list()
            self.select_stage(min(stage_index, len(ensure_pipeline(self.current_project)["stages"]) - 1))
        else:
            self.show_home()
        self.status_var.set(self.t("status.ready"))

    def _clear_page(self) -> None:
        self.stop_animation()
        self.cancel_eyedropper(update_status=False)
        for child in self.page.winfo_children():
            child.destroy()

    def show_home(self) -> None:
        self._clear_page()
        home = ttk.Frame(self.page, padding=28, style="Panel.TFrame")
        home.pack(fill="both", expand=True)
        ttk.Label(home, text=self.t("home.title"), style="Title.TLabel").pack(anchor="w")
        ttk.Label(home, text=self.t("home.subtitle"), style="Muted.TLabel").pack(anchor="w", pady=(4, 10))
        backend_bar = ttk.Frame(home, style="Panel.TFrame")
        backend_bar.pack(fill="x", pady=(0, 18))
        ttk.Label(backend_bar, text=self.t("compute.label"), style="Section.TLabel").pack(side="left")
        if is_frozen_build():
            ttk.Label(backend_bar, text=self.t("compute.cpu_locked"), style="Muted.TLabel").pack(side="left", padx=(8, 0))
        else:
            labels = [self.t("compute.cpu"), self.t("compute.gpu")]
            self.compute_backend_var.set(self.t(f"compute.{current_backend()}"))
            self.compute_backend_combo = ttk.Combobox(
                backend_bar,
                textvariable=self.compute_backend_var,
                values=labels,
                state="readonly",
                width=18,
            )
            self.compute_backend_combo.pack(side="left", padx=(8, 10))
            self.compute_backend_combo.bind("<<ComboboxSelected>>", self.on_compute_backend_change)
            detail_key = "compute.gpu_available" if gpu_available() else "compute.gpu_unavailable"
            device = opencl_device_name() or "OpenCL"
            ttk.Label(backend_bar, text=self.t(detail_key, device=device), style="Muted.TLabel").pack(side="left")
        launch = ttk.Frame(home, style="Panel.TFrame")
        launch.pack(fill="x")
        for title, subtitle, command in [
            (self.t("home.image"), self.t("home.image_subtitle"), self.create_image_project),
            (self.t("home.sheet"), self.t("home.sheet_subtitle"), self.create_sheet_project),
            (self.t("home.video"), self.t("home.video_subtitle"), self.create_video_project),
        ]:
            card = ttk.Frame(launch, padding=18, style="Card.TFrame")
            card.pack(side="left", fill="both", expand=True, padx=(0, 12))
            ttk.Label(card, text=title, style="Section.TLabel").pack(anchor="w")
            ttk.Label(card, text=subtitle, style="Muted.TLabel").pack(anchor="w", pady=(4, 16))
            ttk.Button(card, text=self.t("home.start"), style="Primary.TButton", command=command).pack(anchor="w")
        standalone = ttk.LabelFrame(home, text=self.t("home.standalone_tools"), padding=12)
        standalone.pack(fill="x", pady=(18, 0))
        standalone.columnconfigure(0, weight=1, uniform="standalone")
        standalone.columnconfigure(1, weight=1, uniform="standalone")
        standalone.columnconfigure(2, weight=1, uniform="standalone")
        for column, title_key, subtitle_key, command in (
            (0, "tools.equal_grid", "home.equal_grid_subtitle", self.run_equal_grid),
            (1, "tools.sequence_composer", "home.sequence_composer_subtitle", self.run_sequence_composer),
            (2, "tools.video_frame_extractor", "home.video_extractor_subtitle", self.run_video_frame_extractor),
        ):
            card = ttk.Frame(standalone, padding=12, style="Card.TFrame")
            card.grid(row=0, column=column, sticky="nsew", padx=(0, 6) if column == 0 else ((6, 0) if column == 2 else 6))
            card.columnconfigure(0, weight=1)
            ttk.Label(card, text=self.t(title_key), style="Section.TLabel").grid(row=0, column=0, sticky="w")
            ttk.Label(card, text=self.t(subtitle_key), style="Muted.TLabel", wraplength=360).grid(row=1, column=0, sticky="w", pady=(4, 12))
            ttk.Button(card, text=self.t("home.start"), command=command).grid(row=0, column=1, rowspan=2, sticky="e", padx=(12, 0))
        recent = ttk.LabelFrame(home, text=self.t("recent.title"), padding=12)
        recent.pack(fill="both", expand=True, pady=(18, 0))
        self.recent_tree = ttk.Treeview(recent, columns=("type", "frames"), show="tree headings")
        self.recent_tree.heading("#0", text=self.t("recent.project"))
        self.recent_tree.heading("type", text=self.t("recent.type"))
        self.recent_tree.heading("frames", text=self.t("recent.frames"))
        self.recent_tree.column("#0", width=360)
        self.recent_tree.column("type", width=120)
        self.recent_tree.column("frames", width=80)
        self.recent_tree.pack(fill="both", expand=True)
        self.recent_tree.bind("<Double-1>", lambda _event: self.open_recent_project())
        self.recent_tree.bind("<Button-3>", self.show_recent_project_menu)
        self.recent_project_menu = tk.Menu(
            self.recent_tree,
            tearoff=False,
            background=BG_DEFAULT,
            foreground=TEXT_PRIMARY,
            activebackground=ACCENT,
            activeforeground=TEXT_ON_ACCENT,
        )
        self.recent_project_menu.add_command(label=self.t("project.menu.open"), command=self.open_recent_project)
        self.recent_project_menu.add_command(label=self.t("project.menu.rename"), command=self.rename_recent_project)
        self.recent_project_menu.add_command(label=self.t("project.menu.delete"), command=self.delete_recent_project)
        for project in self.pm.list_projects():
            project_type = self.t(f"type.{project['project_type']}")
            self.recent_tree.insert("", "end", iid=project["id"], text=project["name"], values=(project_type, project.get("frame_count", project.get("rows", 0) * project.get("cols", 0))))

    def on_compute_backend_change(self, _event=None) -> None:
        if is_frozen_build():
            self.compute_backend = configure_backend(CPU)
            return
        requested = GPU if self.compute_backend_var.get() == self.t("compute.gpu") else CPU
        if self.worker is not None and self.worker.is_alive():
            self.compute_backend_var.set(self.t(f"compute.{current_backend()}"))
            self.status_var.set(self.t("status.compute_busy"))
            return
        selected = configure_backend(requested)
        self.compute_backend = selected
        self.compute_backend_var.set(self.t(f"compute.{selected}"))
        save_backend_preference(self.app_root, selected)
        if requested == GPU and selected != GPU:
            self.status_var.set(self.t("status.compute_unavailable"))
        else:
            self.status_var.set(self.t("status.compute_changed", backend=self.t(f"compute.{selected}")))

    def create_image_project(self) -> None:
        self._show_create_dialog("image")

    def create_sheet_project(self) -> None:
        self._show_create_dialog("sheet")

    def create_video_project(self) -> None:
        self._show_create_dialog("video")

    def _show_create_dialog(self, kind: str) -> None:
        if self._create_dialog is not None and self._create_dialog.window.winfo_exists():
            self._create_dialog.window.lift()
            self._create_dialog.window.focus_force()
            return
        dialog = CreateProjectDialog(self.root, kind, self.t, self.mode_labels())
        self._create_dialog = dialog
        try:
            request = dialog.show()
        finally:
            self._create_dialog = None
        if request is not None:
            self._create_project_from_request(request)

    def _create_project_from_request(self, request: dict[str, object]) -> None:
        try:
            source = Path(request["source"])
            name = str(request["name"])
            target_mode = str(request["target_mode"])
            custom_color = str(request["custom_color"])
            if request["kind"] == "video":
                project = self.pm.create_video_project(source, name, int(request["frame_interval"]), target_mode, custom_color)
            else:
                rows = int(request.get("rows", 1))
                cols = int(request.get("cols", 1))
                project = self.pm.create_project(source, name, rows, cols, target_mode, custom_color)
            self.load_project(project["id"])
        except Exception as exc:
            messagebox.showerror(self.t("error.create_title"), str(exc), parent=self.root)

    def open_recent_project(self) -> None:
        selected = self.recent_tree.selection()
        if selected:
            self.load_project(selected[0])

    def show_recent_project_menu(self, event) -> None:
        project_id = self.recent_tree.identify_row(event.y)
        if not project_id:
            return
        self.recent_tree.selection_set(project_id)
        self.recent_tree.focus(project_id)
        try:
            self.recent_project_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.recent_project_menu.grab_release()

    def rename_recent_project(self) -> None:
        selected = self.recent_tree.selection()
        if not selected:
            return
        project_id = selected[0]
        project = self.pm.load_project(project_id)
        new_name = ProjectNameDialog(self.root, project.get("name", project_id), self.t).show()
        if new_name is None:
            return
        updated = self.pm.rename_project(project_id, new_name)
        if self.current_project_id == project_id:
            self.current_project = updated
        self.show_home()
        self.status_var.set(self.t("status.project_renamed", name=new_name))

    def delete_recent_project(self) -> None:
        selected = self.recent_tree.selection()
        if not selected:
            return
        project_id = selected[0]
        project = self.pm.load_project(project_id)
        if not messagebox.askyesno(
            self.t("project.delete.title"),
            self.t("project.delete.confirm", name=project.get("name", project_id)),
            parent=self.root,
        ):
            return
        self.pm.delete_project(project_id)
        if self.current_project_id == project_id:
            self.current_project_id = None
            self.current_project = {}
        self.show_home()
        self.status_var.set(self.t("status.project_deleted", name=project.get("name", project_id)))

    def load_project(self, project_id: str) -> None:
        self.stop_animation()
        self.current_project_id = project_id
        self.current_project = self.pm.load_project(project_id)
        ensure_pipeline(self.current_project)
        self.current_frame_index = 1
        self.selected_stage_index = 0
        self._stage_loaded = False
        self.build_workbench()
        self.refresh_frame_list()
        self.refresh_stage_list()
        self.select_stage(0)
        self.refresh_preview_images()
        self.status_var.set(self.t("status.opened", name=self.current_project.get("name", project_id)))

    def build_workbench(self) -> None:
        self.stop_animation()
        self._clear_page()
        outer = ttk.Frame(self.page, style="Panel.TFrame")
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(0, weight=1)
        workspace = ttk.Frame(outer, style="Panel.TFrame")
        workspace.grid(row=0, column=0, sticky="nsew")
        workspace.columnconfigure(0, minsize=210)
        workspace.columnconfigure(1, weight=1, minsize=320)
        workspace.columnconfigure(2, minsize=350)
        workspace.rowconfigure(0, weight=1)
        left = ttk.Frame(workspace, padding=10, style="Panel.TFrame", width=210)
        center = ttk.Frame(workspace, padding=10, style="Panel.TFrame")
        right = ttk.Frame(workspace, padding=10, style="Panel.TFrame", width=350)
        left.grid(row=0, column=0, sticky="nsew")
        center.grid(row=0, column=1, sticky="nsew")
        right.grid(row=0, column=2, sticky="nsew")
        left.grid_propagate(False)
        right.grid_propagate(False)
        self._build_left_panel(left)
        self._build_preview_panel(center)
        self._build_pipeline_panel(right)
        self._build_tool_bar(outer).grid(row=1, column=0, sticky="ew")

    def _build_left_panel(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text=self.current_project.get("name", self.t("project.fallback")), style="Section.TLabel").pack(anchor="w")
        ttk.Label(parent, text=self.t("project.frames"), style="Muted.TLabel").pack(anchor="w", pady=(2, 8))
        frame_box = ttk.Frame(parent)
        frame_box.pack(fill="both", expand=True)
        self.frame_listbox = tk.Listbox(frame_box, background=BG_INPUT, foreground=TEXT_PRIMARY, selectbackground=ACCENT, borderwidth=0, highlightthickness=0)
        scrollbar = ttk.Scrollbar(frame_box, orient="vertical", command=self.frame_listbox.yview)
        self.frame_listbox.configure(yscrollcommand=scrollbar.set)
        self.frame_listbox.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.frame_listbox.bind("<<ListboxSelect>>", self.on_frame_select)
        ttk.Button(parent, text=self.t("project.open_folder"), command=self.open_project_folder).pack(fill="x", pady=(8, 0))

    def _build_preview_panel(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1, uniform="preview")
        parent.columnconfigure(1, weight=1, uniform="preview")
        parent.rowconfigure(0, weight=1)
        self.view_buttons: dict[str, ttk.Radiobutton] = {}
        left_panel = self._build_preview_side(parent, 0, ("original", "input"), self.left_view_var)
        right_panel = self._build_preview_side(parent, 1, ("result", "final"), self.right_view_var)
        self.left_preview_canvas = ImageCanvas(left_panel)
        self.left_preview_canvas.grid(row=1, column=0, sticky="nsew")
        self.right_preview_canvas = ImageCanvas(right_panel)
        self.right_preview_canvas.grid(row=2, column=0, sticky="nsew")
        # Preserve the public attribute used by the eyedropper and existing integrations.
        self.preview_canvas = self.left_preview_canvas

    def _build_preview_side(self, parent: ttk.Frame, column: int, keys: tuple[str, str], variable: tk.StringVar) -> ttk.Frame:
        panel = ttk.Frame(parent, style="Panel.TFrame")
        panel.grid(row=0, column=column, sticky="nsew", padx=(0, 4) if column == 0 else (4, 0))
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(1 if column == 0 else 2, weight=1)
        toolbar = ttk.Frame(panel)
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        for button_column, key in enumerate(keys):
            toolbar.columnconfigure(button_column, weight=1, uniform="preview_button")
            button = ttk.Radiobutton(
                toolbar,
                text=self.t(f"view.{key}"),
                variable=variable,
                value=key,
                command=lambda selected=key: self.show_preview_view(selected),
                style="Toolbutton",
            )
            button.grid(row=0, column=button_column, sticky="ew", padx=(0, 4) if button_column == 0 else 0)
            self.view_buttons[key] = button
        if column == 1:
            controls = ttk.Frame(panel)
            controls.grid(row=1, column=0, sticky="ew", pady=(0, 8))
            controls.columnconfigure(0, weight=1)
            controls.columnconfigure(1, weight=1)
            controls.columnconfigure(2, weight=0)
            controls.columnconfigure(3, weight=0)
            controls.columnconfigure(4, weight=0)
            self.animation_play_button = ttk.Button(controls, text=self.t("animation.play"), command=self.play_animation)
            self.animation_play_button.grid(row=0, column=0, sticky="ew", padx=(0, 4))
            self.animation_stop_button = ttk.Button(controls, text=self.t("animation.stop"), command=self.stop_animation, state="disabled")
            self.animation_stop_button.grid(row=0, column=1, sticky="ew", padx=(0, 8))
            ttk.Label(controls, text=self.t("animation.fps")).grid(row=0, column=2, sticky="e", padx=(0, 4))
            self.animation_fps_spinbox = ttk.Spinbox(controls, from_=1, to=60, width=4, textvariable=self.animation_fps_var)
            self.animation_fps_spinbox.grid(row=0, column=3, sticky="e")
            ttk.Label(controls, text=self.t("animation.fps_suffix")).grid(row=0, column=4, sticky="w", padx=(3, 0))
        return panel

    def _build_pipeline_panel(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text=self.t("pipeline.title"), style="Section.TLabel").pack(anchor="w")
        ttk.Label(parent, text=self.t("pipeline.subtitle"), style="Muted.TLabel").pack(anchor="w", pady=(0, 8))
        self.pipeline_scroll = ScrollableFrame(parent, height=210)
        self.pipeline_scroll.pack(fill="both", expand=True)
        self.stage_list_frame = ttk.Frame(self.pipeline_scroll.content)
        self.stage_list_frame.pack(fill="x")
        stage_actions = ttk.Frame(self.pipeline_scroll.content)
        stage_actions.pack(fill="x", pady=6)
        for text, command in [("+", self.add_stage_ui), (self.t("action.duplicate"), self.duplicate_stage_ui), (self.t("action.delete"), self.delete_stage_ui), ("↑", lambda: self.move_stage_ui(-1)), ("↓", lambda: self.move_stage_ui(1))]:
            ttk.Button(stage_actions, text=text, command=command).pack(side="left", padx=(0, 3))
        ttk.Button(self.pipeline_scroll.content, text=self.t("despill.add"), command=self.add_despill_stage_ui).pack(fill="x", pady=(4, 0))
        self._build_stage_editor(self.pipeline_scroll.content)

    def _build_stage_editor(self, parent: ttk.Frame) -> None:
        editor = ttk.LabelFrame(parent, text=self.t("editor.title"), padding=10)
        editor.pack(fill="x", pady=(6, 0))
        ttk.Label(editor, text=self.t("editor.target_color")).grid(row=0, column=0, sticky="w")
        mode = ttk.Combobox(editor, textvariable=self.mode_var, values=list(self.mode_labels().values()), state="readonly")
        mode.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(2, 6))
        mode.bind("<<ComboboxSelected>>", lambda _event: self.update_intensity_label())
        ttk.Entry(editor, textvariable=self.custom_color_var).grid(row=2, column=0, sticky="ew")
        ttk.Button(editor, text=self.t("editor.eyedropper"), command=self.start_eyedropper).grid(row=2, column=1, padx=(4, 0))
        ttk.Label(editor, text=self.t("editor.intensity")).grid(row=3, column=0, sticky="w", pady=(8, 0))
        scale = ttk.Scale(editor, from_=1, to=5, variable=self.intensity_var, command=self.on_intensity_change)
        scale.grid(row=4, column=0, columnspan=2, sticky="ew")
        ttk.Label(editor, textvariable=self.intensity_label_var, style="Muted.TLabel").grid(row=5, column=0, columnspan=2, sticky="w")
        self._spin(editor, self.t("param.background_threshold"), self.bg_threshold_var, 0.0, 1.0, 0.01, 6)
        self._spin(editor, self.t("param.foreground_threshold"), self.fg_threshold_var, 0.0, 1.0, 0.01, 7)
        self._spin(editor, self.t("param.feather"), self.feather_var, 0.0, 10.0, 0.1, 8)
        self._spin(editor, self.t("param.edge_erode"), self.edge_erode_var, 0, 8, 1, 9)
        self.advanced_visible = False
        self.advanced_button = ttk.Button(editor, text=self.t("param.advanced_closed"), command=self.toggle_advanced)
        self.advanced_button.grid(row=10, column=0, columnspan=2, sticky="ew", pady=(8, 3))
        self.advanced_frame = ttk.Frame(editor)
        self._spin(self.advanced_frame, self.t("param.min_hole"), self.min_hole_var, 0, 9999, 1, 0)
        self._spin(self.advanced_frame, self.t("param.alpha_gamma"), self.alpha_gamma_var, 0.1, 4.0, 0.1, 1)
        self._spin(self.advanced_frame, self.t("param.saturation_protect"), self.saturation_var, 0.0, 1.0, 0.01, 2)
        self._spin(self.advanced_frame, self.t("param.output_alpha"), self.output_alpha_var, 0.0, 1.0, 0.01, 3)
        ttk.Checkbutton(self.advanced_frame, text=self.t("param.keep_sparks"), variable=self.keep_sparks_var).grid(row=4, column=0, columnspan=2, sticky="w")
        ttk.Checkbutton(self.advanced_frame, text=self.t("param.hole_punch"), variable=self.enable_hole_var).grid(row=5, column=0, columnspan=2, sticky="w")
        editor.columnconfigure(0, weight=1)
        self.cancel_button = ttk.Button(editor, text=self.t("action.cancel"), command=self.cancel_worker, state="disabled")
        ttk.Label(editor, textvariable=self.frame_override_var, style="Muted.TLabel").grid(row=12, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Button(editor, text=self.t("action.preview_stage"), command=self.preview_selected_stage).grid(row=13, column=0, columnspan=2, sticky="ew", pady=(6, 3))
        ttk.Button(editor, text=self.t("action.process_frame"), command=self.process_current_frame_ui).grid(row=14, column=0, columnspan=2, sticky="ew", pady=3)
        ttk.Button(editor, text=self.t("action.clear_frame_override"), command=self.clear_current_frame_override_ui).grid(row=15, column=0, columnspan=2, sticky="ew", pady=3)
        ttk.Button(editor, text=self.t("action.process_all"), style="Primary.TButton", command=self.start_process_all).grid(row=16, column=0, columnspan=2, sticky="ew", pady=3)
        self.cancel_button.grid(row=17, column=0, columnspan=2, sticky="ew", pady=3)
        self.progress_bar = ttk.Progressbar(editor, variable=self.progress_var, maximum=100)
        self.progress_bar.grid(row=18, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        preset_row = ttk.Frame(editor)
        preset_row.grid(row=19, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Button(preset_row, text=self.t("preset.load"), command=self.load_preset_ui).pack(side="left", fill="x", expand=True)
        ttk.Button(preset_row, text=self.t("preset.save"), command=self.save_preset_ui).pack(side="left", fill="x", expand=True, padx=(4, 0))
        self._key_editor_widgets = [widget for widget in editor.winfo_children()
                                    if 3 <= int(widget.grid_info().get("row", -1)) <= 10]
        self.despill_editor = ttk.Frame(editor)
        self._spin(self.despill_editor, self.t("despill.strength"), self.despill_strength_var, 0, 1, 0.05, 0)
        self._spin(self.despill_editor, self.t("despill.width"), self.despill_width_var, 1, 32, 1, 1)
        self._spin(self.despill_editor, self.t("despill.tolerance"), self.despill_tolerance_var, 0.01, 1, 0.05, 2)
        ttk.Label(self.despill_editor, text=self.t("despill.hint"), wraplength=270, style="Muted.TLabel").grid(row=3, column=0, columnspan=2, sticky="ew", pady=6)
        self.refresh_operation_editor()

    def refresh_operation_editor(self) -> None:
        if not hasattr(self, "despill_editor") or not self.despill_editor.winfo_exists():
            return
        despill = self.operation_var.get() == "despill"
        for widget in self._key_editor_widgets:
            widget.grid_remove() if despill else widget.grid()
        if despill:
            self.advanced_frame.grid_remove()
            self.despill_editor.grid(row=3, column=0, columnspan=2, sticky="ew")
        else:
            self.despill_editor.grid_remove()
            if self.advanced_visible:
                self.advanced_frame.grid(row=11, column=0, columnspan=2, sticky="ew")

    def _spin(self, parent, label: str, variable, low, high, increment, row: int) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=(5, 0))
        ttk.Spinbox(parent, from_=low, to=high, increment=increment, textvariable=variable, width=10).grid(row=row, column=1, sticky="e", pady=(5, 0))

    def toggle_advanced(self) -> None:
        self.advanced_visible = not self.advanced_visible
        if self.advanced_visible:
            self.advanced_frame.grid(row=11, column=0, columnspan=2, sticky="ew")
            self.advanced_button.configure(text=self.t("param.advanced_open"))
        else:
            self.advanced_frame.grid_remove()
            self.advanced_button.configure(text=self.t("param.advanced_closed"))

    def _build_tool_bar(self, parent: ttk.Frame) -> ttk.Frame:
        tools = ttk.Frame(parent, padding=(10, 8), style="Panel.TFrame")
        tools.columnconfigure(0, weight=1)
        tools.columnconfigure(1, weight=1)
        export_key = "tools.export_video" if self.current_project.get("project_type") == "video" else "tools.export"
        post_process = ttk.Frame(tools)
        post_process.grid(row=0, column=0, sticky="w", padx=(0, 12))
        ttk.Label(post_process, text=self.t("tools.post_process"), style="Muted.TLabel").pack(side="left", padx=(0, 8))
        for text, command in [(self.t("tools.trim"), self.run_trim), (self.t("tools.align"), self.run_align)]:
            ttk.Button(post_process, text=text, command=command).pack(side="left", padx=(0, 4))
        export = ttk.Frame(tools)
        export.grid(row=0, column=1, sticky="e")
        ttk.Label(export, text=self.t("tools.export_group"), style="Muted.TLabel").pack(side="left", padx=(0, 8))
        ttk.Button(export, text=self.t(export_key), style="Primary.TButton", command=self.run_export).pack(side="left")
        return tools

    def project_path(self) -> Path:
        if not self.current_project_id:
            raise ValueError(self.t("error.no_project"))
        return self.pm.project_path(self.current_project_id)

    def refresh_frame_list(self) -> None:
        self.frame_listbox.delete(0, "end")
        for frame in sorted((self.project_path() / "01_frames_raw").glob("frame_*.png")):
            self.frame_listbox.insert("end", frame.name)
        if self.frame_listbox.size():
            self.frame_listbox.selection_set(0)

    def on_frame_select(self, _event=None) -> None:
        if self._animation_playing:
            self.stop_animation()
        selected = self.frame_listbox.curselection()
        if selected:
            self.cancel_eyedropper(update_status=False)
            self._save_visible_params_for_navigation()
            self.current_frame_index = selected[0] + 1
            stage = ensure_pipeline(self.current_project)["stages"][self.selected_stage_index]
            self.apply_params(effective_stage_params(stage, self.current_raw_frame().name))
            self.update_frame_override_label()
            self.refresh_preview_images()

    def _save_visible_params_for_navigation(self) -> None:
        """Keep unsaved stage defaults or a frame override when changing frames."""
        if not self._stage_loaded or not self.current_project_id:
            return
        stages = ensure_pipeline(self.current_project)["stages"]
        if not 0 <= self.selected_stage_index < len(stages):
            return
        frame_name = self.current_raw_frame().name
        params = self.collect_params()
        if frame_name in stages[self.selected_stage_index]["frame_params"]:
            set_frame_params(self.current_project, self.selected_stage_index, frame_name, params)
        else:
            update_stage(self.current_project, self.selected_stage_index, params)
        self.pm.save_project(self.current_project_id, self.current_project)

    def current_raw_frame(self) -> Path:
        return self.project_path() / "01_frames_raw" / f"frame_{self.current_frame_index:06d}.png"

    def refresh_stage_list(self) -> None:
        for child in self.stage_list_frame.winfo_children():
            child.destroy()
        stages = ensure_pipeline(self.current_project)["stages"]
        self.selected_stage_index = min(self.selected_stage_index, len(stages) - 1)
        for index, stage in enumerate(stages):
            row = ttk.Frame(self.stage_list_frame, style="Card.TFrame", padding=4)
            row.pack(fill="x", pady=2)
            enabled = tk.BooleanVar(value=stage["enabled"])
            ttk.Checkbutton(row, variable=enabled, command=lambda i=index, var=enabled: self.toggle_stage_ui(i, var.get())).pack(side="left")
            mode_key = stage["params"]["target_mode"]
            mode = self.mode_labels().get(mode_key, self.t("mode.custom"))
            if stage["params"].get("operation") == "despill":
                mode = self.t("despill.name") + " · " + mode
            custom = stage["params"]["custom_color"] if mode_key == "custom" else ""
            status = self.t(f"stage.{stage['status']}")
            text = f"{self.t('stage.label', number=index + 1)} · {mode} {custom} · {status}"
            if index == self.selected_stage_index:
                style = "Selected.Stage.TButton"
            elif not stage.get("enabled", True):
                style = "Disabled.Stage.TButton"
            else:
                style = "Stage.TButton"
            ttk.Button(row, text=text, style=style, command=lambda i=index: self.select_stage(i)).pack(side="left", fill="x", expand=True)

    def select_stage(self, index: int) -> None:
        self.stop_animation()
        self.cancel_eyedropper(update_status=False)
        self.selected_stage_index = index
        stage = ensure_pipeline(self.current_project)["stages"][index]
        frame_name = self.current_raw_frame().name if self.current_project_id else None
        self.apply_params(effective_stage_params(stage, frame_name))
        self._stage_loaded = True
        self.update_frame_override_label()
        if hasattr(self, "stage_list_frame"):
            self.refresh_stage_list()
        self.refresh_preview_images()

    def collect_params(self) -> dict:
        return {
            "operation": self.operation_var.get(),
            "despill_strength": float(self.despill_strength_var.get()),
            "despill_width": int(float(self.despill_width_var.get())),
            "despill_tolerance": float(self.despill_tolerance_var.get()),
            "target_mode": self.mode_key(),
            "custom_color": self.custom_color_var.get(),
            "intensity": int(float(self.intensity_var.get())),
            "background_threshold": float(self.bg_threshold_var.get()),
            "foreground_threshold": float(self.fg_threshold_var.get()),
            "feather_radius": float(self.feather_var.get()),
            "edge_erode": int(float(self.edge_erode_var.get())),
            "min_hole_size": int(float(self.min_hole_var.get())),
            "alpha_gamma": float(self.alpha_gamma_var.get()),
            "saturation_protect": float(self.saturation_var.get()),
            "output_alpha": float(self.output_alpha_var.get()),
            "keep_sparks": bool(self.keep_sparks_var.get()),
            "enable_hole_punch": bool(self.enable_hole_var.get()),
        }

    def apply_params(self, params: dict) -> None:
        config = DEFAULT_PARAMS.copy()
        config.update(params)
        self.operation_var.set(config["operation"])
        self.despill_strength_var.set(float(config["despill_strength"]))
        self.despill_width_var.set(int(config["despill_width"]))
        self.despill_tolerance_var.set(float(config["despill_tolerance"]))
        self.refresh_operation_editor()
        self.mode_var.set(self.mode_labels().get(config["target_mode"], self.t("mode.black")))
        self.custom_color_var.set(config["custom_color"])
        self.intensity_var.set(int(config["intensity"]))
        self.bg_threshold_var.set(float(config["background_threshold"]))
        self.fg_threshold_var.set(float(config["foreground_threshold"]))
        self.feather_var.set(float(config["feather_radius"]))
        self.edge_erode_var.set(int(config["edge_erode"]))
        self.min_hole_var.set(int(config["min_hole_size"]))
        self.alpha_gamma_var.set(float(config["alpha_gamma"]))
        self.saturation_var.set(float(config["saturation_protect"]))
        self.output_alpha_var.set(float(config["output_alpha"]))
        self.keep_sparks_var.set(bool(config["keep_sparks"]))
        self.enable_hole_var.set(bool(config["enable_hole_punch"]))
        self.update_intensity_label()

    def save_selected_stage(self, *, silent: bool = False) -> None:
        if not self.current_project:
            return
        stages = ensure_pipeline(self.current_project)["stages"]
        if not 0 <= self.selected_stage_index < len(stages):
            return
        try:
            update_stage(self.current_project, self.selected_stage_index, self.collect_params())
            self.pm.save_project(self.current_project_id, self.current_project)
        except (tk.TclError, ValueError) as exc:
            if not silent:
                messagebox.showerror(self.t("error.params_title"), str(exc), parent=self.root)

    def update_intensity_label(self) -> None:
        mode = self.mode_key()
        index = max(1, min(5, int(float(self.intensity_var.get())))) - 1
        self.intensity_label_var.set(self.t(f"intensity.{mode}.{index + 1}"))

    def on_intensity_change(self, _value: str | None = None) -> None:
        self.update_intensity_label()

    def add_despill_stage_ui(self) -> None:
        self.add_stage_ui("despill")

    def add_stage_ui(self, operation: str = "key") -> None:
        self.stop_animation()
        params = self.collect_params()
        params["operation"] = operation
        if operation == "despill" and params["target_mode"] in {"black", "white"}:
            params.update(target_mode="green", custom_color="#00FF00")
        self.selected_stage_index = add_stage(self.current_project, params)
        self.pm.save_project(self.current_project_id, self.current_project)
        self.refresh_stage_list()
        self.select_stage(self.selected_stage_index)

    def duplicate_stage_ui(self) -> None:
        self.stop_animation()
        self.selected_stage_index = duplicate_stage(self.current_project, self.selected_stage_index)
        self.pm.save_project(self.current_project_id, self.current_project)
        self.refresh_stage_list()
        self.select_stage(self.selected_stage_index)

    def delete_stage_ui(self) -> None:
        self.stop_animation()
        try:
            delete_stage(self.current_project, self.selected_stage_index)
        except ValueError as exc:
            messagebox.showwarning(self.t("error.delete_title"), self.t("error.delete_last_stage"), parent=self.root)
            return
        self.selected_stage_index = max(0, self.selected_stage_index - 1)
        self.pm.save_project(self.current_project_id, self.current_project)
        self.refresh_stage_list()
        self.select_stage(self.selected_stage_index)

    def toggle_stage_ui(self, index: int, enabled: bool) -> None:
        self.stop_animation()
        set_stage_enabled(self.current_project, index, enabled)
        self.pm.save_project(self.current_project_id, self.current_project)
        self.refresh_stage_list()
        self.refresh_preview_images()

    def move_stage_ui(self, offset: int) -> None:
        self.stop_animation()
        self.selected_stage_index = move_stage(self.current_project, self.selected_stage_index, offset)
        self.pm.save_project(self.current_project_id, self.current_project)
        self.refresh_stage_list()
        self.select_stage(self.selected_stage_index)

    def refresh_preview_images(self) -> None:
        raw_path = self.current_raw_frame() if self.current_project_id else None
        if raw_path is None or not raw_path.exists():
            return
        with Image.open(raw_path) as source:
            original = source.convert("RGBA")
        stages = ensure_pipeline(self.current_project)["stages"]
        preview_stages = deepcopy(stages)
        preview_stages[self.selected_stage_index]["frame_params"][raw_path.name] = self.collect_params()
        stage_input = process_pipeline_image(original, preview_stages, self.selected_stage_index - 1, raw_path.name) if self.selected_stage_index > 0 else original.copy()
        stage_result = process_pipeline_image(original, preview_stages, self.selected_stage_index, raw_path.name)
        final = process_pipeline_image(original, preview_stages, frame_name=raw_path.name)
        final_source = resolve_final_result_source(self.current_project, self.project_path())
        if final_source is not None:
            final_path = final_source.frame_path(raw_path.name)
            if final_path.is_file():
                with Image.open(final_path) as processed:
                    final = processed.convert("RGBA")
        self.preview_images = {"original": original, "input": stage_input, "result": stage_result, "final": final}
        self._refresh_preview_canvases()

    def _refresh_preview_canvases(self) -> None:
        if hasattr(self, "left_preview_canvas"):
            self.left_preview_canvas.set_image(self.preview_images.get(self.left_view_var.get()))
        if hasattr(self, "right_preview_canvas") and not self._animation_playing:
            self.right_preview_canvas.set_image(self.preview_images.get(self.right_view_var.get()))

    def _set_animation_controls(self, playing: bool) -> None:
        play_state = "disabled" if playing else "normal"
        stop_state = "normal" if playing else "disabled"
        for name, state in (
            ("animation_play_button", play_state),
            ("animation_stop_button", stop_state),
            ("animation_fps_spinbox", "disabled" if playing else "normal"),
        ):
            widget = getattr(self, name, None)
            if widget is not None:
                try:
                    widget.configure(state=state)
                except tk.TclError:
                    pass

    def _animation_error_text(self, error: Exception) -> str:
        key = getattr(error, "message_key", "error.animation_source")
        try:
            return self.t(key)
        except Exception:
            return str(error)

    def play_animation(self) -> None:
        """Play the current right-side source over the existing Result canvas."""

        if self._animation_playing:
            return
        try:
            fps = validate_fps(self.animation_fps_var.get())
            source_key = "stage_result" if self.right_view_var.get() == "result" else "final_result"
            source = resolve_animation_source(
                self.current_project,
                self.project_path(),
                source_key,
                self.selected_stage_index,
            )
        except (AnimationPreviewError, OSError, ValueError) as exc:
            messagebox.showerror(self.t("error.animation_title"), self._animation_error_text(exc), parent=self.root)
            return

        if not source.frame_names:
            messagebox.showerror(self.t("error.animation_title"), self.t("error.animation_source"), parent=self.root)
            return
        self._animation_restore_frame = self.current_frame_index
        self._animation_restore_view = self.right_view_var.get()
        self._animation_restore_project_id = self.current_project_id
        self._animation_source = source
        self._animation_frame_index = 0
        self._animation_cache.clear()
        self._animation_playing = True
        self._set_animation_controls(True)
        try:
            self._show_animation_frame()
            self._animation_after_id = self.root.after(fps_interval_ms(fps), self._animation_tick)
        except (AnimationPreviewError, OSError, tk.TclError, ValueError) as exc:
            self.stop_animation(error=exc)

    def _show_animation_frame(self) -> None:
        if not self._animation_playing or self._animation_source is None:
            return
        image = read_frame(self._animation_source, self._animation_frame_index, self._animation_cache)
        try:
            self.right_preview_canvas.set_image(image)
        finally:
            image.close()

    def _animation_tick(self) -> None:
        self._animation_after_id = None
        if not self._animation_playing or self._animation_source is None:
            return
        try:
            next_index = next_frame_index(self._animation_frame_index, self._animation_source.frame_count, loop=False)
            if next_index is None:
                self.stop_animation()
                return
            self._animation_frame_index = next_index
            self._show_animation_frame()
            fps = validate_fps(self.animation_fps_var.get())
            self._animation_after_id = self.root.after(fps_interval_ms(fps), self._animation_tick)
        except (AnimationPreviewError, OSError, tk.TclError, ValueError) as exc:
            self.stop_animation(error=exc)

    def stop_animation(self, error: Exception | None = None) -> None:
        """Cancel playback and restore the static frame/view without selection churn."""

        after_id = self._animation_after_id
        self._animation_after_id = None
        if after_id is not None:
            try:
                self.root.after_cancel(after_id)
            except tk.TclError:
                pass
        was_playing = self._animation_playing
        restore_project_id = self._animation_restore_project_id
        restore_frame = self._animation_restore_frame
        restore_view = self._animation_restore_view
        self._animation_playing = False
        self._animation_source = None
        self._animation_frame_index = 0
        self._animation_cache.clear()
        self._set_animation_controls(False)
        if was_playing and self.current_project_id == restore_project_id and self.current_project_id:
            self.current_frame_index = restore_frame
            self.right_view_var.set(restore_view)
            self.current_view = restore_view
            try:
                self.refresh_preview_images()
            except (OSError, tk.TclError, ValueError):
                # A page/project may be in the middle of being destroyed or
                # replaced; the callback is still safely gone.
                pass
        if error is not None:
            messagebox.showerror(self.t("error.animation_title"), self._animation_error_text(error), parent=self.root)

    def close(self) -> None:
        self.stop_animation()
        self.cancel_eyedropper(update_status=False)
        self.cancel_worker()
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def show_preview_view(self, key: str) -> None:
        self.stop_animation()
        self.cancel_eyedropper(update_status=False)
        self.current_view = key
        if key in ("original", "input"):
            self.left_view_var.set(key)
        elif key in ("result", "final"):
            self.right_view_var.set(key)
        self._refresh_preview_canvases()

    def preview_selected_stage(self) -> None:
        self.stop_animation()
        self.refresh_stage_list()
        self.refresh_preview_images()
        self.show_preview_view("result")

    def update_frame_override_label(self) -> None:
        if not self.current_project_id:
            self.frame_override_var.set("")
            return
        stage = ensure_pipeline(self.current_project)["stages"][self.selected_stage_index]
        key = "frame.override" if self.current_raw_frame().name in stage["frame_params"] else "frame.default"
        self.frame_override_var.set(self.t(key))

    def process_current_frame_ui(self) -> None:
        self.stop_animation()
        if self.worker and self.worker.is_alive():
            return
        frame_name = self.current_raw_frame().name
        set_frame_params(self.current_project, self.selected_stage_index, frame_name, self.collect_params())
        self.pm.save_project(self.current_project_id, self.current_project)
        self.update_frame_override_label()
        self.worker_events = queue.Queue()
        self.worker = PipelineFrameWorker(self.current_project, self.project_path(), frame_name, self.worker_events)
        self.progress_var.set(0)
        self.cancel_button.configure(state="normal")
        self.worker.start()
        self.root.after(50, self.poll_worker_events)

    def clear_current_frame_override_ui(self) -> None:
        self.stop_animation()
        frame_name = self.current_raw_frame().name
        clear_frame_params(self.current_project, self.selected_stage_index, frame_name)
        self.pm.save_project(self.current_project_id, self.current_project)
        stage = ensure_pipeline(self.current_project)["stages"][self.selected_stage_index]
        self.apply_params(stage["params"])
        self.update_frame_override_label()
        self.refresh_stage_list()
        self.refresh_preview_images()

    def start_eyedropper(self) -> None:
        if self._eyedropper_active:
            self.cancel_eyedropper()
            return
        canvases = self._preview_canvases()
        if not canvases:
            return
        for canvas in canvases:
            canvas.enable_eyedropper(self._eyedropper_selected, self._eyedropper_missed)
        self._eyedropper_active = True
        self.status_var.set(self.t("status.eyedropper_prompt"))

    def _preview_canvases(self) -> tuple[ImageCanvas, ...]:
        canvases: list[ImageCanvas] = []
        for name in ("left_preview_canvas", "right_preview_canvas"):
            canvas = getattr(self, name, None)
            try:
                if canvas is not None and canvas.winfo_exists():
                    canvases.append(canvas)
            except tk.TclError:
                pass
        return tuple(canvases)

    def cancel_eyedropper(self, _event=None, *, update_status: bool = True):
        was_active = self._eyedropper_active
        for canvas in self._preview_canvases():
            canvas.cancel_eyedropper()
        self._eyedropper_active = False
        if was_active and update_status:
            self.status_var.set(self.t("status.eyedropper_cancelled"))
        return "break" if _event is not None else None

    def _eyedropper_missed(self) -> None:
        if self._eyedropper_active:
            self.status_var.set(self.t("status.eyedropper_outside"))

    def _eyedropper_selected(self, rgb: tuple[int, int, int] | None) -> None:
        self.cancel_eyedropper(update_status=False)
        if rgb is None:
            self.status_var.set(self.t("status.eyedropper_transparent"))
            return
        self.custom_color_var.set("#{:02X}{:02X}{:02X}".format(*rgb))
        self.mode_var.set(self.t("mode.custom"))
        self.refresh_stage_list()
        self.refresh_preview_images()
        self.status_var.set(self.t("status.color_picked", color=self.custom_color_var.get()))

    def start_process_all(self) -> None:
        self.stop_animation()
        if self.worker and self.worker.is_alive():
            return
        self.save_selected_stage()
        self.worker_events = queue.Queue()
        self.worker = PipelineWorker(self.current_project, self.project_path(), self.worker_events)
        self.progress_var.set(0)
        self.cancel_button.configure(state="normal")
        self.worker.start()
        self.root.after(50, self.poll_worker_events)

    def poll_worker_events(self) -> None:
        finished = False
        while True:
            try:
                event = self.worker_events.get_nowait()
            except queue.Empty:
                break
            kind = event["type"]
            if kind == "started":
                self.status_var.set(self.t("status.processing_frame", frame=event.get("frame_name", "")) if event.get("scope") == "frame" else self.t("status.processing"))
            elif kind == "progress":
                self.progress_var.set(event["percent"])
                self.progress_text_var.set(self.t("status.progress", stage=event["stage"], frame=event["frame"], total=event["frame_total"], percent=event["percent"]))
            elif kind == "done":
                self.pm.save_project(self.current_project_id, self.current_project)
                self.status_var.set(self.t("status.frame_done", frame=event.get("frame_name", "")) if event.get("scope") == "frame" else self.t("status.done"))
                self.progress_var.set(100)
                finished = True
            elif kind == "cancelled":
                self.pm.save_project(self.current_project_id, self.current_project)
                self.status_var.set(self.t("status.cancelled"))
                finished = True
            elif kind == "error":
                self.status_var.set(self.t("status.failed"))
                messagebox.showerror(self.t("error.process_title"), event["error"], parent=self.root)
                finished = True
        if finished:
            self.cancel_button.configure(state="disabled")
            self.refresh_stage_list()
            self.refresh_preview_images()
        elif self.worker and self.worker.is_alive():
            self.root.after(50, self.poll_worker_events)

    def cancel_worker(self) -> None:
        if self.worker and self.worker.is_alive():
            self.worker.cancel()
            self.status_var.set(self.t("status.cancelling"))

    def _pipeline_source_dir(self) -> Path:
        source = resolve_pipeline_result_source(self.current_project, self.project_path())
        if source is not None:
            return source.directory
        raise ValueError(self.t("error.run_first"))

    def run_sequence_composer(self) -> None:
        # The composer is a standalone Toplevel workflow; animation playback
        # belongs to the workbench and must not survive a page transition.
        self.stop_animation()
        FrameSequenceComposerDialog(self.root, self.t).show()

    def run_video_frame_extractor(self) -> None:
        self.stop_animation()
        VideoFrameExtractorDialog(self.root, self.t).show()

    def run_equal_grid(self) -> None:
        self.stop_animation()
        request = EqualGridDialog(self.root, self.t).show()
        if request is None:
            return
        try:
            normalize_equal_grid(Path(request["source"]), Path(request["output"]), int(request["rows"]), int(request["cols"]))
            self.status_var.set(self.t("status.equal_grid_done"))
        except Exception as exc:
            messagebox.showerror(self.t("error.equal_grid_title"), str(exc), parent=self.root)

    def run_trim(self) -> None:
        self.stop_animation()
        try:
            source = resolve_pipeline_result_source(self.current_project, self.project_path())
            if source is None:
                raise ValueError(self.t("error.run_first"))
            threshold = simpledialog.askinteger(self.t("dialog.alpha_threshold"), self.t("dialog.alpha_threshold"), minvalue=0, maxvalue=255, initialvalue=8, parent=self.root)
            padding = simpledialog.askinteger(self.t("dialog.padding"), self.t("dialog.padding"), minvalue=0, initialvalue=0, parent=self.root)
            if threshold is None or padding is None:
                return
            metadata = trim_frames(source.directory, self.project_path() / "04_trimmed", threshold, padding, source.signature)
            self.current_project["trim"] = metadata
            self.pm.save_project(self.current_project_id, self.current_project)
            self.status_var.set(self.t("status.trimmed", count=metadata["frame_count"]))
            self.refresh_preview_images()
        except Exception as exc:
            messagebox.showerror(self.t("error.trim_title"), str(exc), parent=self.root)

    def run_align(self) -> None:
        self.stop_animation()
        try:
            source = resolve_pre_alignment_source(self.current_project, self.project_path())
            if source is None:
                raise ValueError(self.t("error.run_first"))
            align_labels = {self.t(f"align.{key}"): key for key in ("none", "center", "bottom_center")}
            selected = simpledialog.askstring(self.t("dialog.align_mode"), self.t("dialog.align_prompt"), initialvalue=self.t("align.center"), parent=self.root)
            if not selected:
                return
            mode = align_labels.get(selected, selected if selected in align_labels.values() else "center")
            metadata = align_frames(source.directory, self.project_path() / "05_aligned", mode=mode, alpha_threshold=8, source_signature=source.signature)
            self.current_project["align"] = metadata
            self.pm.save_project(self.current_project_id, self.current_project)
            self.status_var.set(self.t("status.aligned", count=metadata["frame_count"]))
            self.refresh_preview_images()
        except Exception as exc:
            messagebox.showerror(self.t("error.align_title"), str(exc), parent=self.root)

    def run_export(self) -> None:
        self.stop_animation()
        try:
            source = resolve_final_result_source(self.current_project, self.project_path())
            if source is None:
                raise ValueError(self.t("error.run_first"))
            if self.current_project.get("project_type") == "video":
                metadata = export_png_frame_sequence(source, self.project_path() / "exports" / "final_frames")
                output_directory = Path(metadata["directory"])
                if not output_directory.is_dir():
                    raise FileNotFoundError(output_directory)
                if len(list(output_directory.glob("frame_*.png"))) != int(metadata["frame_count"]):
                    raise ValueError(self.t("error.export_frame_count"))
                self.current_project["exports"] = metadata
                self.pm.save_project(self.current_project_id, self.current_project)
                self.status_var.set(self.t("status.exported", path=metadata["directory"]))
                self.root.after_idle(self._open_output_directory, output_directory)
                return
            name = simpledialog.askstring(self.t("dialog.filename"), self.t("dialog.output_png"), initialvalue="sheet_transparent.png", parent=self.root)
            if not name:
                return
            metadata = export_sheet(source.directory, self.project_path() / "exports", int(self.current_project.get("rows", 1)), int(self.current_project.get("cols", 1)), name)
            output_file = Path(metadata["sheet"])
            if not output_file.is_file():
                raise FileNotFoundError(output_file)
            self.current_project["exports"] = metadata
            self.pm.save_project(self.current_project_id, self.current_project)
            self.status_var.set(self.t("status.exported", path=metadata["sheet"]))
            self.root.after_idle(self._open_output_directory, output_file.parent)
        except Exception as exc:
            messagebox.showerror(self.t("error.export_title"), str(exc), parent=self.root)

    def _open_output_directory(self, output_directory: Path) -> None:
        try:
            os.startfile(str(output_directory))
        except OSError as exc:
            self.status_var.set(self.t("status.open_folder_failed", error=exc))

    def save_preset_ui(self) -> None:
        path = filedialog.asksaveasfilename(title=self.t("dialog.save_preset"), initialdir=self.presets_dir, defaultextension=".json", filetypes=[("JSON", "*.json")])
        if path:
            save_preset(Path(path), self.collect_params())

    def load_preset_ui(self) -> None:
        path = filedialog.askopenfilename(title=self.t("dialog.load_preset"), initialdir=self.presets_dir, filetypes=[("JSON", "*.json")])
        if path:
            self.apply_params(load_preset(Path(path)))
            self.refresh_preview_images()

    def open_project_folder(self) -> None:
        os.startfile(self.project_path())
