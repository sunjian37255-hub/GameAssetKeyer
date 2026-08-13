from __future__ import annotations

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0

import queue
import threading
from pathlib import Path
from typing import Any

from .pipeline import run_pipeline, run_pipeline_frame


class PipelineWorker(threading.Thread):
    def __init__(self, project: dict[str, Any], project_path: Path, events: queue.Queue[dict[str, Any]]):
        super().__init__(name="GameAssetKeyerPipeline", daemon=True)
        self.project = project
        self.project_path = project_path
        self.events = events
        self.cancel_event = threading.Event()

    def cancel(self) -> None:
        self.cancel_event.set()

    def _progress(self, stage: int, stage_total: int, frame: int, frame_total: int) -> None:
        percent = round((frame / frame_total) * 100) if frame_total else 0
        self.events.put({
            "type": "progress",
            "stage": stage,
            "stage_total": stage_total,
            "frame": frame,
            "frame_total": frame_total,
            "percent": percent,
        })

    def run(self) -> None:
        self.events.put({"type": "started", "scope": "all"})
        try:
            output = run_pipeline(
                self.project,
                self.project_path,
                progress=self._progress,
                cancel_event=self.cancel_event,
            )
        except InterruptedError:
            self.events.put({"type": "cancelled", "scope": "all"})
        except Exception as exc:
            self.events.put({"type": "error", "scope": "all", "error": str(exc), "exception": type(exc).__name__})
        else:
            self.events.put({"type": "done", "scope": "all", "output_dir": str(output)})


class PipelineFrameWorker(PipelineWorker):
    def __init__(self, project: dict[str, Any], project_path: Path, frame_name: str, events: queue.Queue[dict[str, Any]]):
        super().__init__(project, project_path, events)
        self.name = "GameAssetKeyerFrame"
        self.frame_name = frame_name

    def run(self) -> None:
        self.events.put({"type": "started", "scope": "frame", "frame_name": self.frame_name})
        try:
            output = run_pipeline_frame(
                self.project,
                self.project_path,
                self.frame_name,
                progress=self._progress,
                cancel_event=self.cancel_event,
            )
        except InterruptedError:
            self.events.put({"type": "cancelled", "scope": "frame", "frame_name": self.frame_name})
        except Exception as exc:
            self.events.put({"type": "error", "scope": "frame", "error": str(exc), "exception": type(exc).__name__})
        else:
            self.events.put({"type": "done", "scope": "frame", "output_path": str(output), "frame_name": self.frame_name})
