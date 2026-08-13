from __future__ import annotations

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0

import hashlib
import json
import shutil
import threading
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

import numpy as np
from PIL import Image

from .color_key_processor import DEFAULT_PARAMS, process_image

PIPELINE_VERSION = 1
ProgressCallback = Callable[[int, int, int, int], None]


def _new_id() -> str:
    return uuid4().hex[:12]


def normalize_params(params: dict[str, Any] | None = None) -> dict[str, Any]:
    result = DEFAULT_PARAMS.copy()
    if params:
        result.update({key: value for key, value in params.items() if key in DEFAULT_PARAMS})
    if result["target_mode"] not in {"black", "white", "green", "magenta", "custom"}:
        result["target_mode"] = "black"
    return result


def make_stage(params: dict[str, Any] | None = None, *, enabled: bool = True, name: str = "") -> dict[str, Any]:
    return {
        "id": _new_id(),
        "name": name,
        "enabled": bool(enabled),
        "params": normalize_params(params),
        "status": "dirty" if enabled else "disabled",
        "cache_signature": "",
        "frame_count": 0,
        "frame_params": {},
        "frame_cache_signatures": {},
    }


def normalize_stage(stage: dict[str, Any]) -> dict[str, Any]:
    enabled = bool(stage.get("enabled", True))
    status = str(stage.get("status", "dirty"))
    if not enabled:
        status = "disabled"
    elif status not in {"dirty", "complete"}:
        status = "dirty"
    frame_params = stage.get("frame_params") if isinstance(stage.get("frame_params"), dict) else {}
    frame_signatures = stage.get("frame_cache_signatures") if isinstance(stage.get("frame_cache_signatures"), dict) else {}
    return {
        "id": str(stage.get("id") or _new_id()),
        "name": str(stage.get("name") or ""),
        "enabled": enabled,
        "params": normalize_params(stage.get("params") if isinstance(stage.get("params"), dict) else stage),
        "status": status,
        "cache_signature": str(stage.get("cache_signature") or ""),
        "frame_count": int(stage.get("frame_count") or 0),
        "frame_params": {
            str(frame_name): normalize_params(params)
            for frame_name, params in frame_params.items()
            if isinstance(params, dict)
        },
        "frame_cache_signatures": {
            str(frame_name): str(signature)
            for frame_name, signature in frame_signatures.items()
            if signature
        },
    }


def ensure_pipeline(project: dict[str, Any]) -> dict[str, Any]:
    existing = project.get("pipeline")
    if isinstance(existing, dict) and isinstance(existing.get("stages"), list):
        stages = existing["stages"]
        stages[:] = [stage for stage in stages if isinstance(stage, dict)]
        for stage in stages:
            normalized = normalize_stage(stage)
            stage.clear()
            stage.update(normalized)
        existing["version"] = PIPELINE_VERSION
        existing["final_output_dir"] = str(existing.get("final_output_dir") or "")
        existing["result_generation"] = str(existing.get("result_generation") or "")
    else:
        legacy = project.get("last_params") if isinstance(project.get("last_params"), dict) else {}
        if not legacy:
            legacy = {"target_mode": project.get("target_mode", "black")}
        stages = [make_stage(legacy)]
        existing = {"version": PIPELINE_VERSION, "stages": stages, "final_output_dir": "", "result_generation": ""}
        project["pipeline"] = existing
    if not stages:
        stages = [make_stage()]
        existing["stages"] = stages
    return existing


