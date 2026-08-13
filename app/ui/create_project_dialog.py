from __future__ import annotations

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0

import re
import tkinter as tk
from pathlib import Path
from tkinter import colorchooser, filedialog, ttk
from typing import Callable

from ..color_key_processor import TARGETS, parse_color
from ..project_manager import INVALID_CHARS


PROJECT_KINDS = {"image", "sheet", "video"}
MODE_KEYS = ("black", "white", "green", "magenta", "custom")
POSITIVE_INTEGER = re.compile(r"^[1-9]\d*$")


class CreateProjectValidationError(ValueError):
    def __init__(self, message_key: str):
        super().__init__(message_key)
        self.message_key = message_key


def _positive_integer(text: str, message_key: str) -> int:
    value = text.strip()
    if not POSITIVE_INTEGER.fullmatch(value):
        raise CreateProjectValidationError(message_key)
    return int(value)


def validate_create_values(kind: str, values: dict[str, str]) -> dict[str, object]:
    if kind not in PROJECT_KINDS:
        raise ValueError(f"Unsupported project kind: {kind}")

    source = Path(values.get("source", "").strip())
    if not values.get("source", "").strip():
        raise CreateProjectValidationError("create.error.source_required")
    if not source.is_file():
        raise CreateProjectValidationError("create.error.source_missing")
    if kind in {"image", "sheet"} and source.suffix.lower() != ".png":
        raise CreateProjectValidationError("create.error.png_required")

    name = values.get("name", "").strip()
    if not name:
        raise CreateProjectValidationError("create.error.name_required")
    if any(char in name for char in INVALID_CHARS) or name.endswith((" ", ".")):
        raise CreateProjectValidationError("create.error.name_invalid")

    mode = values.get("target_mode", "")
    if mode not in MODE_KEYS:
        raise CreateProjectValidationError("create.error.color_invalid")
    try:
        rgb = parse_color(mode, values.get("custom_color", ""))
    except (TypeError, ValueError):
        raise CreateProjectValidationError("create.error.color_invalid") from None
    custom_color = "#{:02X}{:02X}{:02X}".format(*rgb)

    result: dict[str, object] = {
        "kind": kind,
        "source": source,
        "name": name,
        "target_mode": mode,
        "custom_color": custom_color,
    }
    if kind == "sheet":
        result["rows"] = _positive_integer(values.get("rows", ""), "create.error.rows_invalid")
        result["cols"] = _positive_integer(values.get("cols", ""), "create.error.cols_invalid")
    elif kind == "video":
        result["frame_interval"] = _positive_integer(values.get("frame_interval", ""), "create.error.interval_invalid")
    return result


