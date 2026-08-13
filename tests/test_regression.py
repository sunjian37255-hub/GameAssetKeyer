from __future__ import annotations

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0

import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from app.align_utils import align_frames
from app.pipeline import add_stage, ensure_pipeline, run_pipeline
from app.project_manager import ProjectManager
from app.sheet_exporter import export_sheet
from app.trim_utils import trim_frames


def make_sheet(path: Path, rows: int = 2, cols: int = 2) -> None:
    pixels = np.zeros((rows * 16, cols * 16, 4), dtype=np.uint8)
    pixels[..., 3] = 255
    colors = ((255, 80, 40), (40, 255, 80), (80, 40, 255), (255, 255, 255))
    for index, color in enumerate(colors[: rows * cols]):
        row, col = divmod(index, cols)
        top, left = row * 16, col * 16
        pixels[top + 4 : top + 12, left + 4 : left + 12, :3] = color
    Image.fromarray(pixels, "RGBA").save(path)


class RegressionTests(unittest.TestCase):
    def test_single_png_sheet_full_processing_trim_align_and_export(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            root = Path(temp)
            image = root / "sheet.png"
            make_sheet(image)
            manager = ProjectManager(root)

            single = manager.create_project(image, "single", 1, 1, "black")
            self.assertEqual(single["frame_count"], 1)

            project = manager.create_project(image, "sheet", 2, 2, "black")
            project_path = manager.project_path(project["id"])
            stages = ensure_pipeline(project)["stages"]
            stages[0]["params"].update({"target_mode": "black", "feather_radius": 0})
            add_stage(project, {"target_mode": "custom", "custom_color": "#FF5028", "feather_radius": 0})
            processed = run_pipeline(project, project_path)
            self.assertEqual(len(list(processed.glob("frame_*.png"))), 4)

            trim_meta = trim_frames(processed, project_path / "04_trimmed", threshold=8, padding=0)
            self.assertEqual(trim_meta["frame_count"], 4)
            align_meta = align_frames(project_path / "04_trimmed", project_path / "05_aligned", mode="center")
            self.assertEqual(align_meta["frame_count"], 4)
            export_meta = export_sheet(project_path / "05_aligned", project_path / "exports", 2, 2, "result.png")
            self.assertTrue(Path(export_meta["sheet"]).is_file())
            self.assertTrue(Path(export_meta["preview"]).is_file())

    def test_short_video_opencv_split_and_pipeline(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            root = Path(temp)
            video = root / "smoke.avi"
            writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"MJPG"), 5.0, (32, 24))
            if not writer.isOpened():
                self.skipTest("OpenCV MJPG VideoWriter is unavailable")
            try:
                for index in range(4):
                    frame = np.zeros((24, 32, 3), dtype=np.uint8)
                    frame[6:18, 4 + index : 16 + index] = (20, 100, 240)
                    writer.write(frame)
            finally:
                writer.release()

            manager = ProjectManager(root)
            project = manager.create_video_project(video, "video", frame_interval=2, target_mode="black")
            self.assertGreaterEqual(project["frame_count"], 2)
            project_path = manager.project_path(project["id"])
            ensure_pipeline(project)["stages"][0]["params"].update({"target_mode": "black", "feather_radius": 0})
            output = run_pipeline(project, project_path)
            self.assertEqual(len(list(output.glob("frame_*.png"))), project["frame_count"])


if __name__ == "__main__":
    unittest.main()
