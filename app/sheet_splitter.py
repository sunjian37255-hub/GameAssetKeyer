from __future__ import annotations

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0

from pathlib import Path
from PIL import Image


def split_sheet(image_path: Path, rows: int, cols: int, output_dir: Path) -> int:
    output_dir.mkdir(parents=True, exist_ok=True)
    for old in output_dir.glob("frame_*.png"):
        old.unlink()
    with Image.open(image_path) as src:
        image = src.convert("RGBA")
        width, height = image.size
        if width < cols or height < rows:
            raise ValueError(f"Image too small for {rows}x{cols}: {width}x{height}")
        cell_w = width // cols
        cell_h = height // rows
        index = 1
        for row in range(rows):
            for col in range(cols):
                left = col * cell_w
                top = row * cell_h
                right = (col + 1) * cell_w if col < cols - 1 else width
                bottom = (row + 1) * cell_h if row < rows - 1 else height
                frame = image.crop((left, top, right, bottom))
                frame.save(output_dir / f"frame_{index:06d}.png")
                index += 1
    return rows * cols
