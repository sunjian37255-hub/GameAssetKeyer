from __future__ import annotations

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0

import math
import shutil
from pathlib import Path
from typing import Any

import cv2


VIDEO_EXTS = {".mp4", ".avi", ".mov", ".mkv", ".webm", ".m4v"}


def _write_png(path: Path, frame) -> None:
    ok, data = cv2.imencode(".png", frame)
    if not ok:
        raise RuntimeError(f"Failed to encode frame: {path}")
    path.write_bytes(data.tobytes())


def _open_capture(video_path: Path, output_dir: Path):
    cap = cv2.VideoCapture(str(video_path))
    temp_path: Path | None = None
    if cap.isOpened():
        return cap, temp_path

    cap.release()
    temp_path = output_dir / "_video_temp_input.mp4"
    shutil.copy2(video_path, temp_path)
    cap = cv2.VideoCapture(str(temp_path))
    if not cap.isOpened():
        cap.release()
        raise ValueError(f"Cannot open video file: {video_path}")
    return cap, temp_path


def split_video(video_path: Path, frame_interval: int, output_dir: Path) -> dict[str, Any]:
    video_path = video_path.resolve()
    if not video_path.exists():
        raise FileNotFoundError(str(video_path))
    if video_path.suffix.lower() not in VIDEO_EXTS:
        raise ValueError(f"Unsupported video format: {video_path.suffix}")
    if frame_interval <= 0:
        raise ValueError("Frame interval must be greater than 0")

    output_dir.mkdir(parents=True, exist_ok=True)
    for old in output_dir.glob("frame_*.png"):
        old.unlink()

    cap, temp_path = _open_capture(video_path, output_dir)
    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)

        saved = 0
        saved_indices: set[int] = set()
        index = 0
        last_index = -1
        last_frame = None
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            last_index = index
            last_frame = frame.copy()
            if index == 0 or index % frame_interval == 0:
                saved += 1
                _write_png(output_dir / f"frame_{saved:06d}.png", frame)
                saved_indices.add(index)
            index += 1

        if last_frame is not None and last_index not in saved_indices:
            saved += 1
            _write_png(output_dir / f"frame_{saved:06d}.png", last_frame)
            saved_indices.add(last_index)
    finally:
        cap.release()
        if temp_path is not None:
            try:
                temp_path.unlink()
            except OSError:
                pass

    if saved == 0:
        raise ValueError("No frames were extracted from the video")

    return {
        "frame_count": saved,
        "source_total_frames": total_frames,
        "fps": fps,
        "width": width,
        "height": height,
        "frame_interval": frame_interval,
        "first_frame_included": 0 in saved_indices,
        "last_frame_included": last_index in saved_indices,
        "last_frame_index": last_index,
        "duration_seconds": (total_frames / fps) if fps > 0 and total_frames > 0 else 0,
        "suggested_rows_for_8_cols": math.ceil(saved / 8),
    }
