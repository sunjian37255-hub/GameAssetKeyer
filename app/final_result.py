from __future__ import annotations

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .pipeline import ensure_pipeline, stage_output_dir, stage_signature


@dataclass(frozen=True)
class FinalResultSource:
    kind: str
    directory: Path
    signature: str
    frame_names: tuple[str, ...]

    def frame_path(self, frame_name: str) -> Path:
        return self.directory / frame_name


def _frame_names(directory: Path) -> tuple[str, ...]:
    return tuple(path.name for path in sorted(directory.glob("frame_*.png")))


def _has_complete_frame_set(directory: Path, expected: tuple[str, ...]) -> bool:
    return bool(expected) and directory.is_dir() and _frame_names(directory) == expected


def _legacy_pipeline_generation(directory: Path, relative: str, enabled: list[tuple[int, dict[str, Any]]]) -> str:
    payload = {
        "relative": relative,
        "stages": [(index, stage["id"], stage["cache_signature"]) for index, stage in enabled],
        "frames": [
            (path.name, path.stat().st_size, path.stat().st_mtime_ns)
            for path in sorted(directory.glob("frame_*.png"))
        ],
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return f"legacy-{digest}"


def resolve_pipeline_result_source(project: dict[str, Any], project_path: Path) -> FinalResultSource | None:
    pipeline = ensure_pipeline(project)
    relative = str(pipeline.get("final_output_dir") or "")
    if not relative:
        return None

    raw_dir = project_path / "01_frames_raw"
    frame_names = _frame_names(raw_dir)
    enabled = [(index, stage) for index, stage in enumerate(pipeline["stages"]) if stage["enabled"]]
    if not frame_names or not enabled:
        return None
    if any(
        stage["status"] != "complete"
        or stage["cache_signature"] != stage_signature(stage)
        or stage["frame_count"] != len(frame_names)
        for _, stage in enabled
    ):
        return None

    directory = project_path / relative
    expected_directory = stage_output_dir(project_path, *enabled[-1])
    try:
        if directory.resolve() != expected_directory.resolve():
            return None
    except OSError:
        return None
    if not _has_complete_frame_set(directory, frame_names):
        return None
    generation = str(pipeline.get("result_generation") or "")
    if not generation:
        try:
            generation = _legacy_pipeline_generation(directory, relative, enabled)
        except OSError:
            return None
    return FinalResultSource("pipeline", directory, generation, frame_names)


def _resolve_postprocess(
    project: dict[str, Any],
    project_path: Path,
    key: str,
    directory_name: str,
    metadata_name: str,
    source: FinalResultSource,
) -> FinalResultSource | None:
    metadata = project.get(key)
    if not isinstance(metadata, dict):
        return None
    source_signature = str(metadata.get("source_signature") or "")
    result_signature = str(metadata.get("result_signature") or "")
    if source_signature != source.signature or not result_signature:
        return None
    if int(metadata.get("frame_count") or 0) != len(source.frame_names):
        return None

    directory = project_path / directory_name
    if not _has_complete_frame_set(directory, source.frame_names):
        return None
    metadata_path = directory / metadata_name
    try:
        disk_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(disk_metadata, dict):
        return None
    if (
        disk_metadata.get("source_signature") != source_signature
        or disk_metadata.get("result_signature") != result_signature
        or int(disk_metadata.get("frame_count") or 0) != len(source.frame_names)
    ):
        return None
    return FinalResultSource(key, directory, result_signature, source.frame_names)


def resolve_pre_alignment_source(project: dict[str, Any], project_path: Path) -> FinalResultSource | None:
    pipeline_source = resolve_pipeline_result_source(project, project_path)
    if pipeline_source is None:
        return None
    trim_source = _resolve_postprocess(
        project,
        project_path,
        "trim",
        "04_trimmed",
        "trim_metadata.json",
        pipeline_source,
    )
    return trim_source or pipeline_source


def resolve_final_result_source(project: dict[str, Any], project_path: Path) -> FinalResultSource | None:
    source = resolve_pre_alignment_source(project, project_path)
    if source is None:
        return None
    align_source = _resolve_postprocess(
        project,
        project_path,
        "align",
        "05_aligned",
        "align_metadata.json",
        source,
    )
    return align_source or source
