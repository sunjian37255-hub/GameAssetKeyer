from __future__ import annotations

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0

import tkinter as tk
from tkinter import ttk
from typing import Callable

from ..project_manager import INVALID_CHARS


def validate_project_display_name(name: str) -> str:
    value = name.strip()
    if not value:
        raise ValueError("project.rename.error.required")
    if any(char in value for char in INVALID_CHARS) or value.endswith((" ", ".")):
        raise ValueError("project.rename.error.invalid")
    return value


class ProjectNameDialog:
    def __init__(self, parent: tk.Misc, initial_name: str, translate: Callable[..., str]):
        self.parent = parent
        self.t = translate
        self.result: str | None = None
        self.window = tk.Toplevel(parent)
        self.window.title(self.t("project.rename.title"))
        self.window.transient(parent)
        self.window.resizable(False, False)
        self.window.protocol("WM_DELETE_WINDOW", self.cancel)
        self.window.bind("<Escape>", lambda _event: self.cancel())
        self.window.bind("<Return>", lambda _event: self.submit())
        self.name_var = tk.StringVar(value=initial_name)
        self.error_var = tk.StringVar()

        content = ttk.Frame(self.window, padding=18)
        content.grid(row=0, column=0, sticky="nsew")
        content.columnconfigure(0, weight=1)
        ttk.Label(content, text=self.t("project.rename.label")).grid(row=0, column=0, sticky="w")
        self.name_entry = ttk.Entry(content, textvariable=self.name_var, width=42)
        self.name_entry.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        ttk.Label(content, textvariable=self.error_var, foreground="#ff7b72", wraplength=380).grid(row=2, column=0, sticky="w", pady=(6, 0))
        actions = ttk.Frame(content)
        actions.grid(row=3, column=0, sticky="e", pady=(12, 0))
        ttk.Button(actions, text=self.t("action.cancel"), command=self.cancel).pack(side="left", padx=(0, 6))
        ttk.Button(actions, text=self.t("project.rename.submit"), style="Primary.TButton", command=self.submit).pack(side="left")
        self._center()

    def _center(self) -> None:
        self.window.update_idletasks()
        width = self.window.winfo_reqwidth()
        height = self.window.winfo_reqheight()
        x = max(0, self.parent.winfo_rootx() + (self.parent.winfo_width() - width) // 2)
        y = max(0, self.parent.winfo_rooty() + (self.parent.winfo_height() - height) // 2)
        self.window.geometry(f"+{x}+{y}")

    def show(self) -> str | None:
        self.window.grab_set()
        self.window.lift()
        self.window.focus_force()
        self.name_entry.focus_set()
        self.name_entry.selection_range(0, "end")
        self.window.wait_window()
        return self.result

    def submit(self) -> None:
        try:
            self.result = validate_project_display_name(self.name_var.get())
        except ValueError as exc:
            self.error_var.set(self.t(str(exc)))
            return
        self.window.destroy()

    def cancel(self) -> None:
        self.result = None
        self.window.destroy()