class CreateProjectDialog:
    def __init__(self, parent: tk.Misc, kind: str, translate: Callable[..., str], mode_labels: dict[str, str]):
        if kind not in PROJECT_KINDS:
            raise ValueError(f"Unsupported project kind: {kind}")
        self.parent = parent
        self.kind = kind
        self.t = translate
        self.mode_labels = mode_labels
        self.label_to_mode = {label: key for key, label in mode_labels.items()}
        self.result: dict[str, object] | None = None
        self._auto_name = ""
        self._last_custom_color = "#000000"
        self._current_mode = "black"

        self.window = tk.Toplevel(parent)
        self.window.title(self.t(f"create.title.{kind}"))
        self.window.transient(parent)
        self.window.resizable(False, False)
        self.window.protocol("WM_DELETE_WINDOW", self.cancel)
        self.window.bind("<Escape>", lambda _event: self.cancel())
        self.window.bind("<Return>", lambda _event: self.submit())

        self.source_var = tk.StringVar()
        self.name_var = tk.StringVar()
        self.rows_var = tk.StringVar(value="3")
        self.cols_var = tk.StringVar(value="3")
        self.interval_var = tk.StringVar(value="1")
        self.mode_var = tk.StringVar(value=mode_labels["black"])
        self.custom_color_var = tk.StringVar(value="#000000")
        self.error_var = tk.StringVar()

        self._build()
        self.custom_color_var.trace_add("write", self._update_swatch)
        self._on_mode_change()
        self._center()

    def _build(self) -> None:
        content = ttk.Frame(self.window, padding=18)
        content.grid(row=0, column=0, sticky="nsew")
        content.columnconfigure(1, weight=1)

        ttk.Label(content, text=self.t("create.input_file")).grid(row=0, column=0, sticky="w", pady=(0, 8))
        source_entry = ttk.Entry(content, textvariable=self.source_var, state="readonly", width=48)
        source_entry.grid(row=0, column=1, sticky="ew", padx=(10, 6), pady=(0, 8))
        ttk.Button(content, text=self.t("create.browse"), command=self.browse).grid(row=0, column=2, pady=(0, 8))

        ttk.Label(content, text=self.t("create.project_name")).grid(row=1, column=0, sticky="w", pady=8)
        self.name_entry = ttk.Entry(content, textvariable=self.name_var, width=36)
        self.name_entry.grid(row=1, column=1, columnspan=2, sticky="ew", padx=(10, 0), pady=8)

        next_row = 2
        if self.kind == "sheet":
            ttk.Label(content, text=self.t("create.rows")).grid(row=next_row, column=0, sticky="w", pady=8)
            ttk.Spinbox(content, from_=1, to=9999, textvariable=self.rows_var, width=10).grid(row=next_row, column=1, columnspan=2, sticky="w", padx=(10, 0), pady=8)
            next_row += 1
            ttk.Label(content, text=self.t("create.cols")).grid(row=next_row, column=0, sticky="w", pady=8)
            ttk.Spinbox(content, from_=1, to=9999, textvariable=self.cols_var, width=10).grid(row=next_row, column=1, columnspan=2, sticky="w", padx=(10, 0), pady=8)
            next_row += 1
        elif self.kind == "video":
            ttk.Label(content, text=self.t("create.frame_interval")).grid(row=next_row, column=0, sticky="w", pady=8)
            ttk.Spinbox(content, from_=1, to=999999, textvariable=self.interval_var, width=10).grid(row=next_row, column=1, columnspan=2, sticky="w", padx=(10, 0), pady=8)
            next_row += 1

        ttk.Label(content, text=self.t("create.target_color")).grid(row=next_row, column=0, sticky="w", pady=8)
        self.mode_combo = ttk.Combobox(content, textvariable=self.mode_var, values=[self.mode_labels[key] for key in MODE_KEYS], state="readonly")
        self.mode_combo.grid(row=next_row, column=1, columnspan=2, sticky="ew", padx=(10, 0), pady=8)
        self.mode_combo.bind("<<ComboboxSelected>>", self._on_mode_change)
        next_row += 1

        ttk.Label(content, text=self.t("create.custom_color")).grid(row=next_row, column=0, sticky="w", pady=8)
        color_row = ttk.Frame(content)
        color_row.grid(row=next_row, column=1, columnspan=2, sticky="ew", padx=(10, 0), pady=8)
        self.color_swatch = tk.Label(color_row, width=3, relief="sunken", borderwidth=1, background="#000000")
        self.color_swatch.pack(side="left", fill="y")
        self.custom_entry = ttk.Entry(color_row, textvariable=self.custom_color_var, width=12)
        self.custom_entry.pack(side="left", fill="x", expand=True, padx=6)
        self.color_button = ttk.Button(color_row, text=self.t("create.choose_color"), command=self.choose_color)
        self.color_button.pack(side="right")
        next_row += 1

        ttk.Label(content, textvariable=self.error_var, foreground="#ff7b72", wraplength=480).grid(row=next_row, column=0, columnspan=3, sticky="w", pady=(6, 4))
        next_row += 1
        actions = ttk.Frame(content)
        actions.grid(row=next_row, column=0, columnspan=3, sticky="e", pady=(8, 0))
        ttk.Button(actions, text=self.t("action.cancel"), command=self.cancel).pack(side="left", padx=(0, 6))
        ttk.Button(actions, text=self.t("create.submit"), style="Primary.TButton", command=self.submit).pack(side="left")

    def _center(self) -> None:
        self.window.update_idletasks()
        width = self.window.winfo_reqwidth()
        height = self.window.winfo_reqheight()
        parent_x = self.parent.winfo_rootx()
        parent_y = self.parent.winfo_rooty()
        parent_width = max(self.parent.winfo_width(), self.parent.winfo_reqwidth())
        parent_height = max(self.parent.winfo_height(), self.parent.winfo_reqheight())
        x = max(0, parent_x + (parent_width - width) // 2)
        y = max(0, parent_y + (parent_height - height) // 2)
        self.window.geometry(f"+{x}+{y}")

    def show(self) -> dict[str, object] | None:
        self.window.grab_set()
        self.window.lift()
        self.window.focus_force()
        self.name_entry.focus_set()
        self.window.wait_window()
        return self.result

    def browse(self) -> None:
        if self.kind == "video":
            path = filedialog.askopenfilename(
                parent=self.window,
                title=self.t("dialog.select_video"),
                filetypes=[(self.t("file.video"), "*.mp4 *.avi *.mov *.mkv *.webm *.m4v"), (self.t("file.all"), "*.*")],
            )
        else:
            title_key = "dialog.select_sheet" if self.kind == "sheet" else "dialog.select_png"
            path = filedialog.askopenfilename(parent=self.window, title=self.t(title_key), filetypes=[("PNG", "*.png")])
        if not path:
            return
        self.source_var.set(path)
        stem = Path(path).stem
        if not self.name_var.get().strip() or self.name_var.get() == self._auto_name:
            self.name_var.set(stem)
            self._auto_name = stem
        self.error_var.set("")

    def _on_mode_change(self, _event=None) -> None:
        selected_mode = self.label_to_mode.get(self.mode_var.get(), "black")
        if self._current_mode == "custom" and selected_mode != "custom":
            try:
                self._last_custom_color = "#{:02X}{:02X}{:02X}".format(*parse_color("custom", self.custom_color_var.get()))
            except ValueError:
                pass
        self._current_mode = selected_mode
        if selected_mode == "custom":
            self.custom_color_var.set(self._last_custom_color)
            self.custom_entry.configure(state="normal")
            self.color_button.configure(state="normal")
        else:
            self.custom_color_var.set("#{:02X}{:02X}{:02X}".format(*TARGETS[selected_mode]))
            self.custom_entry.configure(state="readonly")
            self.color_button.configure(state="disabled")
        self.error_var.set("")

    def _update_swatch(self, *_args) -> None:
        try:
            rgb = parse_color("custom", self.custom_color_var.get())
        except ValueError:
            return
        self.color_swatch.configure(background="#{:02X}{:02X}{:02X}".format(*rgb))

    def choose_color(self) -> None:
        selected = colorchooser.askcolor(color=self.custom_color_var.get(), parent=self.window, title=self.t("create.choose_color"))[1]
        if selected:
            self.custom_color_var.set(selected.upper())

    def _values(self) -> dict[str, str]:
        return {
            "source": self.source_var.get(),
            "name": self.name_var.get(),
            "rows": self.rows_var.get(),
            "cols": self.cols_var.get(),
            "frame_interval": self.interval_var.get(),
            "target_mode": self.label_to_mode.get(self.mode_var.get(), ""),
            "custom_color": self.custom_color_var.get(),
        }

    def submit(self) -> None:
        try:
            self.result = validate_create_values(self.kind, self._values())
        except CreateProjectValidationError as exc:
            self.error_var.set(self.t(exc.message_key))
            return
        self.window.destroy()

    def cancel(self) -> None:
        self.result = None
        self.window.destroy()
