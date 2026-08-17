from __future__ import annotations

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0

import os
import re
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable

from PIL import Image, ImageTk

from ..frame_sequence_composer import (
    calculate_grid,
    calculate_layout,
    compose_sprite_sheet,
    is_hidden_path,
    list_png_files,
    natural_sort_key,
    render_sprite_sheet_thumbnail,
    validate_alignment,
    validate_padding,
)
from .theme import ACCENT, BG_INPUT, BG_ROOT, CHECKER_DARK, CHECKER_LIGHT, DANGER, TEXT_PRIMARY


POSITIVE_INTEGER = re.compile(r"^[1-9]\d*$")


class ComposerValidationError(ValueError):
    def __init__(self, message_key: str):
        super().__init__(message_key)
        self.message_key = message_key


def choose_auto_output_path(
    files: list[Path] | tuple[Path, ...],
    current_output: str | Path | None,
    previous_auto_output: str | Path | None,
) -> tuple[str, str]:
    """Return the output path and auto marker for a changed file set.

    A path previously proposed by the dialog follows the first frame when the
    input set changes. Any other non-empty path is treated as user-owned and
    is preserved. Clearing removes an automatic path but never a manual one.
    """

    current = str(current_output or "")
    previous_auto = str(previous_auto_output or "")

    def same_path(left: str, right: str) -> bool:
        if not left or not right:
            return False
        return os.path.normcase(os.path.abspath(left)).casefold() == os.path.normcase(os.path.abspath(right)).casefold()

    if not files:
        return ("", "") if not current or same_path(current, previous_auto) else (current, "")
    proposed = str(Path(files[0]).with_name(f"{Path(files[0]).stem}_sheet.png"))
    if not current or same_path(current, previous_auto):
        return proposed, proposed
    return current, ""


def validate_composer_values(values: dict[str, object]) -> dict[str, object]:
    """Validate serializable dialog state without creating Tk widgets."""

    paths = [Path(path) for path in values.get("files", [])]
    paths = [path for path in paths if path.is_file() and path.suffix.lower() == ".png"]
    if not paths:
        raise ComposerValidationError("composer.error.no_frames")
    columns_text = str(values.get("columns", "")).strip()
    if not POSITIVE_INTEGER.fullmatch(columns_text):
        raise ComposerValidationError("composer.error.columns")
    try:
        padding = validate_padding(values.get("padding", 0))
        alignment = validate_alignment(str(values.get("alignment", "center")))
    except ValueError:
        raise ComposerValidationError("composer.error.layout") from None
    output_text = str(values.get("output", "")).strip()
    if not output_text:
        raise ComposerValidationError("composer.error.output")
    output = Path(output_text)
    if output.suffix.lower() != ".png":
        raise ComposerValidationError("composer.error.output_png")
    return {
        # Explicit list order is meaningful because Move Up/Down is a core
        # part of the composer.  Folder/file selection is naturally sorted at
        # ingestion time; validation must not undo later manual ordering.
        "files": paths,
        "columns": int(columns_text),
        "padding": padding,
        "alignment": alignment,
        "output": output,
    }


