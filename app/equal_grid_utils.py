
from __future__ import annotations

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0

from collections import deque
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image

BACKGROUND_COLORS = {
    "black": (0, 0, 0, 255),
    "green": (0, 255, 0, 255),
    "transparent": (0, 0, 0, 0),
}


def _bounds(total: int, parts: int) -> list[int]:
    return [round(i * total / parts) for i in range(parts + 1)]


def _border_connected(mask: np.ndarray) -> np.ndarray:
    h, w = mask.shape
    visited = np.zeros((h, w), dtype=bool)
    q: deque[tuple[int, int]] = deque()
    for x in range(w):
        if mask[0, x]:
            q.append((0, x))
        if mask[h - 1, x]:
            q.append((h - 1, x))
    for y in range(h):
        if mask[y, 0]:
            q.append((y, 0))
        if mask[y, w - 1]:
            q.append((y, w - 1))
    while q:
        y, x = q.popleft()
        if y < 0 or y >= h or x < 0 or x >= w or visited[y, x] or not mask[y, x]:
            continue
        visited[y, x] = True
        q.append((y - 1, x))
        q.append((y + 1, x))
        q.append((y, x - 1))
        q.append((y, x + 1))
    return visited


def _green_bg_mask(rgb: np.ndarray) -> np.ndarray:
    data = rgb.astype(np.int16)
    r = data[..., 0]
    g = data[..., 1]
    b = data[..., 2]
    return (g >= 130) & (g - r >= 55) & (g - b >= 55)


def _detect_background_mode(rgba: np.ndarray) -> str:
    if int(rgba[..., 3].min()) < 255:
        return "transparent"
    h, w = rgba.shape[:2]
    sample = np.concatenate([
        rgba[: min(8, h), :, :3].reshape(-1, 3),
        rgba[max(0, h - 8):, :, :3].reshape(-1, 3),
        rgba[:, : min(8, w), :3].reshape(-1, 3),
        rgba[:, max(0, w - 8):, :3].reshape(-1, 3),
    ], axis=0)
    green_ratio = float(_green_bg_mask(sample.reshape(-1, 1, 3)).mean())
    near_black_ratio = float((sample.max(axis=1) <= 24).mean())
    return "green" if green_ratio > near_black_ratio else "black"


def _subject_mask(rgba: np.ndarray, bg_mode: str, alpha_threshold: int, black_threshold: int) -> np.ndarray:
    if bg_mode == "auto":
        bg_mode = _detect_background_mode(rgba)
    if bg_mode == "transparent":
        return rgba[..., 3] > alpha_threshold
    rgb = rgba[..., :3]
    if bg_mode == "green":
        return ~_border_connected(_green_bg_mask(rgb))
    # black/default: only border-connected near-black is background, so dark internal details are preserved.
    near_black = rgb.max(axis=2) <= black_threshold
    return ~_border_connected(near_black)


def _blank(width: int, height: int, bg_mode: str) -> np.ndarray:
    color = BACKGROUND_COLORS.get(bg_mode, BACKGROUND_COLORS["black"])
    arr = np.zeros((height, width, 4), dtype=np.uint8)
    arr[:, :] = np.array(color, dtype=np.uint8)
    return arr


def _paste_subject(out: np.ndarray, src: np.ndarray, mask: np.ndarray, dx: int, dy: int) -> bool:
    yy, xx = np.where(mask)
    if len(xx) == 0:
        return False
    dst_x = xx + dx
    dst_y = yy + dy
    valid = (dst_x >= 0) & (dst_x < out.shape[1]) & (dst_y >= 0) & (dst_y < out.shape[0])
    if np.any(valid):
        out[dst_y[valid], dst_x[valid], :] = src[yy[valid], xx[valid], :]
    return bool(np.all(valid))


def _weighted_center(mask: np.ndarray, rgba: np.ndarray, x_offset: int = 0, y_offset: int = 0) -> tuple[float, float]:
    yy, xx = np.where(mask)
    if len(xx) == 0:
        raise ValueError("Subject detection failed")
    alpha = rgba[..., 3].astype(np.float32)
    bright = rgba[..., :3].max(axis=2).astype(np.float32)
    weights = np.maximum(alpha[mask], 1.0) * np.maximum(bright[mask], 1.0) / 255.0
    if float(weights.sum()) <= 0:
        weights = np.ones_like(weights)
    cx = float(((xx + x_offset) * weights).sum() / weights.sum())
    cy = float(((yy + y_offset) * weights).sum() / weights.sum())
    return cx, cy


def normalize_equal_grid(
    image_path: Path,
    output_path: Path,
    rows: int,
    cols: int,
    cell_width: int = 0,
    cell_height: int = 0,
    background_mode: str = "auto",
    assignment_mode: str = "cell",
    alpha_threshold: int = 8,
    black_threshold: int = 20,
) -> dict[str, Any]:
    image_path = Path(image_path)
    output_path = Path(output_path)
    if rows <= 0 or cols <= 0:
        raise ValueError("rows and cols must be greater than 0")
    with Image.open(image_path) as src_img:
        src = src_img.convert("RGBA")
    rgba = np.array(src, dtype=np.uint8)
    src_w, src_h = src.size
    x_bounds = _bounds(src_w, cols)
    y_bounds = _bounds(src_h, rows)
    source_cell_widths = [x_bounds[i + 1] - x_bounds[i] for i in range(cols)]
    source_cell_heights = [y_bounds[i + 1] - y_bounds[i] for i in range(rows)]
    bg = _detect_background_mode(rgba) if background_mode == "auto" else background_mode
    if bg not in BACKGROUND_COLORS:
        raise ValueError(f"Unknown background mode: {background_mode}")
    max_w = max(source_cell_widths)
    max_h = max(source_cell_heights)
    if cell_width <= 0:
        cell_width = int(np.ceil((max_w + max(48, max_w * 0.25)) / 8.0) * 8)
    if cell_height <= 0:
        cell_height = int(np.ceil((max_h + max(40, max_h * 0.25)) / 8.0) * 8)
    out = _blank(cell_width * cols, cell_height * rows, bg)
    placements: list[dict[str, Any]] = []
    failed: list[int] = []
    near_edges: list[int] = []
    method = assignment_mode
    if method == "component":
        global_mask = _subject_mask(rgba, bg, alpha_threshold, black_threshold).astype(np.uint8)
        num, labels, stats, cents = cv2.connectedComponentsWithStats(global_mask, 8)
        frame_masks = [np.zeros((src_h, src_w), dtype=bool) for _ in range(rows * cols)]
        centers = [((c + 0.5) * src_w / cols, (r + 0.5) * src_h / rows) for r in range(rows) for c in range(cols)]
        for comp in range(1, num):
            area = int(stats[comp, cv2.CC_STAT_AREA])
            if area <= 0:
                continue
            cx, cy = float(cents[comp][0]), float(cents[comp][1])
            target = min(range(len(centers)), key=lambda i: (cx - centers[i][0]) ** 2 + (cy - centers[i][1]) ** 2)
            frame_masks[target][labels == comp] = True
        for i, mask in enumerate(frame_masks):
            frame_no = i + 1
            row = i // cols
            col = i % cols
            if not mask.any():
                failed.append(frame_no)
                continue
            cx, _cy = _weighted_center(mask, rgba)
            dx = int(round((col + 0.5) * cell_width - cx))
            source_center_y = (row + 0.5) * src_h / rows
            dy = int(round((row + 0.5) * cell_height - source_center_y))
            ok = _paste_subject(out, rgba, mask, dx, dy)
            yy, xx = np.where(mask)
            dst_x = xx + dx
            dst_y = yy + dy
            bbox = (int(dst_x.min() - col * cell_width), int(dst_y.min() - row * cell_height), int(dst_x.max() + 1 - col * cell_width), int(dst_y.max() + 1 - row * cell_height))
            edge = (not ok) or bbox[0] < 4 or bbox[1] < 4 or bbox[2] > cell_width - 4 or bbox[3] > cell_height - 4
            if edge:
                near_edges.append(frame_no)
            placements.append({"frame": frame_no, "row": row + 1, "col": col + 1, "bbox": bbox, "dx": dx, "dy": dy, "near_edge": edge})
    else:
        for row in range(rows):
            for col in range(cols):
                frame_no = row * cols + col + 1
                x0, x1 = x_bounds[col], x_bounds[col + 1]
                y0, y1 = y_bounds[row], y_bounds[row + 1]
                cell = rgba[y0:y1, x0:x1, :]
                mask = _subject_mask(cell, bg, alpha_threshold, black_threshold)
                if not mask.any():
                    failed.append(frame_no)
                    continue
                cx, _cy = _weighted_center(mask, cell)
                paste_x = col * cell_width + int(round(cell_width / 2.0 - cx))
                paste_y = row * cell_height + int(round((cell_height - cell.shape[0]) / 2.0))
                local_out = out[row * cell_height:(row + 1) * cell_height, col * cell_width:(col + 1) * cell_width, :]
                ok = _paste_subject(local_out, cell, mask, paste_x - col * cell_width, paste_y - row * cell_height)
                yy, xx = np.where(mask)
                dst_x = xx + paste_x - col * cell_width
                dst_y = yy + paste_y - row * cell_height
                bbox = (int(dst_x.min()), int(dst_y.min()), int(dst_x.max() + 1), int(dst_y.max() + 1))
                edge = (not ok) or bbox[0] < 4 or bbox[1] < 4 or bbox[2] > cell_width - 4 or bbox[3] > cell_height - 4
                if edge:
                    near_edges.append(frame_no)
                placements.append({"frame": frame_no, "row": row + 1, "col": col + 1, "bbox": bbox, "paste_x": paste_x - col * cell_width, "paste_y": paste_y - row * cell_height, "near_edge": edge})
    if failed:
        raise ValueError("Subject detection failed in frames: " + ", ".join(str(x) for x in failed))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(out, "RGBA").save(output_path)
    report_path = output_path.with_suffix(".equal_grid_report.txt")
    lines = [
        "GameAssetKeyer equal-grid report",
        f"source: {image_path}",
        f"output: {output_path}",
        f"source_size: {src_w}x{src_h}",
        f"layout: {cols} columns x {rows} rows",
        f"source_cell_widths: {source_cell_widths}",
        f"source_cell_heights: {source_cell_heights}",
        f"output_size: {cell_width * cols}x{cell_height * rows}",
        f"output_cell_size: {cell_width}x{cell_height}",
        f"background_mode: {bg}",
        f"assignment_mode: {method}",
        f"near_edge_frames: {sorted(set(near_edges)) if near_edges else 'none'}",
        "",
        "placements:",
    ]
    for item in placements:
        lines.append(str(item))
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return {
        "output_path": str(output_path),
        "report_path": str(report_path),
        "source_size": [src_w, src_h],
        "rows": rows,
        "cols": cols,
        "cell_width": cell_width,
        "cell_height": cell_height,
        "frame_count": rows * cols,
        "background_mode": bg,
        "assignment_mode": method,
        "near_edge_frames": sorted(set(near_edges)),
    }
