from __future__ import annotations

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0

import math
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import cv2


VIDEO_EXTS = {".mp4", ".avi", ".mov", ".mkv", ".webm", ".m4v"}


@dataclass(frozen=True)
class VideoMetadata:
    path: Path
    fps: float
    frame_count: int
    width: int
    height: int
    duration_seconds: float


@dataclass(frozen=True)
class VideoRangeResult:
    output_dir: Path
    frame_count: int
    first_source_frame: int
    last_source_frame: int
    start_seconds: float
    end_seconds: float


class ExtractionCancelled(RuntimeError):
    pass


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


def _validate_video_path(video_path: Path) -> Path:
    video_path = video_path.resolve()
    if not video_path.is_file():
        raise FileNotFoundError(str(video_path))
    if video_path.suffix.lower() not in VIDEO_EXTS:
        raise ValueError(f"Unsupported video format: {video_path.suffix}")
    return video_path


def inspect_video(video_path: Path) -> VideoMetadata:
    video_path = _validate_video_path(video_path)
    with tempfile.TemporaryDirectory(prefix="gameassetkeyer-video-probe-") as temp:
        cap, _temp_path = _open_capture(video_path, Path(temp))
        try:
            fps = float(cap.get(cv2.CAP_PROP_FPS) or 0)
            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        finally:
            cap.release()
    if fps <= 0 or frame_count <= 0 or width <= 0 or height <= 0:
        raise ValueError(f"Invalid video metadata: {video_path}")
    return VideoMetadata(video_path, fps, frame_count, width, height, frame_count / fps)


def validate_time_range(metadata: VideoMetadata, start_seconds: float, end_seconds: float) -> tuple[int, int]:
    start = float(start_seconds)
    end = float(end_seconds)
    if not math.isfinite(start) or not math.isfinite(end):
        raise ValueError("Start and end times must be finite")
    tolerance = 0.5 / metadata.fps
    if start < 0 or end <= start or start >= metadata.duration_seconds or end > metadata.duration_seconds + tolerance:
        raise ValueError("The selected time range is outside the video duration")
    end = min(end, metadata.duration_seconds)
    first_frame = min(metadata.frame_count - 1, max(0, math.floor(start * metadata.fps + 1e-9)))
    end_frame = min(metadata.frame_count, max(first_frame + 1, math.ceil(end * metadata.fps - 1e-9)))
    return first_frame, end_frame


def default_range_output_dir(video_path: Path, start_seconds: float, end_seconds: float) -> Path:
    video_path = Path(video_path)
    start_ms = max(0, round(float(start_seconds) * 1000))
    end_ms = max(0, round(float(end_seconds) * 1000))
    return video_path.with_name(f"{video_path.stem}_frames_{start_ms:07d}ms-{end_ms:07d}ms")


def unique_output_dir(preferred: Path) -> Path:
    preferred = Path(preferred)
    if not preferred.exists():
        return preferred
    index = 2
    while True:
        candidate = preferred.with_name(f"{preferred.name}_{index}")
        if not candidate.exists():
            return candidate
        index += 1


def extract_video_range(
    video_path: Path,
    start_seconds: float,
    end_seconds: float,
    output_dir: Path,
    *,
    progress: Callable[[int, int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> VideoRangeResult:
    metadata = inspect_video(video_path)
    first_frame, end_frame = validate_time_range(metadata, start_seconds, end_seconds)
    expected = end_frame - first_frame
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=False)

    cap, temp_path = _open_capture(metadata.path, output_dir)
    saved = 0
    try:
        seek_ok = bool(cap.set(cv2.CAP_PROP_POS_FRAMES, first_frame))
        current = int(round(cap.get(cv2.CAP_PROP_POS_FRAMES) or 0))
        if not seek_ok or current != first_frame:
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            current = 0
            while current < first_frame:
                ok, _frame = cap.read()
                if not ok:
                    raise ValueError("Video ended before the selected start time")
                current += 1

        digits = max(6, len(str(expected)))
        for _source_index in range(first_frame, end_frame):
            if cancelled is not None and cancelled():
                raise ExtractionCancelled("Video frame extraction was cancelled")
            ok, frame = cap.read()
            if not ok:
                raise ValueError("Video ended before the selected end time")
            saved += 1
            _write_png(output_dir / f"frame_{saved:0{digits}d}.png", frame)
            if progress is not None:
                progress(saved, expected)
    finally:
        cap.release()
        if temp_path is not None:
            try:
                temp_path.unlink()
            except OSError:
                pass

    if saved == 0:
        raise ValueError("No frames were extracted from the selected range")
    return VideoRangeResult(
        output_dir=output_dir,
        frame_count=saved,
        first_source_frame=first_frame,
        last_source_frame=end_frame - 1,
        start_seconds=float(start_seconds),
        end_seconds=min(float(end_seconds), metadata.duration_seconds),
    )


def split_video(video_path: Path, frame_interval: int, output_dir: Path) -> dict[str, Any]:
    video_path = _validate_video_path(video_path)
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
