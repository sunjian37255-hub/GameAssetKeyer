from __future__ import annotations

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np
from PIL import Image


def alpha_bbox(image: Image.Image, threshold: int = 8):
    alpha = np.array(image.convert("RGBA"))[..., 3]
    ys, xs = np.where(alpha > threshold)
    if len(xs) == 0 or len(ys) == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def compute_global_bbox(input_dir: Path, threshold: int = 8, padding: int = 0):
    boxes = []
    for path in sorted(input_dir.glob("frame_*.png")):
        with Image.open(path) as img:
            box = alpha_bbox(img, threshold)
            if box:
                boxes.append(box)
    if not boxes:
        raise ValueError("没有找到可见的 Alpha 像素")
    left = min(b[0] for b in boxes)
    top = min(b[1] for b in boxes)
    right = max(b[2] for b in boxes)
    bottom = max(b[3] for b in boxes)
    with Image.open(sorted(input_dir.glob("frame_*.png"))[0]) as sample:
        width, height = sample.size
    left = max(0, left - padding)
    top = max(0, top - padding)
    right = min(width, right + padding)
    bottom = min(height, bottom + padding)
    return left, top, right, bottom


def trim_frames(input_dir: Path, output_dir: Path, threshold: int = 8, padding: int = 0, source_signature: str = "") -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    for old in output_dir.glob("frame_*.png"):
        old.unlink()
    bbox = compute_global_bbox(input_dir, threshold, padding)
    count = 0
    for path in sorted(input_dir.glob("frame_*.png")):
        with Image.open(path) as img:
            img.convert("RGBA").crop(bbox).save(output_dir / path.name)
        count += 1
    meta = {
        "source_dir": str(input_dir),
        "output_dir": str(output_dir),
        "bbox": list(bbox),
        "threshold": threshold,
        "padding": padding,
        "frame_count": count,
        "source_signature": source_signature,
        "result_signature": uuid4().hex,
    }
    (output_dir / "trim_metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta
