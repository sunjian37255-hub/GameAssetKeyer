from __future__ import annotations

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0

import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk
from typing import Callable

from ..video_splitter import (
    VIDEO_EXTS,
    ExtractionCancelled,
    VideoMetadata,
    VideoRangeResult,
    default_range_output_dir,
    extract_video_range,
    inspect_video,
    unique_output_dir,
    validate_time_range,
)
from .theme import DANGER


def format_timestamp(seconds: float) -> str:
    milliseconds = max(0, round(float(seconds) * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}.{milliseconds:03d}"
    return f"{minutes:02d}:{whole_seconds:02d}.{milliseconds:03d}"


class VideoFrameExtractorDialog:
    def __init__(self, parent: tk.Misc, translate: Callable[..., str]):
        self.parent = parent
        self.t = translate
        self.result: VideoRangeResult | None = None
        self.metadata: VideoMetadata | None = None
        self._events: queue.Queue[tuple[str, object]] = queue.Queue()
        self._worker: threading.Thread | None = None
        self._cancel_event = threading.Event()

        self.window = tk.Toplevel(parent)
        self.window.title(self.t("video_extractor.title"))
        self.window.transient(parent)
        self.window.minsize(780, 560)
        self.window.protocol("WM_DELETE_WINDOW", self.cancel)
        self.window.bind("<Escape>", lambda _event: self.cancel())

        self.source_var = tk.StringVar()
        self.metadata_var = tk.StringVar(value=self.t("video_extractor.info.empty"))
        self.start_scale_var = tk.DoubleVar(value=0.0)
        self.end_scale_var = tk.DoubleVar(value=0.0)
        self.start_entry_var = tk.StringVar(value="0.000")
        self.end_entry_var = tk.StringVar(value="0.000")
        self.range_var = tk.StringVar(value=self.t("video_extractor.range.empty"))
        self.status_var = tk.StringVar(value=self.t("video_extractor.status.ready"))
        self.error_var = tk.StringVar()
        self.progress_var = tk.DoubleVar(value=0.0)
        self._build()
        self._center()

    def _build(self) -> None:
        content = ttk.Frame(self.window, padding=16)
        content.grid(row=0, column=0, sticky="nsew")
        self.window.rowconfigure(0, weight=1)
        self.window.columnconfigure(0, weight=1)
        content.columnconfigure(0, weight=1)
        content.rowconfigure(2, weight=1)

        source = ttk.LabelFrame(content, text=self.t("video_extractor.source"), padding=10)
        source.grid(row=0, column=0, sticky="ew")
        source.columnconfigure(0, weight=1)
        ttk.Entry(source, textvariable=self.source_var, state="readonly").grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.select_button = ttk.Button(source, text=self.t("video_extractor.select_video"), command=self.select_video)
        self.select_button.grid(row=0, column=1)
        ttk.Label(source, textvariable=self.metadata_var, style="Muted.TLabel", justify="left").grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))

        timeline = ttk.LabelFrame(content, text=self.t("video_extractor.timeline"), padding=10)
        timeline.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        timeline.columnconfigure(1, weight=1)

        ttk.Label(timeline, text=self.t("video_extractor.start_time")).grid(row=0, column=0, sticky="w", padx=(0, 10))
        self.start_scale = ttk.Scale(timeline, from_=0, to=1, variable=self.start_scale_var, command=self._on_start_scale)
        self.start_scale.grid(row=0, column=1, sticky="ew")
        self.start_entry = ttk.Entry(timeline, textvariable=self.start_entry_var, width=10)
        self.start_entry.grid(row=0, column=2, padx=(10, 0))

        ttk.Label(timeline, text=self.t("video_extractor.end_time")).grid(row=1, column=0, sticky="w", padx=(0, 10), pady=(9, 0))
        self.end_scale = ttk.Scale(timeline, from_=0, to=1, variable=self.end_scale_var, command=self._on_end_scale)
        self.end_scale.grid(row=1, column=1, sticky="ew", pady=(9, 0))
        self.end_entry = ttk.Entry(timeline, textvariable=self.end_entry_var, width=10)
        self.end_entry.grid(row=1, column=2, padx=(10, 0), pady=(9, 0))

        for entry in (self.start_entry, self.end_entry):
            entry.bind("<Return>", self._commit_entry_values)
            entry.bind("<FocusOut>", self._commit_entry_values)
        ttk.Label(timeline, textvariable=self.range_var, style="Muted.TLabel").grid(row=2, column=0, columnspan=3, sticky="w", pady=(10, 0))

        progress = ttk.LabelFrame(content, text=self.t("video_extractor.progress"), padding=10)
        progress.grid(row=2, column=0, sticky="nsew", pady=(12, 0))
        progress.columnconfigure(0, weight=1)
        ttk.Progressbar(progress, variable=self.progress_var, maximum=100).grid(row=0, column=0, sticky="ew")
        ttk.Label(progress, text=self.t("video_extractor.output_note"), style="Muted.TLabel", wraplength=720).grid(row=1, column=0, sticky="w", pady=(10, 0))
        ttk.Label(progress, textvariable=self.status_var, wraplength=720).grid(row=2, column=0, sticky="w", pady=(10, 0))
        ttk.Label(progress, textvariable=self.error_var, foreground=DANGER, wraplength=720).grid(row=3, column=0, sticky="w", pady=(6, 0))

        controls = ttk.Frame(content)
        controls.grid(row=3, column=0, sticky="e", pady=(12, 0))
        self.cancel_button = ttk.Button(controls, text=self.t("action.cancel"), command=self.cancel)
        self.cancel_button.pack(side="left", padx=(0, 6))
        self.extract_button = ttk.Button(controls, text=self.t("video_extractor.extract"), style="Primary.TButton", command=self.start_extraction, state="disabled")
        self.extract_button.pack(side="left")

    def _center(self) -> None:
        self.window.update_idletasks()
        width = self.window.winfo_reqwidth()
        height = self.window.winfo_reqheight()
        x = max(0, self.parent.winfo_rootx() + (self.parent.winfo_width() - width) // 2)
        y = max(0, self.parent.winfo_rooty() + (self.parent.winfo_height() - height) // 2)
        self.window.geometry(f"+{x}+{y}")

    def show(self) -> VideoRangeResult | None:
        self.window.grab_set()
        self.window.lift()
        self.window.focus_force()
        self.window.wait_window()
        return self.result

    def select_video(self) -> None:
        patterns = " ".join(f"*{suffix}" for suffix in sorted(VIDEO_EXTS))
        selected = filedialog.askopenfilename(
            parent=self.window,
            title=self.t("video_extractor.select_video"),
            filetypes=[(self.t("home.video"), patterns), (self.t("dialog.all_files"), "*.*")],
        )
        if not selected:
            return
        try:
            metadata = inspect_video(Path(selected))
        except (OSError, ValueError) as exc:
            self.metadata = None
            self.source_var.set(selected)
            self.extract_button.configure(state="disabled")
            self.error_var.set(self.t("video_extractor.error.read", error=exc))
            return
        self.metadata = metadata
        self.source_var.set(str(metadata.path))
        self.metadata_var.set(self.t(
            "video_extractor.info",
            duration=format_timestamp(metadata.duration_seconds),
            fps=f"{metadata.fps:.3f}".rstrip("0").rstrip("."),
            frames=metadata.frame_count,
            width=metadata.width,
            height=metadata.height,
        ))
        self.start_scale.configure(to=metadata.duration_seconds)
        self.end_scale.configure(to=metadata.duration_seconds)
        self.start_scale_var.set(0.0)
        self.end_scale_var.set(metadata.duration_seconds)
        self.start_entry_var.set("0.000")
        self.end_entry_var.set(f"{metadata.duration_seconds:.3f}")
        self._update_range_label()
        self.progress_var.set(0)
        self.status_var.set(self.t("video_extractor.status.ready"))
        self.error_var.set("")
        self.extract_button.configure(state="normal")

    def _minimum_step(self) -> float:
        return 1.0 / self.metadata.fps if self.metadata is not None else 0.001

    def _on_start_scale(self, value: str) -> None:
        if self.metadata is None:
            return
        end = self.end_scale_var.get()
        start = min(float(value), max(0.0, end - self._minimum_step()))
        self.start_scale_var.set(start)
        self.start_entry_var.set(f"{start:.3f}")
        self._update_range_label()

    def _on_end_scale(self, value: str) -> None:
        if self.metadata is None:
            return
        start = self.start_scale_var.get()
        end = max(float(value), min(self.metadata.duration_seconds, start + self._minimum_step()))
        end = min(end, self.metadata.duration_seconds)
        self.end_scale_var.set(end)
        self.end_entry_var.set(f"{end:.3f}")
        self._update_range_label()

    def _commit_entry_values(self, _event=None) -> None:
        if self.metadata is None:
            return
        try:
            start = float(self.start_entry_var.get().strip().replace(",", "."))
            end = float(self.end_entry_var.get().strip().replace(",", "."))
            validate_time_range(self.metadata, start, end)
        except (TypeError, ValueError):
            self.error_var.set(self.t("video_extractor.error.range"))
            return
        self.start_scale_var.set(start)
        self.end_scale_var.set(min(end, self.metadata.duration_seconds))
        self.start_entry_var.set(f"{start:.3f}")
        self.end_entry_var.set(f"{min(end, self.metadata.duration_seconds):.3f}")
        self.error_var.set("")
        self._update_range_label()

    def _update_range_label(self) -> None:
        if self.metadata is None:
            self.range_var.set(self.t("video_extractor.range.empty"))
            return
        self.range_var.set(self.t(
            "video_extractor.range",
            start=format_timestamp(self.start_scale_var.get()),
            end=format_timestamp(self.end_scale_var.get()),
        ))

    def start_extraction(self) -> None:
        if self.metadata is None or self._worker is not None:
            return
        self._commit_entry_values()
        if self.error_var.get():
            return
        start = self.start_scale_var.get()
        end = self.end_scale_var.get()
        try:
            validate_time_range(self.metadata, start, end)
        except ValueError:
            self.error_var.set(self.t("video_extractor.error.range"))
            return
        output_dir = unique_output_dir(default_range_output_dir(self.metadata.path, start, end))
        self._cancel_event.clear()
        self.progress_var.set(0)
        self.error_var.set("")
        self.status_var.set(self.t("video_extractor.status.extracting", current=0, total="?"))
        self._set_busy(True)
        self._worker = threading.Thread(target=self._extract_worker, args=(start, end, output_dir), daemon=True)
        self._worker.start()
        self.window.after(50, self._poll_events)

    def _extract_worker(self, start: float, end: float, output_dir: Path) -> None:
        try:
            result = extract_video_range(
                self.metadata.path,
                start,
                end,
                output_dir,
                progress=lambda current, total: self._events.put(("progress", (current, total))),
                cancelled=self._cancel_event.is_set,
            )
        except ExtractionCancelled:
            self._events.put(("cancelled", None))
        except Exception as exc:
            self._events.put(("error", exc))
        else:
            self._events.put(("done", result))

    def _poll_events(self) -> None:
        while True:
            try:
                kind, payload = self._events.get_nowait()
            except queue.Empty:
                break
            if kind == "progress":
                current, total = payload
                self.progress_var.set((current / total) * 100)
                self.status_var.set(self.t("video_extractor.status.extracting", current=current, total=total))
            elif kind == "done":
                self._finish(payload)
                return
            elif kind == "cancelled":
                self._worker = None
                self._set_busy(False)
                self.status_var.set(self.t("video_extractor.status.cancelled"))
                return
            elif kind == "error":
                self._worker = None
                self._set_busy(False)
                self.error_var.set(self.t("video_extractor.error.extract", error=payload))
                return
        if self._worker is not None and self._worker.is_alive():
            self.window.after(50, self._poll_events)
        elif self._worker is not None:
            self.window.after(50, self._poll_events)

    def _finish(self, result: VideoRangeResult) -> None:
        self.result = result
        self._worker = None
        self._set_busy(False)
        self.progress_var.set(100)
        self.status_var.set(self.t("video_extractor.status.done", count=result.frame_count, path=result.output_dir))
        try:
            os.startfile(str(result.output_dir))
        except OSError as exc:
            self.error_var.set(self.t("status.open_folder_failed", error=exc))

    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        self.select_button.configure(state=state)
        self.start_scale.configure(state=state)
        self.end_scale.configure(state=state)
        self.start_entry.configure(state=state)
        self.end_entry.configure(state=state)
        self.extract_button.configure(state=state if self.metadata is not None else "disabled")
        self.cancel_button.configure(text=self.t("video_extractor.cancel_extraction") if busy else self.t("action.cancel"), state="normal")

    def cancel(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            self._cancel_event.set()
            self.cancel_button.configure(state="disabled")
            self.status_var.set(self.t("video_extractor.status.cancelling"))
            return
        self.window.destroy()
