from __future__ import annotations

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0

import json
from pathlib import Path
from statistics import median
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


def frame_anchor(bbox, mode: str):
    left, top, right, bottom = bbox
    center_x = (left + right) / 2.0
    center_y = (top + bottom) / 2.0
    if mode == "bottom_center":
        return center_x, float(bottom)
    return center_x, center_y


def shift_rgba(image: Image.Image, dx: int, dy: int) -> Image.Image:
    src = image.convert("RGBA")
    width, height = src.size
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    src_x = max(0, -dx)
    src_y = max(0, -dy)
    dst_x = max(0, dx)
    dst_y = max(0, dy)
    copy_w = min(width - src_x, width - dst_x)
    copy_h = min(height - src_y, height - dst_y)
    if copy_w <= 0 or copy_h <= 0:
        return canvas
    region = src.crop((src_x, src_y, src_x + copy_w, src_y + copy_h))
    canvas.alpha_composite(region, (dst_x, dst_y))
    return canvas


def align_frames(input_dir: Path, output_dir: Path, mode: str = "center", alpha_threshold: int = 8, custom_anchor: tuple[float, float] | None = None, source_signature: str = "") -> dict[str, Any]:
    frames = sorted(input_dir.glob("frame_*.png"))
    if not frames:
        raise ValueError("没有找到帧图片")
    output_dir.mkdir(parents=True, exist_ok=True)
    for old in output_dir.glob("frame_*.png"):
        old.unlink()

    if mode == "none":
        offsets = {}
        for path in frames:
            with Image.open(path) as img:
                img.convert("RGBA").save(output_dir / path.name)
            offsets[path.name] = {"dx": 0, "dy": 0, "source_anchor": None}
        meta = {
            "align_mode": mode,
            "alpha_threshold": alpha_threshold,
            "target_anchor": None,
            "per_frame_offsets": offsets,
            "frame_count": len(frames),
            "source_dir": str(input_dir),
            "output_dir": str(output_dir),
            "source_signature": source_signature,
            "result_signature": uuid4().hex,
        }
        (output_dir / "align_metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        return meta

    anchors: dict[str, tuple[float, float] | None] = {}
    xs: list[float] = []
    ys: list[float] = []
    for path in frames:
        with Image.open(path) as img:
            bbox = alpha_bbox(img, alpha_threshold)
        if bbox is None:
            anchors[path.name] = None
            continue
        anchor = frame_anchor(bbox, "bottom_center" if mode == "bottom_center" else "center")
        anchors[path.name] = anchor
        xs.append(anchor[0])
        ys.append(anchor[1])

    if mode == "custom":
        if custom_anchor is None:
            raise ValueError("自定义锚点需要 anchor_x 和 anchor_y")
        target_anchor = (float(custom_anchor[0]), float(custom_anchor[1]))
    else:
        if not xs or not ys:
            raise ValueError("没有找到可用于对齐的 Alpha 区域")
        target_anchor = (float(median(xs)), float(median(ys)))

    offsets = {}
    for path in frames:
        source_anchor = anchors[path.name]
        if source_anchor is None:
            dx = dy = 0
        else:
            dx = int(round(target_anchor[0] - source_anchor[0]))
            dy = int(round(target_anchor[1] - source_anchor[1]))
        with Image.open(path) as img:
            shifted = shift_rgba(img, dx, dy)
        shifted.save(output_dir / path.name)
        offsets[path.name] = {
            "dx": dx,
            "dy": dy,
            "source_anchor": list(source_anchor) if source_anchor is not None else None,
        }

    meta = {
        "align_mode": mode,
        "alpha_threshold": alpha_threshold,
        "target_anchor": list(target_anchor),
        "per_frame_offsets": offsets,
        "frame_count": len(frames),
        "source_dir": str(input_dir),
        "output_dir": str(output_dir),
        "source_signature": source_signature,
        "result_signature": uuid4().hex,
    }
    (output_dir / "align_metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta
