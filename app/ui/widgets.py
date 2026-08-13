from __future__ import annotations

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0

import tkinter as tk
from tkinter import ttk
from typing import Callable

from PIL import Image, ImageTk


class ScrollableFrame(ttk.Frame):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(self, width=1, height=1, highlightthickness=0, background="#252a31")
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.content = ttk.Frame(self.canvas)
        self.window_id = self.canvas.create_window((0, 0), window=self.content, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scrollbar.grid(row=0, column=1, sticky="ns")
        self.content.bind("<Configure>", self._update_scrollregion)
        self.canvas.bind("<Configure>", self._resize_content)
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel, add="+")

    def _update_scrollregion(self, _event=None) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _resize_content(self, event) -> None:
        self.canvas.itemconfigure(self.window_id, width=event.width)

    def _on_mousewheel(self, event) -> None:
        if self.winfo_containing(event.x_root, event.y_root) in self.winfo_children() or self.winfo_containing(event.x_root, event.y_root) == self.canvas:
            self.canvas.yview_scroll(int(-event.delta / 120), "units")


class ImageCanvas(tk.Canvas):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, background="#171a1f", highlightthickness=0, **kwargs)
        self.source_image: Image.Image | None = None
        self._photo: ImageTk.PhotoImage | None = None
        self.display_box = (0, 0, 0, 0)
        self.eyedropper_callback: Callable[[tuple[int, int, int] | None], None] | None = None
        self.eyedropper_miss_callback: Callable[[], None] | None = None
        self.bind("<Configure>", lambda _event: self.redraw())
        self.bind("<Button-1>", self._on_click)

    def set_image(self, image: Image.Image | None) -> None:
        self.source_image = image.convert("RGBA") if image is not None else None
        self.redraw()

    def enable_eyedropper(
        self,
        callback: Callable[[tuple[int, int, int] | None], None],
        miss_callback: Callable[[], None] | None = None,
    ) -> None:
        self.eyedropper_callback = callback
        self.eyedropper_miss_callback = miss_callback
        self.configure(cursor="crosshair")

    def cancel_eyedropper(self) -> None:
        self.eyedropper_callback = None
        self.eyedropper_miss_callback = None
        self.configure(cursor="")

    def canvas_to_image(self, x: int, y: int) -> tuple[int, int] | None:
        if self.source_image is None:
            return None
        left, top, right, bottom = self.display_box
        if not (left <= x < right and top <= y < bottom):
            return None
        width, height = self.source_image.size
        image_x = min(width - 1, int((x - left) * width / max(1, right - left)))
        image_y = min(height - 1, int((y - top) * height / max(1, bottom - top)))
        return image_x, image_y

    def _on_click(self, event) -> None:
        if self.eyedropper_callback is None:
            return
        if self.source_image is None:
            if self.eyedropper_miss_callback is not None:
                self.eyedropper_miss_callback()
            return
        point = self.canvas_to_image(event.x, event.y)
        if point is None:
            if self.eyedropper_miss_callback is not None:
                self.eyedropper_miss_callback()
            return
        pixel = self.source_image.getpixel(point)
        callback = self.eyedropper_callback
        self.cancel_eyedropper()
        callback(None if pixel[3] == 0 else pixel[:3])

    def _draw_checkerboard(self, left: int, top: int, width: int, height: int, size: int = 12) -> None:
        colors = ("#c7cbd1", "#eef0f3")
        for y in range(top, top + height, size):
            for x in range(left, left + width, size):
                color = colors[((x - left) // size + (y - top) // size) % 2]
                self.create_rectangle(x, y, min(x + size, left + width), min(y + size, top + height), fill=color, outline="")

    def redraw(self) -> None:
        self.delete("all")
        if self.source_image is None:
            self.display_box = (0, 0, 0, 0)
            return
        canvas_width = max(1, self.winfo_width())
        canvas_height = max(1, self.winfo_height())
        image_width, image_height = self.source_image.size
        scale = min((canvas_width - 24) / image_width, (canvas_height - 24) / image_height)
        scale = max(0.01, scale)
        display_width = max(1, int(image_width * scale))
        display_height = max(1, int(image_height * scale))
        left = (canvas_width - display_width) // 2
        top = (canvas_height - display_height) // 2
        self.display_box = (left, top, left + display_width, top + display_height)
        self._draw_checkerboard(left, top, display_width, display_height)
        resized = self.source_image.resize((display_width, display_height), Image.Resampling.LANCZOS)
        self._photo = ImageTk.PhotoImage(resized)
        self.create_image(left, top, image=self._photo, anchor="nw")
