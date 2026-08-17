from __future__ import annotations

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0

import tempfile
import unittest
from pathlib import Path

from PIL import Image

from app.frame_sequence_composer import (
    calculate_grid,
    calculate_layout,
    compose_sprite_sheet,
    export_sprite_sheet,
    list_png_files,
    natural_sort_key,
)
from app.ui.frame_sequence_composer_dialog import choose_auto_output_path


class FrameSequenceComposerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write(self, name: str, size: tuple[int, int], mode: str, color: tuple[int, ...]) -> Path:
        path = self.root / name
        Image.new(mode, size, color).save(path)
        return path

    def test_natural_sort_and_non_recursive_visible_png_selection(self) -> None:
        self._write("frame_10.png", (2, 2), "RGBA", (10, 0, 0, 255))
        self._write("frame_2.png", (2, 2), "RGBA", (2, 0, 0, 255))
        self._write("frame_1.png", (2, 2), "RGBA", (1, 0, 0, 255))
        self._write(".hidden.png", (2, 2), "RGBA", (99, 0, 0, 255))
        nested = self.root / "nested"
        nested.mkdir()
        nested_marker = self._write("nested-marker.png", (1, 1), "RGBA", (0, 0, 0, 255))
        nested_marker.replace(nested / "nested-marker.png")
        self.assertEqual([path.name for path in list_png_files(self.root)], ["frame_1.png", "frame_2.png", "frame_10.png"])
        self.assertEqual(sorted(["frame_10.png", "frame_2.png", "frame_1.png"], key=natural_sort_key), ["frame_1.png", "frame_2.png", "frame_10.png"])

    def test_layout_alignment_padding_alpha_and_non_integer_grid(self) -> None:
        paths = [
            self._write("frame_1.png", (100, 100), "RGB", (255, 0, 0)),
            self._write("frame_2.png", (80, 120), "RGBA", (0, 255, 0, 128)),
            self._write("frame_3.png", (120, 90), "RGBA", (0, 0, 255, 64)),
        ]
        self.assertEqual(calculate_grid(10, 3), (3, 4))
        layout = calculate_layout(paths, 3, 4)
        self.assertEqual((layout.cell_width, layout.cell_height), (128, 128))
        self.assertEqual((layout.output_width, layout.output_height), (384, 128))
        centered = compose_sprite_sheet(paths, 3, "center", 4)
        bottom = compose_sprite_sheet(paths, 3, "bottom_center", 4)
        self.assertEqual(centered.mode, "RGBA")
        self.assertEqual(centered.size, (384, 128))
        self.assertEqual(centered.getpixel((0, 0))[3], 0)
        # The 80x120 frame keeps its alpha and is bottom-aligned inside the
        # 128px cell (4px padding plus 4px top slack).
        self.assertEqual(bottom.getpixel((192, 120))[3], 128)
        centered.close()
        bottom.close()

    def test_ten_frames_three_columns_have_transparent_last_cells_and_export_rgba(self) -> None:
        paths = [self._write(f"frame_{index}.png", (4 + index, 5), "RGB", (index, 20, 30)) for index in range(1, 11)]
        output = self.root / "out folder" / "中文 sheet.png"
        layout = export_sprite_sheet(paths, output, 3, "center", 0)
        self.assertEqual(layout.rows, 4)
        with Image.open(output) as sheet:
            self.assertEqual(sheet.mode, "RGBA")
            self.assertEqual(sheet.size, (14 * 3, 5 * 4))
            self.assertEqual(sheet.getpixel((14, 19))[3], 0)

    def test_auto_output_tracks_new_sets_but_preserves_manual_paths(self) -> None:
        first = self.root / "first" / "frame_1.png"
        second = self.root / "second" / "frame_2.png"
        first.parent.mkdir()
        second.parent.mkdir()
        auto = str(first.with_name("frame_1_sheet.png"))
        output, marker = choose_auto_output_path([first], "", "")
        self.assertEqual((output, marker), (auto, auto))
        output, marker = choose_auto_output_path([second], output, marker)
        expected_second = str(second.with_name("frame_2_sheet.png"))
        self.assertEqual((output, marker), (expected_second, expected_second))
        manual = str(self.root / "custom" / "keep.png")
        output, marker = choose_auto_output_path([first], manual, marker)
        self.assertEqual((output, marker), (manual, ""))
        output, marker = choose_auto_output_path([], output, marker)
        self.assertEqual((output, marker), (manual, ""))
        output, marker = choose_auto_output_path([], expected_second, expected_second)
        self.assertEqual((output, marker), ("", ""))


if __name__ == "__main__":
    unittest.main()
