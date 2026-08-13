from __future__ import annotations

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0

import re
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk
from typing import Callable


POSITIVE_INTEGER = re.compile(r"^[1-9]\d*$")


class EqualGridValidationError(ValueError):
    def __init__(self, message_key: str):
        super().__init__(message_key)
        self.message_key = message_key


def validate_equal_grid_values(values: dict[str, str]) -> dict[str, object]:
    source_text = values.get("source", "").strip()
    if not source_text:
        raise EqualGridValidationError("equal_grid.error.source_required")
    source = Path(source_text)
    if not source.is_file():
        raise EqualGridValidationError("equal_grid.error.source_missing")
    if source.suffix.lower() != ".png":
        raise EqualGridValidationError("equal_grid.error.png_required")

    output_text = values.get("output", "").strip()
    if not output_text:
        raise EqualGridValidationError("equal_grid.error.output_required")
    output = Path(output_text)
    if output.suffix.lower() != ".png":
        raise EqualGridValidationError("equal_grid.error.output_png")
    if source.resolve() == output.resolve():
        raise EqualGridValidationError("equal_grid.error.same_file")

    dimensions: dict[str, int] = {}
    for key in ("rows", "cols"):
        text = values.get(key, "").strip()
        if not POSITIVE_INTEGER.fullmatch(text):
            raise EqualGridValidationError(f"equal_grid.error.{key}_invalid")
        dimensions[key] = int(text)
    return {"source": source, "output": output, **dimensions}


class EqualGridDialog:
    def __init__(self, parent: tk.Misc, translate: Callable[..., str]):
        self.parent = parent
        self.t = translate
        self.result: dict[str, object] | None = None
        self._auto_output = ""
        self.window = tk.Toplevel(parent)
        self.window.title(self.t("equal_grid.title"))
        self.window.transient(parent)
        self.window.resizable(False, False)
        self.window.protocol("WM_DELETE_WINDOW", self.cancel)
        self.window.bind("<Escape>", lambda _event: self.cancel())
        self.window.bind("<Return>", lambda _event: self.submit())
        self.source_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.rows_var = tk.StringVar(value="4")
        self.cols_var = tk.StringVar(value="6")
        self.error_var = tk.StringVar()
        self._build()
        self._center()

    def _build(self) -> None:
        content = ttk.Frame(self.window, padding=18)
        content.grid(row=0, column=0, sticky="nsew")
        content.columnconfigure(1, weight=1)
        self._file_row(content, 0, "equal_grid.input", self.source_var, self.browse_source)
        self._file_row(content, 1, "equal_grid.output", self.output_var, self.browse_output)
        ttk.Label(content, text=self.t("equal_grid.rows")).grid(row=2, column=0, sticky="w", pady=8)
        ttk.Spinbox(content, from_=1, to=9999, textvariable=self.rows_var, width=10).grid(row=2, column=1, columnspan=2, sticky="w", padx=(10, 0), pady=8)
        ttk.Label(content, text=self.t("equal_grid.cols")).grid(row=3, column=0, sticky="w", pady=8)
        ttk.Spinbox(content, from_=1, to=9999, textvariable=self.cols_var, width=10).grid(row=3, column=1, columnspan=2, sticky="w", padx=(10, 0), pady=8)
        ttk.Label(content, textvariable=self.error_var, foreground="#ff7b72", wraplength=500).grid(row=4, column=0, columnspan=3, sticky="w", pady=(6, 4))
        actions = ttk.Frame(content)
        actions.grid(row=5, column=0, columnspan=3, sticky="e", pady=(8, 0))
        ttk.Button(actions, text=self.t("action.cancel"), command=self.cancel).pack(side="left", padx=(0, 6))
        ttk.Button(actions, text=self.t("equal_grid.submit"), style="Primary.TButton", command=self.submit).pack(side="left")

    def _file_row(self, content: ttk.Frame, row: int, label_key: str, variable: tk.StringVar, command) -> None:
        ttk.Label(content, text=self.t(label_key)).grid(row=row, column=0, sticky="w", pady=8)
        ttk.Entry(content, textvariable=variable, state="readonly", width=52).grid(row=row, column=1, sticky="ew", padx=(10, 6), pady=8)
        ttk.Button(content, text=self.t("create.browse"), command=command).grid(row=row, column=2, pady=8)

    def _center(self) -> None:
        self.window.update_idletasks()
        width = self.window.winfo_reqwidth()
        height = self.window.winfo_reqheight()
        x = max(0, self.parent.winfo_rootx() + (self.parent.winfo_width() - width) // 2)
        y = max(0, self.parent.winfo_rooty() + (self.parent.winfo_height() - height) // 2)
        self.window.geometry(f"+{x}+{y}")

    def show(self) -> dict[str, object] | None:
        self.window.grab_set()
        self.window.lift()
        self.window.focus_force()
        self.window.wait_window()
        return self.result

    def browse_source(self) -> None:
        path = filedialog.askopenfilename(parent=self.window, title=self.t("dialog.select_equal_grid"), filetypes=[("PNG", "*.png")])
        if not path:
            return
        self.source_var.set(path)
        proposed = str(Path(path).with_name(f"{Path(path).stem}_equal_grid.png"))
        if not self.output_var.get() or self.output_var.get() == self._auto_output:
            self.output_var.set(proposed)
            self._auto_output = proposed
        self.error_var.set("")

    def browse_output(self) -> None:
        current = Path(self.output_var.get()) if self.output_var.get() else None
        source = Path(self.source_var.get()) if self.source_var.get() else None
        initial_dir = current.parent if current else (source.parent if source else None)
        initial_file = current.name if current else (f"{source.stem}_equal_grid.png" if source else "equal_grid.png")
        path = filedialog.asksaveasfilename(
            parent=self.window,
            title=self.t("dialog.save_equal_grid"),
            initialdir=initial_dir,
            initialfile=initial_file,
            defaultextension=".png",
            filetypes=[("PNG", "*.png")],
        )
        if path:
            self.output_var.set(path)
            self._auto_output = ""
            self.error_var.set("")

    def submit(self) -> None:
        try:
            self.result = validate_equal_grid_values({
                "source": self.source_var.get(),
                "output": self.output_var.get(),
                "rows": self.rows_var.get(),
                "cols": self.cols_var.get(),
            })
        except EqualGridValidationError as exc:
            self.error_var.set(self.t(exc.message_key))
            return
        self.window.destroy()

    def cancel(self) -> None:
        self.result = None
        self.window.destroy()
