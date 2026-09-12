from __future__ import annotations

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0

import json
import tempfile
import unittest
from pathlib import Path
from tkinter import ttk
from unittest.mock import patch

import cv2
import numpy as np
from PIL import Image

from app.ui.video_frame_extractor_dialog import VideoFrameExtractorDialog, format_timestamp
from app.ui_main import GameAssetKeyerApp
from app.video_splitter import (
    default_range_output_dir,
    extract_video_range,
    inspect_video,
    unique_output_dir,
    validate_time_range,
    VideoRangeResult,
)


def widget_texts(widget, widget_type) -> list[str]:
    result: list[str] = []
    for child in widget.winfo_children():
        if isinstance(child, widget_type):
            result.append(str(child.cget("text")))
        result.extend(widget_texts(child, widget_type))
    return result


class VideoRangeExtractorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.root = Path(self.temp.name)
        self.video = self.root / "range.avi"
        writer = cv2.VideoWriter(str(self.video), cv2.VideoWriter_fourcc(*"MJPG"), 10.0, (32, 24))
        if not writer.isOpened():
            self.temp.cleanup()
            self.skipTest("OpenCV MJPG VideoWriter is unavailable")
        try:
            for index in range(20):
                frame = np.full((24, 32, 3), (index * 8, 40, 180), dtype=np.uint8)
                writer.write(frame)
        finally:
            writer.release()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_metadata_time_validation_and_exact_range_extraction(self) -> None:
        metadata = inspect_video(self.video)
        self.assertAlmostEqual(metadata.fps, 10.0, places=1)
        self.assertEqual(metadata.frame_count, 20)
        self.assertAlmostEqual(metadata.duration_seconds, 2.0, places=1)
        self.assertEqual(validate_time_range(metadata, 0.7, 1.0), (7, 10))
        progress: list[tuple[int, int]] = []
        output = self.root / "frames"
        result = extract_video_range(self.video, 0.7, 1.0, output, progress=lambda current, total: progress.append((current, total)))
        self.assertEqual(result.frame_count, 3)
        self.assertEqual((result.first_source_frame, result.last_source_frame), (7, 9))
        self.assertEqual([path.name for path in output.glob("*.png")], ["frame_000001.png", "frame_000002.png", "frame_000003.png"])
        self.assertEqual(progress[-1], (3, 3))

    def test_invalid_ranges_and_unique_output_folder(self) -> None:
        metadata = inspect_video(self.video)
        for start, end in ((-1, 1), (1, 1), (1.5, 1.0), (0, 3.0)):
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                validate_time_range(metadata, start, end)
        preferred = default_range_output_dir(self.video, 0.7, 1.0)
        preferred.mkdir()
        self.assertEqual(unique_output_dir(preferred), preferred.with_name(f"{preferred.name}_2"))
        self.assertEqual(format_timestamp(7.125), "00:07.125")

    def test_seven_to_ten_seconds_exports_every_frame_in_that_range(self) -> None:
        video = self.root / "twelve-seconds.avi"
        writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"MJPG"), 10.0, (16, 16))
        if not writer.isOpened():
            self.skipTest("OpenCV MJPG VideoWriter is unavailable")
        try:
            for index in range(120):
                writer.write(np.full((16, 16, 3), (index % 255, 40, 180), dtype=np.uint8))
        finally:
            writer.release()
        output = self.root / "seven-to-ten"
        result = extract_video_range(video, 7.0, 10.0, output)
        self.assertEqual(result.frame_count, 30)
        self.assertEqual((result.first_source_frame, result.last_source_frame), (70, 99))
        self.assertEqual(len(list(output.glob("frame_*.png"))), 30)


class VideoRangeExtractorUiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.root = Path(self.temp.name)
        (self.root / "settings.json").write_text(json.dumps({"language": "zh_CN"}), encoding="utf-8")
        self.source = self.root / "source.png"
        Image.new("RGBA", (16, 16), (20, 30, 40, 255)).save(self.source)
        self.app = GameAssetKeyerApp(self.root)
        self.app.root.withdraw()

    def tearDown(self) -> None:
        self.app.root.destroy()
        self.temp.cleanup()

    def test_home_and_dialog_expose_complete_standalone_workflow(self) -> None:
        self.assertIn("视频拆帧", widget_texts(self.app.page, ttk.Label))
        dialog = VideoFrameExtractorDialog(self.app.root, self.app.t)
        labels = widget_texts(dialog.window, ttk.Label)
        self.assertIn("源视频", widget_texts(dialog.window, ttk.LabelFrame))
        for text in ("开始时间（秒）", "结束时间（秒）"):
            self.assertIn(text, labels)
        self.assertIn("开始拆帧", widget_texts(dialog.window, ttk.Button))
        dialog.cancel()

        project = self.app.pm.create_project(self.source, "video-tool-location", 1, 1, "black")
        self.app.load_project(project["id"])
        self.assertNotIn("视频拆帧", widget_texts(self.app.page, ttk.Label))

    def test_home_action_opens_one_standalone_dialog(self) -> None:
        with patch("app.ui_main.VideoFrameExtractorDialog") as dialog_class:
            self.app.run_video_frame_extractor()
        dialog_class.assert_called_once_with(self.app.root, self.app.t)
        dialog_class.return_value.show.assert_called_once_with()

    def test_success_opens_the_actual_output_folder(self) -> None:
        dialog = VideoFrameExtractorDialog(self.app.root, self.app.t)
        output = self.root / "frames output"
        output.mkdir()
        result = VideoRangeResult(output, 3, 7, 9, 0.7, 1.0)
        with patch("app.ui.video_frame_extractor_dialog.os.startfile") as open_folder:
            dialog._finish(result)
        open_folder.assert_called_once_with(str(output))
        self.assertEqual(dialog.result, result)
        dialog.cancel()


if __name__ == "__main__":
    unittest.main()