def stage_signature(stage: dict[str, Any]) -> str:
    payload = {
        "enabled": bool(stage["enabled"]),
        "params": normalize_params(stage["params"]),
        "frame_params": {
            name: normalize_params(params)
            for name, params in sorted(stage.get("frame_params", {}).items())
        },
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def effective_stage_params(stage: dict[str, Any], frame_name: str | None = None) -> dict[str, Any]:
    if frame_name and frame_name in stage.get("frame_params", {}):
        return normalize_params(stage["frame_params"][frame_name])
    return normalize_params(stage["params"])


def frame_stage_signature(stage: dict[str, Any], frame_name: str) -> str:
    payload = {"enabled": bool(stage["enabled"]), "params": effective_stage_params(stage, frame_name)}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def invalidate_from(project: dict[str, Any], index: int) -> None:
    pipeline = ensure_pipeline(project)
    for stage in pipeline["stages"][max(0, index):]:
        stage["status"] = "dirty" if stage["enabled"] else "disabled"
        stage["cache_signature"] = ""
        stage["frame_count"] = 0
        stage["frame_cache_signatures"] = {}
    pipeline["final_output_dir"] = ""
    pipeline["result_generation"] = ""


def add_stage(project: dict[str, Any], params: dict[str, Any] | None = None) -> int:
    stages = ensure_pipeline(project)["stages"]
    stages.append(make_stage(params))
    index = len(stages) - 1
    invalidate_from(project, index)
    return index


def duplicate_stage(project: dict[str, Any], index: int) -> int:
    stages = ensure_pipeline(project)["stages"]
    clone = make_stage(deepcopy(stages[index]["params"]), enabled=stages[index]["enabled"], name=stages[index]["name"])
    stages.insert(index + 1, clone)
    invalidate_from(project, index + 1)
    return index + 1


def delete_stage(project: dict[str, Any], index: int) -> None:
    stages = ensure_pipeline(project)["stages"]
    if len(stages) <= 1:
        raise ValueError("A pipeline must contain at least one stage")
    stages.pop(index)
    invalidate_from(project, index)


def update_stage(project: dict[str, Any], index: int, params: dict[str, Any]) -> None:
    stage = ensure_pipeline(project)["stages"][index]
    normalized = normalize_params(params)
    if normalized != stage["params"]:
        stage["params"] = normalized
        invalidate_from(project, index)


def set_frame_params(project: dict[str, Any], index: int, frame_name: str, params: dict[str, Any]) -> None:
    stages = ensure_pipeline(project)["stages"]
    normalized = normalize_params(params)
    if stages[index]["frame_params"].get(frame_name) == normalized:
        return
    stages[index]["frame_params"][frame_name] = normalized
    for stage in stages[index:]:
        stage["frame_cache_signatures"].pop(frame_name, None)
        stage["status"] = "dirty" if stage["enabled"] else "disabled"
        stage["cache_signature"] = ""
        stage["frame_count"] = 0
    ensure_pipeline(project)["final_output_dir"] = ""
    ensure_pipeline(project)["result_generation"] = ""


def clear_frame_params(project: dict[str, Any], index: int, frame_name: str) -> None:
    stage = ensure_pipeline(project)["stages"][index]
    if frame_name in stage["frame_params"]:
        del stage["frame_params"][frame_name]
        for downstream in ensure_pipeline(project)["stages"][index:]:
            downstream["frame_cache_signatures"].pop(frame_name, None)
            downstream["status"] = "dirty" if downstream["enabled"] else "disabled"
            downstream["cache_signature"] = ""
            downstream["frame_count"] = 0
        ensure_pipeline(project)["final_output_dir"] = ""
        ensure_pipeline(project)["result_generation"] = ""


def set_stage_enabled(project: dict[str, Any], index: int, enabled: bool) -> None:
    stage = ensure_pipeline(project)["stages"][index]
    if stage["enabled"] != bool(enabled):
        stage["enabled"] = bool(enabled)
        invalidate_from(project, index)


def move_stage(project: dict[str, Any], index: int, offset: int) -> int:
    stages = ensure_pipeline(project)["stages"]
    destination = index + offset
    if destination < 0 or destination >= len(stages):
        return index
    stages[index], stages[destination] = stages[destination], stages[index]
    invalidate_from(project, min(index, destination))
    return destination


def clamp_alpha(previous: Image.Image, current: Image.Image) -> Image.Image:
    previous_rgba = np.array(previous.convert("RGBA"), dtype=np.uint8)
    current_rgba = np.array(current.convert("RGBA"), dtype=np.uint8)
    current_rgba[..., 3] = np.minimum(previous_rgba[..., 3], current_rgba[..., 3])
    return Image.fromarray(current_rgba, "RGBA")


def process_stage(image: Image.Image, params: dict[str, Any]) -> Image.Image:
    return clamp_alpha(image, process_image(image, normalize_params(params), apply_hole_punch=True))


def process_pipeline_image(
    image: Image.Image,
    stages: list[dict[str, Any]],
    through_index: int | None = None,
    frame_name: str | None = None,
) -> Image.Image:
    result = image.convert("RGBA")
    for index, stage in enumerate(stages):
        if through_index is not None and index > through_index:
            break
        normalized = normalize_stage(stage)
        if normalized["enabled"]:
            result = process_stage(result, effective_stage_params(normalized, frame_name))
    return result


def stage_output_dir(project_path: Path, index: int, stage: dict[str, Any]) -> Path:
    return project_path / "pipeline" / f"stage_{index + 1:03d}_{stage['id']}"


def _stage_cache_valid(project_path: Path, index: int, stage: dict[str, Any], frame_count: int) -> bool:
    output = stage_output_dir(project_path, index, stage)
    return (
        stage["enabled"]
        and stage["status"] == "complete"
        and stage["cache_signature"] == stage_signature(stage)
        and stage["frame_count"] == frame_count
        and len(list(output.glob("frame_*.png"))) == frame_count
    )


def run_pipeline(
    project: dict[str, Any],
    project_path: Path,
    *,
    progress: ProgressCallback | None = None,
    cancel_event: threading.Event | None = None,
) -> Path:
    stages = ensure_pipeline(project)["stages"]
    raw_dir = project_path / "01_frames_raw"
    raw_frames = sorted(raw_dir.glob("frame_*.png"))
    if not raw_frames:
        raise ValueError("No input frames found")
    enabled = [(index, stage) for index, stage in enumerate(stages) if stage["enabled"]]
    if not enabled:
        raise ValueError("At least one stage must be enabled")

    pipeline = ensure_pipeline(project)
    pipeline["final_output_dir"] = ""
    pipeline["result_generation"] = ""

    input_dir = raw_dir
    total_stages = len(enabled)
    for enabled_index, (stage_index, stage) in enumerate(enabled, start=1):
        output_dir = stage_output_dir(project_path, stage_index, stage)
        if _stage_cache_valid(project_path, stage_index, stage, len(raw_frames)):
            input_dir = output_dir
            continue

        output_dir.mkdir(parents=True, exist_ok=True)
        for old in output_dir.glob("frame_*.png"):
            old.unlink()
        input_frames = sorted(input_dir.glob("frame_*.png"))
        stage["status"] = "dirty"
        stage["frame_count"] = 0
        stage["frame_cache_signatures"] = {}
        for frame_index, input_path in enumerate(input_frames, start=1):
            if cancel_event is not None and cancel_event.is_set():
                invalidate_from(project, stage_index)
                raise InterruptedError("Pipeline processing cancelled")
            with Image.open(input_path) as source:
                result = process_stage(source, effective_stage_params(stage, input_path.name))
            result.save(output_dir / input_path.name)
            stage["frame_count"] = frame_index
            stage["frame_cache_signatures"][input_path.name] = frame_stage_signature(stage, input_path.name)
            if progress:
                progress(enabled_index, total_stages, frame_index, len(input_frames))
        stage["status"] = "complete"
        stage["cache_signature"] = stage_signature(stage)
        stage["completed_at"] = datetime.now().isoformat()
        input_dir = output_dir

    pipeline["final_output_dir"] = str(input_dir.relative_to(project_path))
    pipeline["result_generation"] = uuid4().hex
    project["last_output_dir"] = pipeline["final_output_dir"]
    return input_dir


def run_pipeline_frame(
    project: dict[str, Any],
    project_path: Path,
    frame_name: str,
    *,
    progress: ProgressCallback | None = None,
    cancel_event: threading.Event | None = None,
) -> Path:
    stages = ensure_pipeline(project)["stages"]
    raw_dir = project_path / "01_frames_raw"
    raw_frames = sorted(raw_dir.glob("frame_*.png"))
    raw_path = raw_dir / frame_name
    if not raw_path.is_file():
        raise FileNotFoundError(str(raw_path))
    enabled = [(index, stage) for index, stage in enumerate(stages) if stage["enabled"]]
    if not enabled:
        raise ValueError("At least one stage must be enabled")

    pipeline = ensure_pipeline(project)
    pipeline["final_output_dir"] = ""
    pipeline["result_generation"] = ""

    with Image.open(raw_path) as source:
        result = source.convert("RGBA")
    total_stages = len(enabled)
    output_path = raw_path
    for enabled_index, (stage_index, stage) in enumerate(enabled, start=1):
        if cancel_event is not None and cancel_event.is_set():
            for downstream in stages[stage_index:]:
                downstream["frame_cache_signatures"].pop(frame_name, None)
            raise InterruptedError("Pipeline processing cancelled")
        result = process_stage(result, effective_stage_params(stage, frame_name))
        output_dir = stage_output_dir(project_path, stage_index, stage)
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / frame_name
        result.save(output_path)
        stage["frame_cache_signatures"][frame_name] = frame_stage_signature(stage, frame_name)
        all_current = all(
            stage["frame_cache_signatures"].get(path.name) == frame_stage_signature(stage, path.name)
            and (output_dir / path.name).is_file()
            for path in raw_frames
        )
        if all_current:
            stage["status"] = "complete"
            stage["cache_signature"] = stage_signature(stage)
            stage["frame_count"] = len(raw_frames)
            stage["completed_at"] = datetime.now().isoformat()
        else:
            stage["status"] = "dirty"
            stage["cache_signature"] = ""
            stage["frame_count"] = len(stage["frame_cache_signatures"])
        if progress:
            progress(enabled_index, total_stages, 1, 1)

    if all(stage["status"] == "complete" for _, stage in enabled):
        final_dir = output_path.parent
        pipeline["final_output_dir"] = str(final_dir.relative_to(project_path))
        pipeline["result_generation"] = uuid4().hex
        project["last_output_dir"] = pipeline["final_output_dir"]
    else:
        pipeline["final_output_dir"] = ""
        pipeline["result_generation"] = ""
    return output_path


def remove_orphan_stage_caches(project: dict[str, Any], project_path: Path) -> None:
    pipeline_root = project_path / "pipeline"
    if not pipeline_root.exists():
        return
    valid = {stage_output_dir(project_path, index, stage).resolve() for index, stage in enumerate(ensure_pipeline(project)["stages"])}
    for directory in pipeline_root.glob("stage_*"):
        if directory.is_dir() and directory.resolve() not in valid:
            shutil.rmtree(directory)
