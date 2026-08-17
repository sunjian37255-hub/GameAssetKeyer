from __future__ import annotations

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image

from app.animation_preview import (
    AnimationPreviewError,
    PreviewFrameCache,
    fps_interval_ms,
    next_frame_index,
    read_frame,
    resolve_animation_source,
    validate_fps,
)
from app.pipeline import run_pipeline
from app.project_manager import ProjectManager
from app.ui_main import GameAssetKeyerApp


class AnimationPreviewCoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.root = Path(self.temp.name)
        self.source = self.root / "source.png"
        sheet = np.zeros((8, 24, 4), dtype=np.uint8)
        sheet[..., 3] = 255
        for index, color in enumerate(((255, 255, 255), (30, 50, 70), (90, 110, 130))):
            sheet[2:6, index * 8 + 2:index * 8 + 6, :3] = color
        Image.fromarray(sheet, "RGBA").save(self.source)
        self.manager = ProjectManager(self.root)
        self.project = self.manager.create_project(self.source, "animation", 1, 3, "white")
        self.project_path = self.manager.project_path(self.project["id"])

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_fps_cursor_and_cache_rules(self) -> None:
        self.assertEqual(validate_fps("12"), 12)
        self.assertEqual(fps_interval_ms(12), 83)
        self.assertEqual(fps_interval_ms(24), 42)
        self.assertEqual(fps_interval_ms(60), 17)
        with self.assertRaises(AnimationPreviewError):
            validate_fps("0")
        self.assertEqual(next_frame_index(0, 3), 1)
        self.assertEqual(next_frame_index(2, 3), None)
        self.assertEqual(next_frame_index(2, 3, loop=True), 0)

        cache = PreviewFrameCache(2)
        cache.put("one", Image.new("RGBA", (2, 2), (1, 2, 3, 255)))
        cache.put("two", Image.new("RGBA", (2, 2), (4, 5, 6, 255)))
        cache.put("three", Image.new("RGBA", (2, 2), (7, 8, 9, 255)))
        self.assertEqual(len(cache), 2)
        self.assertNotIn("one", cache)
        cache.clear()
        self.assertEqual(len(cache), 0)

    def test_all_sources_use_disk_sequences_and_reject_stale_results(self) -> None:
        run_pipeline(self.project, self.project_path)
        raw = resolve_animation_source(self.project, self.project_path, "original")
        stage_input = resolve_animation_source(self.project, self.project_path, "stage_input", 0)
        stage_result = resolve_animation_source(self.project, self.project_path, "stage_result", 0)
        final = resolve_animation_source(self.project, self.project_path, "final_result")
        self.assertEqual(raw.frame_count, 3)
        self.assertEqual(stage_input.directory, raw.directory)
        self.assertEqual(stage_result.frame_names, final.frame_names)
        self.assertEqual(read_frame(final, 0).mode, "RGBA")

        stage = self.project["pipeline"]["stages"][0]
        stage["status"] = "dirty"
        with self.assertRaisesRegex(AnimationPreviewError, "incomplete") as context:
            resolve_animation_source(self.project, self.project_path, "stage_result", 0)
        self.assertEqual(context.exception.message_key, "error.animation_incomplete_stage")

        self.project["pipeline"]["stages"][0]["status"] = "complete"
        (stage_result.directory / stage_result.frame_names[-1]).unlink()
        with self.assertRaises(AnimationPreviewError) as missing:
            resolve_animation_source(self.project, self.project_path, "stage_result", 0)
        self.assertEqual(missing.exception.message_key, "error.animation_incomplete_stage")


class AnimationPreviewUiStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.root = Path(self.temp.name)
        (self.root / "settings.json").write_text(json.dumps({"language": "en_US"}), encoding="utf-8")
        self.source = self.root / "source.png"
        image = Image.new("RGBA", (16, 8), (0, 0, 0, 255))
        image.paste((255, 255, 255, 255), (2, 2, 6, 6))
        image.save(self.source)
        self.app = GameAssetKeyerApp(self.root)
        self.app.root.withdraw()
        project = self.app.pm.create_project(self.source, "animation-ui", 1, 1, "white")
        run_pipeline(project, self.app.pm.project_path(project["id"]))
        self.app.pm.save_project(project["id"], project)
        self.app.load_project(project["id"])

    def tearDown(self) -> None:
        self.app.root.destroy()
        self.temp.cleanup()

    def test_play_stop_restores_static_view_and_does_not_change_selection(self) -> None:
        original_selection = self.app.frame_listbox.curselection()
        static = np.asarray(self.app.right_preview_canvas.source_image).copy()
        with patch.object(self.app.root, "after", return_value="animation-job") as after, patch.object(self.app.root, "after_cancel") as cancel:
            self.app.play_animation()
            self.assertTrue(self.app._animation_playing)
            self.assertEqual(self.app.frame_listbox.curselection(), original_selection)
            self.assertEqual(str(self.app.animation_fps_spinbox.cget("state")), "disabled")
            self.app.stop_animation()
            cancel.assert_called_once_with("animation-job")
            after.assert_called_once()
        self.assertFalse(self.app._animation_playing)
        self.assertEqual(self.app.current_frame_index, 1)
        self.assertEqual(self.app.right_view_var.get(), "result")
        self.assertEqual(self.app.frame_listbox.curselection(), original_selection)
        self.assertTrue(np.array_equal(np.asarray(self.app.right_preview_canvas.source_image), static))

    def test_view_switch_stops_playback_and_invalid_fps_is_friendly(self) -> None:
        with patch.object(self.app.root, "after", return_value="animation-job"), patch.object(self.app.root, "after_cancel") as cancel:
            self.app.play_animation()
            self.app.show_preview_view("final")
            self.assertFalse(self.app._animation_playing)
            cancel.assert_called_once_with("animation-job")
        self.app.animation_fps_var.set("61")
        with patch("app.ui_main.messagebox.showerror") as showerror:
            self.app.play_animation()
        showerror.assert_called_once()
        self.assertFalse(self.app._animation_playing)


if __name__ == "__main__":
    unittest.main()
