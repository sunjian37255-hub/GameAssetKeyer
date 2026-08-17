from __future__ import annotations

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0

"""Pure animation-preview source resolution and bounded frame caching.

The workbench owns playback state, while this module owns the rules for
deciding which on-disk frame set is safe to preview.  In particular, Final
Result resolution is deliberately delegated to ``final_result`` instead of
being reimplemented here.
"""

from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from .final_result import (
    FinalResultSource,
    resolve_final_result_source,
)
from .pipeline import ensure_pipeline, stage_output_dir, stage_signature


class AnimationPreviewError(ValueError):
    """A source cannot safely provide a complete animation sequence."""

    def __init__(self, message: str, *, message_key: str = "error.animation_source"):
        super().__init__(message)
        self.message_key = message_key


@dataclass(frozen=True)
class AnimationSource:
    """A validated, disk-backed frame sequence.

    Only names and the source directory are retained here.  Full-resolution
    images are read by :func:`read_frame` one at a time.
    """

    key: str
    directory: Path
    frame_names: tuple[str, ...]
    signature: str = ""

    def frame_path(self, frame_name: str) -> Path:
        return self.directory / frame_name

    @property
    def frame_count(self) -> int:
        return len(self.frame_names)


def validate_fps(value: object, *, minimum: int = 1, maximum: int = 60) -> int:
    """Parse a user-entered FPS value and enforce the RC's 1..60 range."""

    text = str(value).strip()
    if not text or not text.isdigit():
        raise AnimationPreviewError(
            "FPS must be a whole number from 1 to 60.",
            message_key="error.animation_fps",
        )
    fps = int(text)
    if not minimum <= fps <= maximum:
        raise AnimationPreviewError(
            "FPS must be a whole number from 1 to 60.",
            message_key="error.animation_fps",
        )
    return fps


def fps_interval_ms(fps: object) -> int:
    """Return the Tk ``after`` interval required for ``fps``."""

    return max(1, round(1000 / validate_fps(fps)))


def next_frame_index(index: int, frame_count: int, *, loop: bool = False) -> int | None:
    """Advance a playback cursor without mutating a workbench selection."""

    if frame_count <= 0:
        raise AnimationPreviewError("The animation has no frames.", message_key="error.animation_source")
    next_index = int(index) + 1
    if next_index < frame_count:
        return next_index
    return 0 if loop else None


# A descriptive alias makes the state-machine intent easy to discover in
# tests and integrations without adding another implementation.
advance_frame_index = next_frame_index


def enumerate_frame_names(directory: Path) -> tuple[str, ...]:
    """Enumerate the project's zero-padded ``frame_*.png`` set."""

    directory = Path(directory)
    return tuple(path.name for path in sorted(directory.glob("frame_*.png")))


def _validated_source(
    key: str,
    directory: Path,
    expected_names: tuple[str, ...],
    *,
    signature: str = "",
    incomplete_key: str,
) -> AnimationSource:
    actual_names = enumerate_frame_names(directory)
    if not expected_names or actual_names != expected_names:
        raise AnimationPreviewError(
            f"Animation source is incomplete: {directory}",
            message_key=incomplete_key,
        )
    return AnimationSource(key, Path(directory), expected_names, signature)


def _validated_stage_source(
    project: dict[str, Any],
    project_path: Path,
    stage_index: int,
    expected_names: tuple[str, ...],
    *,
    key: str,
) -> AnimationSource:
    stages = ensure_pipeline(project)["stages"]
    if not 0 <= stage_index < len(stages):
        raise AnimationPreviewError("The selected stage does not exist.", message_key="error.animation_source")
    stage = stages[stage_index]
    directory = stage_output_dir(project_path, stage_index, stage)
    if (
        not stage.get("enabled")
        or stage.get("status") != "complete"
        or stage.get("cache_signature") != stage_signature(stage)
        or int(stage.get("frame_count") or 0) != len(expected_names)
    ):
        raise AnimationPreviewError(
            "The current Stage Result is incomplete.",
            message_key="error.animation_incomplete_stage",
        )
    return _validated_source(
        key,
        directory,
        expected_names,
        signature=str(stage.get("cache_signature") or ""),
        incomplete_key="error.animation_incomplete_stage",
    )


