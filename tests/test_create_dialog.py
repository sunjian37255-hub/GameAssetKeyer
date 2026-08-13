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

import numpy as np
from PIL import Image

from app.pipeline import ensure_pipeline
from app.ui.create_project_dialog import (
    CreateProjectDialog,
    CreateProjectValidationError,
    validate_create_values,
)
from app.ui_main import GameAssetKeyerApp


class CreateDialogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.app_root = Path(self.temp.name)
        (self.app_root / "settings.json").write_text(json.dumps({"language": "zh_CN"}), encoding="utf-8")
        self.source = self.app_root / "sheet.png"
        pixels = np.zeros((12, 12, 4), dtype=np.uint8)
        pixels[..., :3] = (255, 255, 255)
        pixels[..., 3] = 255
        pixels[2:10, 2:10, :3] = (20, 30, 40)
        Image.fromarray(pixels, "RGBA").save(self.source)
        self.app = GameAssetKeyerApp(self.app_root)
        self.app.root.withdraw()

    def tearDown(self) -> None:
        self.app.root.destroy()
        self.temp.cleanup()

    def _values(self, **changes: str) -> dict[str, str]:
        values = {
            "source": str(self.source),
            "name": "rc3_project",
            "rows": "3",
            "cols": "3",
            "frame_interval": "1",
            "target_mode": "black",
            "custom_color": "#000000",
        }
        values.update(changes)
        return values

    def test_three_home_entries_use_one_dialog_without_serial_simpledialogs(self) -> None:
        with (
            patch("app.ui_main.CreateProjectDialog") as dialog_class,
            patch("app.ui_main.simpledialog.askstring") as ask_string,
            patch("app.ui_main.simpledialog.askinteger") as ask_integer,
            patch("app.ui_main.filedialog.askopenfilename") as ask_file,
        ):
            dialog_class.return_value.show.return_value = None
            self.app.create_image_project()
            self.app.create_sheet_project()
            self.app.create_video_project()

        self.assertEqual([call.args[1] for call in dialog_class.call_args_list], ["image", "sheet", "video"])
        ask_string.assert_not_called()
        ask_integer.assert_not_called()
        ask_file.assert_not_called()

    def test_dialog_fields_are_specific_to_each_project_kind(self) -> None:
        expected = {
            "image": (False, False, False),
            "sheet": (True, True, False),
            "video": (False, False, True),
        }
        for kind, fields in expected.items():
            with self.subTest(kind=kind):
                dialog = CreateProjectDialog(self.app.root, kind, self.app.t, self.app.mode_labels())
                labels = {
                    child.cget("text")
                    for child in dialog.window.winfo_children()[0].winfo_children()
                    if isinstance(child, ttk.Label)
                }
                self.assertEqual(self.app.t("create.rows") in labels, fields[0])
                self.assertEqual(self.app.t("create.cols") in labels, fields[1])
                self.assertEqual(self.app.t("create.frame_interval") in labels, fields[2])
                self.assertIn(self.app.t("create.input_file"), labels)
                self.assertIn(self.app.t("create.target_color"), labels)
                dialog.cancel()

    def test_all_target_colors_initialize_project_json_stage_one_and_ui(self) -> None:
        cases = [
            ("black", "#000000", 3, 3),
            ("white", "#FFFFFF", 2, 2),
            ("green", "#00FF00", 4, 4),
            ("magenta", "#FF00FF", 3, 3),
            ("custom", "#171717", 3, 3),
        ]
        for mode, color, rows, cols in cases:
            with self.subTest(mode=mode):
                request = validate_create_values(
                    "sheet",
                    self._values(name=f"rc3_{mode}", rows=str(rows), cols=str(cols), target_mode=mode, custom_color=color),
                )
                with patch("app.ui_main.CreateProjectDialog") as dialog_class:
                    dialog_class.return_value.show.return_value = request
                    self.app.create_sheet_project()

                project_path = self.app.pm.project_path(self.app.current_project_id)
                saved = json.loads((project_path / "project.json").read_text(encoding="utf-8"))
                stage = ensure_pipeline(self.app.current_project)["stages"][0]
                self.assertEqual(saved["target_mode"], mode)
                self.assertEqual(saved["custom_color"], color)
                self.assertEqual(saved["pipeline"]["stages"][0]["params"]["target_mode"], mode)
                self.assertEqual(saved["pipeline"]["stages"][0]["params"]["custom_color"], color)
                self.assertEqual(stage["params"]["target_mode"], mode)
                self.assertEqual(stage["params"]["custom_color"], color)
                self.assertEqual(self.app.mode_var.get(), self.app.mode_labels()[mode])
                self.assertEqual(self.app.custom_color_var.get(), color)
                self.assertEqual(self.app.frame_listbox.size(), rows * cols)

    def test_invalid_dimensions_and_name_do_not_validate(self) -> None:
        for field in ("rows", "cols"):
            for value in ("0", "-1", "abc", ""):
                with self.subTest(field=field, value=value):
                    with self.assertRaises(CreateProjectValidationError):
                        validate_create_values("sheet", self._values(**{field: value}))
        for name in ("", "bad/name", "bad*name"):
            with self.subTest(name=name):
                with self.assertRaises(CreateProjectValidationError):
                    validate_create_values("sheet", self._values(name=name))

    def test_cancel_creates_no_project(self) -> None:
        before = sorted(path.name for path in self.app.pm.projects_root.iterdir())
        with (
            patch("app.ui_main.CreateProjectDialog") as dialog_class,
            patch.object(self.app.pm, "create_project") as create_image,
            patch.object(self.app.pm, "create_video_project") as create_video,
        ):
            dialog_class.return_value.show.return_value = None
            self.app.create_sheet_project()
            self.app.create_image_project()
            self.app.create_video_project()
        after = sorted(path.name for path in self.app.pm.projects_root.iterdir())
        self.assertEqual(before, after)
        create_image.assert_not_called()
        create_video.assert_not_called()

    def test_single_png_and_video_requests_have_only_applicable_parameters(self) -> None:
        image_request = validate_create_values("image", self._values(name="single_png", rows="", cols=""))
        self.assertNotIn("rows", image_request)
        self.assertNotIn("cols", image_request)
        self.assertNotIn("frame_interval", image_request)

        video = self.app_root / "sample.mp4"
        video.write_bytes(b"placeholder")
        video_request = validate_create_values("video", self._values(source=str(video), name="video", frame_interval="2"))
        self.assertEqual(video_request["frame_interval"], 2)
        self.assertNotIn("rows", video_request)
        self.assertNotIn("cols", video_request)


if __name__ == "__main__":
    unittest.main()
