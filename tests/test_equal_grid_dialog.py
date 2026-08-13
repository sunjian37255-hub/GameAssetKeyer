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

from PIL import Image

from app.ui.equal_grid_dialog import EqualGridDialog, EqualGridValidationError, validate_equal_grid_values
from app.ui_main import GameAssetKeyerApp


def widget_texts(widget, widget_type) -> list[str]:
    result: list[str] = []
    for child in widget.winfo_children():
        if isinstance(child, widget_type):
            result.append(str(child.cget("text")))
        result.extend(widget_texts(child, widget_type))
    return result


class EqualGridDialogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.root = Path(self.temp.name)
        (self.root / "settings.json").write_text(json.dumps({"language": "zh_CN"}), encoding="utf-8")
        self.source = self.root / "sheet.png"
        Image.new("RGBA", (24, 16), (20, 30, 40, 255)).save(self.source)
        self.output = self.root / "sheet_equal_grid.png"
        self.app = GameAssetKeyerApp(self.root)
        self.app.root.withdraw()

    def tearDown(self) -> None:
        self.app.root.destroy()
        self.temp.cleanup()

    def test_home_contains_standalone_equal_grid_and_workbench_does_not(self) -> None:
        self.assertIn("等分扩展", widget_texts(self.app.page, ttk.Label))
        project = self.app.pm.create_project(self.source, "grid-location", 1, 1, "black")
        self.app.load_project(project["id"])
        self.assertNotIn("等分扩展", widget_texts(self.app.page, ttk.Button))
        self.assertNotIn("等分扩展", widget_texts(self.app.page, ttk.Label))

    def test_dialog_contains_all_required_fields(self) -> None:
        dialog = EqualGridDialog(self.app.root, self.app.t)
        labels = widget_texts(dialog.window, ttk.Label)
        for text in ("输入 PNG", "输出 PNG", "行数", "列数"):
            self.assertIn(text, labels)
        dialog.cancel()

    def test_single_dialog_runs_without_serial_file_or_integer_dialogs(self) -> None:
        request = {"source": self.source, "output": self.output, "rows": 4, "cols": 6}
        with (
            patch("app.ui_main.EqualGridDialog") as dialog_class,
            patch("app.ui_main.normalize_equal_grid", return_value={"output_path": str(self.output)}) as normalize,
            patch("app.ui_main.filedialog.askopenfilename") as ask_open,
            patch("app.ui_main.filedialog.asksaveasfilename") as ask_save,
            patch("app.ui_main.simpledialog.askinteger") as ask_integer,
        ):
            dialog_class.return_value.show.return_value = request
            self.app.run_equal_grid()
        dialog_class.assert_called_once_with(self.app.root, self.app.t)
        normalize.assert_called_once_with(self.source, self.output, 4, 6)
        ask_open.assert_not_called()
        ask_save.assert_not_called()
        ask_integer.assert_not_called()

    def test_validation_accepts_complete_request_and_rejects_invalid_values(self) -> None:
        valid = validate_equal_grid_values({"source": str(self.source), "output": str(self.output), "rows": "4", "cols": "6"})
        self.assertEqual(valid, {"source": self.source, "output": self.output, "rows": 4, "cols": 6})
        invalid_cases = [
            {"source": "", "output": str(self.output), "rows": "4", "cols": "6"},
            {"source": str(self.source), "output": "", "rows": "4", "cols": "6"},
            {"source": str(self.source), "output": str(self.source), "rows": "4", "cols": "6"},
            {"source": str(self.source), "output": str(self.output), "rows": "0", "cols": "6"},
            {"source": str(self.source), "output": str(self.output), "rows": "4", "cols": "abc"},
        ]
        for values in invalid_cases:
            with self.subTest(values=values), self.assertRaises(EqualGridValidationError):
                validate_equal_grid_values(values)


if __name__ == "__main__":
    unittest.main()