def resolve_animation_source(
    project: dict[str, Any],
    project_path: Path,
    source_key: str,
    selected_stage_index: int = 0,
) -> AnimationSource:
    """Resolve a safe sequence for Original/Input/Stage/Final preview.

    ``source_key`` accepts both the UI keys (``result``/``final``) and the
    descriptive keys used by non-GUI tests (``stage_result``/``final_result``).
    """

    project_path = Path(project_path)
    pipeline = ensure_pipeline(project)
    raw_names = enumerate_frame_names(project_path / "01_frames_raw")
    if not raw_names:
        raise AnimationPreviewError("No input frames found.", message_key="error.animation_source")

    normalized_key = {
        "raw": "original",
        "original": "original",
        "input": "stage_input",
        "stage_input": "stage_input",
        "result": "stage_result",
        "stage_result": "stage_result",
        "final": "final_result",
        "final_result": "final_result",
    }.get(str(source_key).strip().lower())
    if normalized_key is None:
        raise AnimationPreviewError("Unknown animation source.", message_key="error.animation_source")

    if normalized_key == "original":
        return AnimationSource("original", project_path / "01_frames_raw", raw_names)

    stages = pipeline["stages"]
    if not 0 <= selected_stage_index < len(stages):
        raise AnimationPreviewError("The selected stage does not exist.", message_key="error.animation_source")

    if normalized_key == "stage_result":
        return _validated_stage_source(project, project_path, selected_stage_index, raw_names, key="stage_result")

    if normalized_key == "stage_input":
        previous_enabled = [
            index for index, stage in enumerate(stages[:selected_stage_index]) if stage.get("enabled")
        ]
        if not previous_enabled:
            return AnimationSource("stage_input", project_path / "01_frames_raw", raw_names)
        previous_index = previous_enabled[-1]
        source = _validated_stage_source(
            project,
            project_path,
            previous_index,
            raw_names,
            key="stage_input",
        )
        return source

    # This call is the single source of truth shared by the static Final
    # Result preview and all existing exports.
    final_source: FinalResultSource | None = resolve_final_result_source(project, project_path)
    if final_source is None:
        raise AnimationPreviewError(
            "The Final Result is incomplete. Process all frames before previewing the animation.",
            message_key="error.animation_incomplete_final",
        )
    return _validated_source(
        "final_result",
        final_source.directory,
        raw_names,
        signature=final_source.signature,
        incomplete_key="error.animation_incomplete_final",
    )


class PreviewFrameCache:
    """Small LRU cache; source images remain disk-backed outside this bound."""

    def __init__(self, max_items: int = 32):
        if max_items < 1:
            raise ValueError("max_items must be positive")
        self.max_items = int(max_items)
        self._items: OrderedDict[str, Image.Image] = OrderedDict()

    def get(self, key: str) -> Image.Image | None:
        image = self._items.get(str(key))
        if image is None:
            return None
        self._items.move_to_end(str(key))
        return image.copy()

    def put(self, key: str, image: Image.Image) -> None:
        key = str(key)
        previous = self._items.pop(key, None)
        if previous is not None:
            previous.close()
        self._items[key] = image.convert("RGBA")
        self._items.move_to_end(key)
        while len(self._items) > self.max_items:
            _, evicted = self._items.popitem(last=False)
            evicted.close()

    def clear(self) -> None:
        for image in self._items.values():
            image.close()
        self._items.clear()

    def __len__(self) -> int:
        return len(self._items)

    def __contains__(self, key: object) -> bool:
        return str(key) in self._items


# Backwards-friendly name for callers that describe these as an animation
# cache rather than a preview cache.
AnimationPreviewCache = PreviewFrameCache


def read_frame(source: AnimationSource, index: int, cache: PreviewFrameCache | None = None) -> Image.Image:
    """Read exactly one RGBA frame, optionally through a bounded cache."""

    if not 0 <= int(index) < source.frame_count:
        raise AnimationPreviewError("Frame index is outside the animation.", message_key="error.animation_source")
    frame_name = source.frame_names[int(index)]
    cache_key = f"{source.directory.resolve()}::{source.signature}::{frame_name}"
    if cache is not None:
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
    path = source.frame_path(frame_name)
    if not path.is_file():
        raise AnimationPreviewError(
            f"Animation frame is missing: {path}",
            message_key="error.animation_missing_frame",
        )
    try:
        with Image.open(path) as image:
            loaded = image.convert("RGBA")
    except (OSError, ValueError) as exc:
        raise AnimationPreviewError(
            f"Could not read animation frame: {path}: {exc}",
            message_key="error.animation_missing_frame",
        ) from exc
    if cache is not None:
        cache.put(cache_key, loaded)
    return loaded


def source_frame_paths(source: AnimationSource) -> tuple[Path, ...]:
    """Return paths without opening images; useful for lightweight audits."""

    return tuple(source.frame_path(name) for name in source.frame_names)
