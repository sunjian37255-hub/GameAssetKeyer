from __future__ import annotations

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0

import tkinter as tk
from tkinter import ttk
from typing import Callable

from PIL import Image, ImageTk

from .theme import BG_INPUT, BG_ROOT, CHECKER_DARK, CHECKER_LIGHT


class ScrollableFrame(ttk.Frame):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(self, width=1, height=1, highlightthickness=0, background=BG_INPUT)
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
    LOUPE_ZOOM = 5
    LOUPE_SAMPLE_SIZE = 21
    LOUPE_TAG = "eyedropper_loupe"

    def __init__(self, parent, **kwargs):
        super().__init__(parent, background=BG_ROOT, highlightthickness=0, **kwargs)
        self.source_image: Image.Image | None = None
        self._photo: ImageTk.PhotoImage | None = None
        self._loupe_photo: ImageTk.PhotoImage | None = None
        self.display_box = (0, 0, 0, 0)
        self.eyedropper_callback: Callable[[tuple[int, int, int] | None], None] | None = None
        self.eyedropper_miss_callback: Callable[[], None] | None = None
        self.bind("<Configure>", lambda _event: self.redraw())
        self.bind("<Button-1>", self._on_click)
        self.bind("<Motion>", self._on_motion)
        self.bind("<Leave>", self._hide_loupe)

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
        self._hide_loupe()

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

    def _on_motion(self, event) -> None:
        if self.eyedropper_callback is None:
            return
        point = self.canvas_to_image(event.x, event.y)
        if point is None:
            self._hide_loupe()
            return
        self._draw_loupe(event.x, event.y, point)

    def _draw_loupe(self, mouse_x: int, mouse_y: int, point: tuple[int, int]) -> None:
        if self.source_image is None:
            self._hide_loupe()
            return
        sample_size = self.LOUPE_SAMPLE_SIZE
        radius = sample_size // 2
        image_x, image_y = point
        sample = Image.new("RGBA", (sample_size, sample_size), (0, 0, 0, 0))
        source_left = max(0, image_x - radius)
        source_top = max(0, image_y - radius)
        source_right = min(self.source_image.width, image_x + radius + 1)
        source_bottom = min(self.source_image.height, image_y + radius + 1)
        region = self.source_image.crop((source_left, source_top, source_right, source_bottom))
        sample.alpha_composite(region, (source_left - image_x + radius, source_top - image_y + radius))

        checker = Image.new("RGBA", sample.size, CHECKER_DARK)
        checker_size = 2
        for y in range(0, sample_size, checker_size):
            for x in range(0, sample_size, checker_size):
                if (x // checker_size + y // checker_size) % 2:
                    checker.paste(CHECKER_LIGHT, (x, y, min(x + checker_size, sample_size), min(y + checker_size, sample_size)))
        checker.alpha_composite(sample)

        loupe_size = sample_size * self.LOUPE_ZOOM
        enlarged = checker.resize((loupe_size, loupe_size), Image.Resampling.NEAREST)
        self._loupe_photo = ImageTk.PhotoImage(enlarged)
        canvas_width = max(1, self.winfo_width())
        canvas_height = max(1, self.winfo_height())
        gap = 16
        left = mouse_x + gap
        top = mouse_y + gap
        if left + loupe_size + 3 > canvas_width:
            left = mouse_x - loupe_size - gap
        if top + loupe_size + 3 > canvas_height:
            top = mouse_y - loupe_size - gap
        left = max(2, min(left, max(2, canvas_width - loupe_size - 3)))
        top = max(2, min(top, max(2, canvas_height - loupe_size - 3)))

        self.delete(self.LOUPE_TAG)
        tags = (self.LOUPE_TAG,)
        self.create_image(left, top, image=self._loupe_photo, anchor="nw", tags=tags)
        self.create_rectangle(left, top, left + loupe_size, top + loupe_size, outline="#FFFFFF", width=3, tags=tags)
        center = radius * self.LOUPE_ZOOM
        self.create_rectangle(
            left + center,
            top + center,
            left + center + self.LOUPE_ZOOM,
            top + center + self.LOUPE_ZOOM,
            outline="#FF3B30",
            width=2,
            tags=tags,
        )
        self.create_text(left + loupe_size - 6, top + 6, text="5×", fill="#FFFFFF", anchor="ne", tags=tags)

    def _hide_loupe(self, _event=None) -> None:
        self.delete(self.LOUPE_TAG)
        self._loupe_photo = None

    def _draw_checkerboard(self, left: int, top: int, width: int, height: int, size: int = 12) -> None:
        colors = (CHECKER_DARK, CHECKER_LIGHT)
        for y in range(top, top + height, size):
            for x in range(left, left + width, size):
                color = colors[((x - left) // size + (y - top) // size) % 2]
                self.create_rectangle(x, y, min(x + size, left + width), min(y + size, top + height), fill=color, outline="")

    def redraw(self) -> None:
        self.delete("all")
        self._loupe_photo = None
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