class FrameSequenceComposerDialog:
    """Standalone PNG sequence composer with a bounded thumbnail preview."""

    def __init__(self, parent: tk.Misc, translate: Callable[..., str]):
        self.parent = parent
        self.t = translate
        self.result: dict[str, object] | None = None
        self.files: list[Path] = []
        self._preview_photo: ImageTk.PhotoImage | None = None
        self._preview_image: Image.Image | None = None
        self._auto_output = ""

        self.window = tk.Toplevel(parent)
        self.window.title(self.t("composer.title"))
        self.window.transient(parent)
        self.window.minsize(820, 620)
        self.window.protocol("WM_DELETE_WINDOW", self.cancel)
        self.window.bind("<Escape>", lambda _event: self.cancel())
        self.columns_var = tk.StringVar(value="1")
        self.padding_var = tk.StringVar(value="0")
        self.alignment_var = tk.StringVar(value=self.t("composer.center"))
        self.output_var = tk.StringVar()
        self.info_var = tk.StringVar(value=self.t("composer.info.empty"))
        self.status_var = tk.StringVar()
        self.error_var = tk.StringVar()
        self._alignment_values = {
            self.t("composer.center"): "center",
            self.t("composer.bottom_center"): "bottom_center",
        }
        self._build()
        self._center()

    def _build(self) -> None:
        content = ttk.Frame(self.window, padding=14)
        content.grid(row=0, column=0, sticky="nsew")
        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(0, weight=1)
        content.columnconfigure(0, weight=0)
        content.columnconfigure(1, weight=1)
        content.rowconfigure(2, weight=1)

        actions = ttk.Frame(content)
        actions.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        ttk.Button(actions, text=self.t("composer.select_files"), command=self.select_files).pack(side="left", padx=(0, 5))
        ttk.Button(actions, text=self.t("composer.select_folder"), command=self.select_folder).pack(side="left", padx=(0, 5))
        ttk.Button(actions, text=self.t("composer.clear"), command=self.clear).pack(side="left")

        list_frame = ttk.Frame(content)
        list_frame.grid(row=1, column=0, rowspan=2, sticky="nsew", padx=(0, 12))
        list_frame.rowconfigure(0, weight=1)
        list_frame.columnconfigure(0, weight=1)
        self.listbox = tk.Listbox(
            list_frame,
            background=BG_INPUT,
            foreground=TEXT_PRIMARY,
            selectbackground=ACCENT,
            borderwidth=0,
            highlightthickness=0,
            width=34,
            exportselection=False,
        )
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=scrollbar.set)
        self.listbox.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        list_buttons = ttk.Frame(list_frame)
        list_buttons.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(7, 0))
        for key, command in (
            ("composer.move_up", self.move_up),
            ("composer.move_down", self.move_down),
            ("composer.remove", self.remove),
        ):
            ttk.Button(list_buttons, text=self.t(key), command=command).pack(side="left", fill="x", expand=True, padx=(0, 4))

        settings = ttk.LabelFrame(content, text=self.t("composer.settings"), padding=10)
        settings.grid(row=1, column=1, sticky="ew")
        settings.columnconfigure(1, weight=1)
        ttk.Label(settings, text=self.t("composer.columns")).grid(row=0, column=0, sticky="w", pady=4)
        columns = ttk.Spinbox(settings, from_=1, to=9999, textvariable=self.columns_var, width=8, command=self.refresh)
        columns.grid(row=0, column=1, sticky="w", padx=(10, 0), pady=4)
        columns.bind("<KeyRelease>", lambda _event: self.refresh())
        ttk.Label(settings, text=self.t("composer.padding")).grid(row=1, column=0, sticky="w", pady=4)
        padding = ttk.Spinbox(settings, from_=0, to=256, textvariable=self.padding_var, width=8, command=self.refresh)
        padding.grid(row=1, column=1, sticky="w", padx=(10, 0), pady=4)
        padding.bind("<KeyRelease>", lambda _event: self.refresh())
        ttk.Label(settings, text=self.t("composer.alignment")).grid(row=2, column=0, sticky="w", pady=4)
        alignment = ttk.Combobox(settings, textvariable=self.alignment_var, state="readonly", values=list(self._alignment_values), width=18)
        alignment.grid(row=2, column=1, sticky="w", padx=(10, 0), pady=4)
        alignment.bind("<<ComboboxSelected>>", lambda _event: self.refresh())
        ttk.Label(settings, textvariable=self.info_var, style="Muted.TLabel", justify="left").grid(row=3, column=0, columnspan=2, sticky="w", pady=(9, 0))

        preview_frame = ttk.LabelFrame(content, text=self.t("composer.preview"), padding=8)
        preview_frame.grid(row=2, column=1, sticky="nsew", pady=(10, 0))
        preview_frame.columnconfigure(0, weight=1)
        preview_frame.rowconfigure(0, weight=1)
        self.preview_canvas = tk.Canvas(preview_frame, background=BG_ROOT, highlightthickness=0, width=500, height=350)
        self.preview_canvas.grid(row=0, column=0, sticky="nsew")
        self.preview_canvas.bind("<Configure>", lambda _event: self._draw_preview())

        output = ttk.Frame(content)
        output.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        output.columnconfigure(1, weight=1)
        ttk.Label(output, text=self.t("composer.output")).grid(row=0, column=0, sticky="w")
        ttk.Entry(output, textvariable=self.output_var, width=48).grid(row=0, column=1, sticky="ew", padx=(10, 6))
        ttk.Button(output, text=self.t("create.browse"), command=self.browse_output).grid(row=0, column=2)
        ttk.Label(content, textvariable=self.error_var, foreground=DANGER, wraplength=760).grid(row=4, column=0, columnspan=2, sticky="w", pady=(7, 0))
        ttk.Label(content, textvariable=self.status_var, style="Muted.TLabel", wraplength=760).grid(row=5, column=0, columnspan=2, sticky="w", pady=(4, 0))
        controls = ttk.Frame(content)
        controls.grid(row=6, column=0, columnspan=2, sticky="e", pady=(9, 0))
        ttk.Button(controls, text=self.t("action.cancel"), command=self.cancel).pack(side="left", padx=(0, 6))
        ttk.Button(controls, text=self.t("composer.export"), style="Primary.TButton", command=self.export).pack(side="left")

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

    def _set_files(self, paths: list[Path]) -> None:
        self.files = sorted(
            {
                path.resolve()
                for path in paths
                if path.is_file() and path.suffix.lower() == ".png" and not is_hidden_path(path)
            },
            key=natural_sort_key,
        )
        if self.files:
            self.columns_var.set(str(calculate_grid(len(self.files)).columns))
        self.listbox.delete(0, "end")
        for path in self.files:
            self.listbox.insert("end", path.name)
        output, auto_output = choose_auto_output_path(self.files, self.output_var.get(), self._auto_output)
        self.output_var.set(output)
        self._auto_output = auto_output
        self.refresh()

    def select_files(self) -> None:
        paths = filedialog.askopenfilenames(parent=self.window, title=self.t("composer.select_files"), filetypes=[("PNG", "*.png")])
        if paths:
            self._set_files([Path(path) for path in paths])

    def select_folder(self) -> None:
        path = filedialog.askdirectory(parent=self.window, title=self.t("composer.select_folder"))
        if path:
            self._set_files(list_png_files(Path(path)))

    def clear(self) -> None:
        self._set_files([])
        self.status_var.set("")

    def _selected_index(self) -> int | None:
        selection = self.listbox.curselection()
        return int(selection[0]) if selection else None

    def move_up(self) -> None:
        index = self._selected_index()
        if index is None or index <= 0:
            return
        self.files[index - 1], self.files[index] = self.files[index], self.files[index - 1]
        self._set_files_in_current_order(index - 1)

    def move_down(self) -> None:
        index = self._selected_index()
        if index is None or index >= len(self.files) - 1:
            return
        self.files[index + 1], self.files[index] = self.files[index], self.files[index + 1]
        self._set_files_in_current_order(index + 1)

    def _set_files_in_current_order(self, selected: int | None = None) -> None:
        self.listbox.delete(0, "end")
        for path in self.files:
            self.listbox.insert("end", path.name)
        if selected is not None and self.files:
            self.listbox.selection_set(selected)
            self.listbox.see(selected)
        self.refresh()

    def remove(self) -> None:
        index = self._selected_index()
        if index is None:
            return
        self.files.pop(index)
        self._set_files_in_current_order(min(index, len(self.files) - 1) if self.files else None)

    def browse_output(self) -> None:
        current = Path(self.output_var.get()) if self.output_var.get() else None
        initial_dir = current.parent if current else (self.files[0].parent if self.files else None)
        initial_file = current.name if current else "sprite_sheet.png"
        path = filedialog.asksaveasfilename(
            parent=self.window,
            title=self.t("composer.save_output"),
            initialdir=initial_dir,
            initialfile=initial_file,
            defaultextension=".png",
            filetypes=[("PNG", "*.png")],
        )
        if path:
            self.output_var.set(path)
            self._auto_output = ""
            self.error_var.set("")

    def _layout_values(self) -> tuple[int, int, str]:
        columns_text = self.columns_var.get().strip()
        if not POSITIVE_INTEGER.fullmatch(columns_text):
            raise ComposerValidationError("composer.error.columns")
        columns = int(columns_text)
        try:
            padding = validate_padding(self.padding_var.get().strip())
        except ValueError:
            raise ComposerValidationError("composer.error.layout") from None
        alignment = self._alignment_values.get(self.alignment_var.get(), "center")
        return columns, padding, alignment

    def refresh(self) -> None:
        if not self.files:
            self.info_var.set(self.t("composer.info.empty"))
            self.error_var.set("")
            self._preview_image = None
            self._draw_preview()
            return
        try:
            columns, padding, alignment = self._layout_values()
            layout = calculate_layout(self.files, columns, padding)
            self.info_var.set(self.t(
                "composer.info",
                frames=layout.frame_count,
                columns=layout.columns,
                rows=layout.rows,
                cell_width=layout.cell_width,
                cell_height=layout.cell_height,
                output_width=layout.output_width,
                output_height=layout.output_height,
            ))
            if layout.output_width > 16384 or layout.output_height > 16384:
                self.status_var.set(self.t("composer.warning_large"))
            else:
                self.status_var.set("")
            self._preview_image = render_sprite_sheet_thumbnail(self.files, columns, alignment, padding, max_size=640)
            self.error_var.set("")
        except ComposerValidationError as exc:
            self.error_var.set(self.t(exc.message_key))
            self._preview_image = None
        except (ValueError, OSError) as exc:
            self.error_var.set(self.t("composer.error.read", error=exc))
            self._preview_image = None
        self._draw_preview()

    def _draw_checkerboard(self, left: int, top: int, width: int, height: int, size: int = 10) -> None:
        colors = (CHECKER_DARK, CHECKER_LIGHT)
        for y in range(top, top + height, size):
            for x in range(left, left + width, size):
                color = colors[((x - left) // size + (y - top) // size) % 2]
                self.preview_canvas.create_rectangle(x, y, min(x + size, left + width), min(y + size, top + height), fill=color, outline="")

    def _draw_preview(self) -> None:
        self.preview_canvas.delete("all")
        if self._preview_image is None:
            self._preview_photo = None
            return
        width = max(1, self.preview_canvas.winfo_width())
        height = max(1, self.preview_canvas.winfo_height())
        image_width, image_height = self._preview_image.size
        scale = min((width - 20) / image_width, (height - 20) / image_height)
        scale = max(0.01, scale)
        display = self._preview_image.resize((max(1, round(image_width * scale)), max(1, round(image_height * scale))), Image.Resampling.LANCZOS)
        left = (width - display.width) // 2
        top = (height - display.height) // 2
        self._draw_checkerboard(left, top, display.width, display.height)
        self._preview_photo = ImageTk.PhotoImage(display)
        self.preview_canvas.create_image(left, top, image=self._preview_photo, anchor="nw")
        display.close()

    def export(self) -> None:
        try:
            values = validate_composer_values({
                "files": self.files,
                "columns": self.columns_var.get(),
                "padding": self.padding_var.get(),
                "alignment": self._alignment_values.get(self.alignment_var.get(), "center"),
                "output": self.output_var.get(),
            })
            output = Path(values["output"])
            if output.exists() and not messagebox.askyesno(self.t("composer.overwrite_title"), self.t("composer.overwrite_confirm", path=output), parent=self.window):
                return
            image = compose_sprite_sheet(values["files"], int(values["columns"]), str(values["alignment"]), int(values["padding"]))
            try:
                output.parent.mkdir(parents=True, exist_ok=True)
                image.save(output, format="PNG")
            finally:
                image.close()
            if not output.is_file():
                raise FileNotFoundError(output)
            self.result = {"output": output, "layout": calculate_layout(values["files"], int(values["columns"]), int(values["padding"]))}
            self.status_var.set(self.t("composer.exported", path=output))
            self.error_var.set("")
            try:
                os.startfile(str(output.parent))
            except OSError as exc:
                self.status_var.set(self.t("status.open_folder_failed", error=exc))
        except ComposerValidationError as exc:
            self.error_var.set(self.t(exc.message_key))
        except (OSError, ValueError) as exc:
            self.error_var.set(self.t("composer.error.export_failed", error=exc))

    def cancel(self) -> None:
        if self._preview_image is not None:
            self._preview_image.close()
            self._preview_image = None
        self.window.destroy()


# Keep both concise and explicit names available to callers/tests.
PNGSequenceComposerDialog = FrameSequenceComposerDialog
FrameSequenceComposer = FrameSequenceComposerDialog
