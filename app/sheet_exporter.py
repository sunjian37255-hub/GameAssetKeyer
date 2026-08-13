from __future__ import annotations

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0

import json
from pathlib import Path
from typing import Any

from PIL import Image

from .color_key_processor import make_dark_preview


def export_sheet(input_dir: Path, output_dir: Path, rows: int, cols: int, output_name: str = "sheet_transparent.png") -> dict[str, Any]:
    frames = sorted(input_dir.glob("frame_*.png"))
    if not frames:
        raise ValueError("没有找到帧图片")
    needed = rows * cols
    with Image.open(frames[0]) as first:
        cell_w, cell_h = first.convert("RGBA").size
    sheet = Image.new("RGBA", (cols * cell_w, rows * cell_h), (0, 0, 0, 0))
    for index, path in enumerate(frames[:needed]):
        with Image.open(path) as src:
            frame = src.convert("RGBA")
        if frame.size != (cell_w, cell_h):
            canvas = Image.new("RGBA", (cell_w, cell_h), (0, 0, 0, 0))
            x = (cell_w - frame.size[0]) // 2
            y = (cell_h - frame.size[1]) // 2
            canvas.alpha_composite(frame, (x, y))
            frame = canvas
        row = index // cols
        col = index % cols
        sheet.alpha_composite(frame, (col * cell_w, row * cell_h))
    output_dir.mkdir(parents=True, exist_ok=True)
    sheet_path = output_dir / output_name
    preview_path = output_dir / "sheet_on_dark_preview.png"
    sheet.save(sheet_path)
    make_dark_preview(sheet).save(preview_path)
    meta = {
        "input_dir": str(input_dir),
        "rows": rows,
        "cols": cols,
        "frame_count": min(needed, len(frames)),
        "cell_count": needed,
        "source_frame_count": len(frames),
        "blank_cells": max(0, needed - len(frames)),
        "cell_size": [cell_w, cell_h],
        "sheet": str(sheet_path),
        "preview": str(preview_path),
    }
    (output_dir / "metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta
