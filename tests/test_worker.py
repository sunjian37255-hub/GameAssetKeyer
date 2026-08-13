from __future__ import annotations

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0

import queue
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from app.pipeline import add_stage, ensure_pipeline, set_frame_params
from app.workers import PipelineFrameWorker, PipelineWorker


class WorkerTests(unittest.TestCase):
    def _project(self, root: Path, frames: int = 4) -> dict:
        raw = root / "01_frames_raw"
        raw.mkdir()
        for index in range(frames):
            Image.new("RGBA", (32, 32), (index * 10, 0, 0, 255)).save(raw / f"frame_{index + 1:06d}.png")
        project: dict = {"target_mode": "black"}
        ensure_pipeline(project)
        add_stage(project, {"target_mode": "green"})
        return project

    def test_progress_and_completion(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            root = Path(temp)
            project = self._project(root)
            events: queue.Queue[dict] = queue.Queue()
            worker = PipelineWorker(project, root, events)
            worker.start()
            worker.join(10)
            self.assertFalse(worker.is_alive())
            received = []
            while not events.empty():
                received.append(events.get_nowait())
            self.assertEqual(received[0]["type"], "started")
            self.assertEqual(received[-1]["type"], "done")
            progress = [event for event in received if event["type"] == "progress"]
            self.assertEqual(len(progress), 8)
            self.assertEqual(progress[-1]["percent"], 100)

    def test_cancel_does_not_mark_complete(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            root = Path(temp)
            project = self._project(root, frames=20)
            events: queue.Queue[dict] = queue.Queue()
            worker = PipelineWorker(project, root, events)
            worker.cancel()
            worker.start()
            worker.join(10)
            received = []
            while not events.empty():
                received.append(events.get_nowait())
            self.assertEqual(received[-1]["type"], "cancelled")
            self.assertNotEqual(ensure_pipeline(project)["stages"][0]["status"], "complete")

    def test_current_frame_worker_uses_saved_override(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            root = Path(temp)
            project = self._project(root, frames=2)
            set_frame_params(project, 0, "frame_000001.png", {"target_mode": "white", "feather_radius": 0})
            events: queue.Queue[dict] = queue.Queue()
            worker = PipelineFrameWorker(project, root, "frame_000001.png", events)
            worker.start()
            worker.join(10)
            received = []
            while not events.empty():
                received.append(events.get_nowait())
            self.assertEqual(received[0]["scope"], "frame")
            self.assertEqual(received[-1]["type"], "done")
            self.assertTrue(Path(received[-1]["output_path"]).is_file())


if __name__ == "__main__":
    unittest.main()
