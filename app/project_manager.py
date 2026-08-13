from __future__ import annotations

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0

import json
import math
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from .sheet_splitter import split_sheet
from .video_splitter import split_video
from .pipeline import ensure_pipeline

INVALID_CHARS = '<>:"/\\|?*'
INITIAL_BASIC_PARAMS = {
    "background_threshold": 0.0,
    "foreground_threshold": 0.0,
    "feather_radius": 0.0,
    "edge_erode": 0,
}


def sanitize_name(name: str) -> str:
    for char in INVALID_CHARS:
        name = name.replace(char, "_")
    name = name.strip().rstrip(".")
    return name or "sprite_project"


class ProjectManager:
    def __init__(self, app_root: Path):
        self.app_root = app_root
        self.projects_root = app_root / "projects"
        self.projects_root.mkdir(parents=True, exist_ok=True)

    def list_projects(self) -> list[dict[str, Any]]:
        projects: list[dict[str, Any]] = []
        for path in sorted(self.projects_root.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if not path.is_dir():
                continue
            meta = self.load_project(path.name, missing_ok=True)
            projects.append({
                "id": path.name,
                "name": meta.get("name", path.name),
                "path": str(path),
                "rows": meta.get("rows", 0),
                "cols": meta.get("cols", 0),
                "target_mode": meta.get("target_mode", "green"),
                "project_type": meta.get("project_type", "sprite_sheet"),
                "modified_at": datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
            })
        return projects

    def project_path(self, project_id: str) -> Path:
        return self.projects_root / project_id

    def load_project(self, project_id: str, missing_ok: bool = False) -> dict[str, Any]:
        path = self.project_path(project_id)
        meta_path = path / "project.json"
        if not meta_path.exists():
            if missing_ok:
                return {}
            raise FileNotFoundError(str(meta_path))
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        ensure_pipeline(data)
        return data

    def save_project(self, project_id: str, data: dict[str, Any]) -> None:
        path = self.project_path(project_id)
        data["updated_at"] = datetime.now().isoformat()
        (path / "project.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def rename_project(self, project_id: str, new_name: str) -> dict[str, Any]:
        display_name = new_name.strip()
        if not display_name or any(char in display_name for char in INVALID_CHARS) or display_name.endswith((" ", ".")):
            raise ValueError("Invalid project name")
        data = self.load_project(project_id)
        data["name"] = display_name
        self.save_project(project_id, data)
        return data

    def create_project(self, image_path: Path, name: str, rows: int, cols: int, target_mode: str, custom_color: str = "#000000") -> dict[str, Any]:
        image_path = image_path.resolve()
        if not image_path.exists():
            raise FileNotFoundError(str(image_path))
        if image_path.suffix.lower() != ".png":
            raise ValueError("仅支持 PNG 序列帧图")
        if rows <= 0 or cols <= 0:
            raise ValueError("行数和列数必须大于 0")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        display_name = name.strip() or f"{image_path.stem}_{timestamp}"
        safe = sanitize_name(display_name)
        project_id = safe
        project_path = self.project_path(project_id)
        counter = 2
        while project_path.exists():
            project_id = f"{safe}_{counter:02d}"
            project_path = self.project_path(project_id)
            counter += 1

        for rel in ["source", "01_frames_raw", "02_no_bg", "03_hole_punched", "04_trimmed", "exports"]:
            (project_path / rel).mkdir(parents=True, exist_ok=True)

        source_copy = project_path / "source" / "original_sheet.png"
        shutil.copy2(image_path, source_copy)
        frame_count = split_sheet(source_copy, rows, cols, project_path / "01_frames_raw")

        data = {
            "id": project_id,
            "name": display_name,
            "source_path": str(image_path),
            "source_copy": str(source_copy),
            "project_type": "sprite_sheet",
            "source_type": "sprite_sheet",
            "rows": rows,
            "cols": cols,
            "frame_count": frame_count,
            "target_mode": target_mode,
            "custom_color": custom_color,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "last_params": {
                "target_mode": target_mode,
                "custom_color": custom_color,
                **INITIAL_BASIC_PARAMS,
            },
            "trim": {},
            "exports": {},
        }
        ensure_pipeline(data)
        self.save_project(project_id, data)
        return data

    def create_video_project(self, video_path: Path, name: str, frame_interval: int, target_mode: str, custom_color: str = "#000000") -> dict[str, Any]:
        video_path = video_path.resolve()
        if not video_path.exists():
            raise FileNotFoundError(str(video_path))
        if frame_interval <= 0:
            raise ValueError("抽帧间隔必须大于 0")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        display_name = name.strip() or f"{video_path.stem}_{timestamp}"
        safe = sanitize_name(display_name)
        project_id = safe
        project_path = self.project_path(project_id)
        counter = 2
        while project_path.exists():
            project_id = f"{safe}_{counter:02d}"
            project_path = self.project_path(project_id)
            counter += 1

        for rel in ["source", "01_frames_raw", "02_no_bg", "03_hole_punched", "04_trimmed", "exports"]:
            (project_path / rel).mkdir(parents=True, exist_ok=True)

        (project_path / "source" / "source_video.txt").write_text(str(video_path), encoding="utf-8")
        video_meta = split_video(video_path, frame_interval, project_path / "01_frames_raw")
        frame_count = int(video_meta["frame_count"])
        # Video projects are frame-sequence projects. Rows/cols are only kept for
        # compatibility with the existing project metadata shape.
        cols = frame_count
        rows = 1

        data = {
            "id": project_id,
            "name": display_name,
            "source_path": str(video_path),
            "source_copy": "",
            "project_type": "video",
            "source_type": "video",
            "rows": rows,
            "cols": cols,
            "frame_count": frame_count,
            "target_mode": target_mode,
            "custom_color": custom_color,
            "video": video_meta,
            "video_frame_interval": frame_interval,
            "export_sheet_enabled": False,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "last_params": {
                "target_mode": target_mode,
                "custom_color": custom_color,
                **INITIAL_BASIC_PARAMS,
            },
            "trim": {},
            "exports": {},
        }
        ensure_pipeline(data)
        self.save_project(project_id, data)
        return data

    def delete_project(self, project_id: str) -> None:
        path = self.project_path(project_id)
        if path.exists():
            shutil.rmtree(path)
