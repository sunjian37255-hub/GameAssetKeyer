from __future__ import annotations

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0

import tempfile
import unittest
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from PIL import Image

from app.pipeline import ensure_pipeline
from app.final_result import FinalResultSource
from app.ui_main import GameAssetKeyerApp


class UiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.app_root = Path(self.temp.name)
        (self.app_root / "settings.json").write_text(json.dumps({"language": "zh_CN"}), encoding="utf-8")
        self.source = self.app_root / "source.png"
        pixels = np.zeros((8, 8, 4), dtype=np.uint8)
        pixels[..., :3] = (255, 255, 255)
        pixels[..., 3] = 255
        pixels[2:6, 2:6, :3] = (20, 30, 40)
        Image.fromarray(pixels, "RGBA").save(self.source)
        self.app = GameAssetKeyerApp(self.app_root)
        self.app.root.withdraw()

    def tearDown(self) -> None:
        self.app.root.destroy()
        self.temp.cleanup()

    def test_home_and_workbench_stage_actions(self) -> None:
        self.assertTrue(self.app.page.winfo_children())
        project = self.app.pm.create_project(self.source, "ui-smoke", 1, 1, "white")
        project_id = project["id"]
        self.app.load_project(project_id)

        stages = ensure_pipeline(self.app.current_project)["stages"]
        self.assertEqual(stages[0]["params"]["target_mode"], "white")
        self.assertEqual(self.app.frame_listbox.size(), 1)
        self.assertEqual(self.app.mode_var.get(), "白色")

        self.app.add_stage_ui()
        self.assertEqual(len(stages), 2)
        self.app.duplicate_stage_ui()
        self.assertEqual(len(stages), 3)
        self.app.toggle_stage_ui(1, False)
        self.assertFalse(stages[1]["enabled"])
        self.app.move_stage_ui(-1)
        self.app.delete_stage_ui()
        self.assertEqual(len(stages), 2)

    def test_recent_project_context_menu_keeps_double_click_and_has_three_actions(self) -> None:
        project = self.app.pm.create_project(self.source, "recent-menu", 1, 1, "white")
        self.app.show_home()
        self.assertTrue(self.app.recent_tree.bind("<Double-1>"))
        self.assertTrue(self.app.recent_tree.bind("<Button-3>"))
        labels = [self.app.recent_project_menu.entrycget(index, "label") for index in range(3)]
        self.assertEqual(labels, ["打开项目", "重命名", "删除"])
        self.app.recent_tree.selection_set(project["id"])
        with patch.object(self.app, "load_project") as load_project:
            self.app.open_recent_project()
        load_project.assert_called_once_with(project["id"])

    def test_recent_project_rename_changes_display_name_without_moving_directory(self) -> None:
        project = self.app.pm.create_project(self.source, "rename-project", 1, 1, "white")
        project_path = self.app.pm.project_path(project["id"])
        self.app.show_home()
        self.app.recent_tree.selection_set(project["id"])
        with patch("app.ui_main.ProjectNameDialog") as dialog_class:
            dialog_class.return_value.show.return_value = "新的显示名称"
            self.app.rename_recent_project()
        self.assertTrue(project_path.is_dir())
        self.assertEqual(self.app.pm.load_project(project["id"])["name"], "新的显示名称")
        self.assertIn(project["id"], self.app.recent_tree.get_children())
        self.assertEqual(self.app.recent_tree.item(project["id"], "text"), "新的显示名称")

    def test_recent_project_delete_requires_confirmation(self) -> None:
        project = self.app.pm.create_project(self.source, "delete-project", 1, 1, "white")
        project_path = self.app.pm.project_path(project["id"])
        self.app.show_home()
        self.app.recent_tree.selection_set(project["id"])
        with patch("app.ui_main.messagebox.askyesno", return_value=False):
            self.app.delete_recent_project()
        self.assertTrue(project_path.is_dir())

        with patch("app.ui_main.messagebox.askyesno", return_value=True):
            self.app.delete_recent_project()
        self.assertFalse(project_path.exists())

    def test_eyedropper_and_coordinate_mapping(self) -> None:
        project = self.app.pm.create_project(self.source, "eyedropper", 1, 1, "white")
        self.app.load_project(project["id"])
        canvas = self.app.preview_canvas
        canvas.set_image(Image.new("RGBA", (200, 100), (1, 2, 3, 255)))
        canvas.display_box = (10, 20, 110, 70)
        self.assertEqual(canvas.canvas_to_image(60, 45), (100, 50))
        self.assertIsNone(canvas.canvas_to_image(110, 70))

        self.app._eyedropper_selected((17, 34, 51))
        self.assertEqual(self.app.custom_color_var.get(), "#112233")
        self.assertEqual(self.app.mode_var.get(), "自定义")
        self.assertEqual(self.app.collect_params()["target_mode"], "custom")

    def test_eyedropper_samples_both_displayed_images_for_all_project_types(self) -> None:
        for project_type in ("image", "sprite_sheet", "video"):
            with self.subTest(project_type=project_type):
                project = self.app.pm.create_project(self.source, f"eyedropper-{project_type}", 1, 1, "white")
                project["project_type"] = project_type
                self.app.pm.save_project(project["id"], project)
                self.app.load_project(project["id"])
                self.app.preview_images = {
                    "original": Image.new("RGBA", (4, 4), (11, 22, 33, 255)),
                    "input": Image.new("RGBA", (4, 4), (44, 55, 66, 255)),
                    "result": Image.new("RGBA", (4, 4), (77, 88, 99, 255)),
                    "final": Image.new("RGBA", (4, 4), (111, 122, 133, 255)),
                }
                self.app.show_preview_view("input")
                self.app.show_preview_view("result")
                self.app.left_preview_canvas.display_box = (10, 10, 50, 50)
                self.app.right_preview_canvas.display_box = (20, 20, 60, 60)

                self.app.start_eyedropper()
                self.assertTrue(self.app._eyedropper_active)
                self.assertEqual(self.app.left_preview_canvas.cget("cursor"), "crosshair")
                self.assertEqual(self.app.right_preview_canvas.cget("cursor"), "crosshair")
                self.app.left_preview_canvas._on_click(SimpleNamespace(x=30, y=30))
                self.assertEqual(self.app.custom_color_var.get(), "#2C3742")
                self.assertEqual(self.app.mode_var.get(), "自定义")
                self.assertFalse(self.app._eyedropper_active)

                self.app.preview_images["original"] = Image.new("RGBA", (4, 4), (11, 22, 33, 255))
                self.app.show_preview_view("original")
                self.app.left_preview_canvas.display_box = (10, 10, 50, 50)
                self.app.start_eyedropper()
                self.app.left_preview_canvas._on_click(SimpleNamespace(x=30, y=30))
                self.assertEqual(self.app.custom_color_var.get(), "#0B1621")

                self.app.preview_images["final"] = Image.new("RGBA", (4, 4), (111, 122, 133, 255))
                self.app.show_preview_view("final")
                self.app.right_preview_canvas.display_box = (20, 20, 60, 60)
                self.app.start_eyedropper()
                self.app.right_preview_canvas._on_click(SimpleNamespace(x=40, y=40))
                self.assertEqual(self.app.custom_color_var.get(), "#6F7A85")
                self.assertEqual(self.app.collect_params()["target_mode"], "custom")
                self.assertIsNone(self.app.left_preview_canvas.eyedropper_callback)
                self.assertIsNone(self.app.right_preview_canvas.eyedropper_callback)

    def test_eyedropper_outside_transparent_and_cancel_lifecycle(self) -> None:
        project = self.app.pm.create_project(self.source, "eyedropper-lifecycle", 1, 1, "white")
        self.app.load_project(project["id"])
        left = self.app.left_preview_canvas
        right = self.app.right_preview_canvas
        original_color = self.app.custom_color_var.get()
        left.set_image(Image.new("RGBA", (4, 4), (10, 20, 30, 255)))
        right.set_image(Image.new("RGBA", (4, 4), (40, 50, 60, 0)))
        left.display_box = (10, 10, 50, 50)
        right.display_box = (10, 10, 50, 50)

        self.app.start_eyedropper()
        left._on_click(SimpleNamespace(x=5, y=5))
        self.assertEqual(self.app.custom_color_var.get(), original_color)
        self.assertTrue(self.app._eyedropper_active)
        self.assertIsNotNone(left.eyedropper_callback)
        self.assertIsNotNone(right.eyedropper_callback)
        self.assertEqual(self.app.status_var.get(), self.app.t("status.eyedropper_outside"))

        right._on_click(SimpleNamespace(x=30, y=30))
        self.assertEqual(self.app.custom_color_var.get(), original_color)
        self.assertFalse(self.app._eyedropper_active)
        self.assertEqual(left.cget("cursor"), "")
        self.assertEqual(right.cget("cursor"), "")
        self.assertEqual(self.app.status_var.get(), self.app.t("status.eyedropper_transparent"))

        self.app.start_eyedropper()
        self.app.start_eyedropper()
        self.assertFalse(self.app._eyedropper_active)
        self.assertEqual(self.app.status_var.get(), self.app.t("status.eyedropper_cancelled"))

        self.app.start_eyedropper()
        self.assertEqual(self.app.cancel_eyedropper(SimpleNamespace()), "break")
        self.assertFalse(self.app._eyedropper_active)

    def test_dual_preview_defaults_and_stage_refresh(self) -> None:
        project = self.app.pm.create_project(self.source, "dual-preview", 1, 1, "white")
        self.app.load_project(project["id"])

        self.assertIsNot(self.app.left_preview_canvas, self.app.right_preview_canvas)
        self.assertEqual(self.app.left_view_var.get(), "input")
        self.assertEqual(self.app.right_view_var.get(), "result")
        self.assertTrue(np.array_equal(np.asarray(self.app.left_preview_canvas.source_image), np.asarray(self.app.preview_images["input"])))
        self.assertTrue(np.array_equal(np.asarray(self.app.right_preview_canvas.source_image), np.asarray(self.app.preview_images["result"])))

        self.app.add_stage_ui()
        self.assertEqual(self.app.selected_stage_index, 1)
        self.assertTrue(np.array_equal(np.asarray(self.app.left_preview_canvas.source_image), np.asarray(self.app.preview_images["input"])))
        self.assertTrue(np.array_equal(np.asarray(self.app.right_preview_canvas.source_image), np.asarray(self.app.preview_images["result"])))
        self.app.show_preview_view("final")
        self.assertEqual(self.app.right_view_var.get(), "final")
        self.assertTrue(np.array_equal(np.asarray(self.app.right_preview_canvas.source_image), np.asarray(self.app.preview_images["final"])))

    def test_parameter_scrollbar_visible_at_default_size_and_125_percent_scaling(self) -> None:
        self.app.root.tk.call("tk", "scaling", 1.6666667)
        project = self.app.pm.create_project(self.source, "layout", 1, 1, "white")
        self.app.load_project(project["id"])
        self.app.root.geometry("1360x820+0+0")
        self.app.root.deiconify()
        self.app.root.update()

        scrollbar = self.app.pipeline_scroll.scrollbar
        root_right = self.app.root.winfo_rootx() + self.app.root.winfo_width()
        scrollbar_right = scrollbar.winfo_rootx() + scrollbar.winfo_width()
        self.assertTrue(scrollbar.winfo_ismapped())
        self.assertGreater(scrollbar.winfo_height(), 100)
        self.assertLessEqual(scrollbar_right, root_right)
        self.app.toggle_advanced()
        self.app.root.update_idletasks()
        self.app.pipeline_scroll.canvas.yview_moveto(1.0)
        self.app.root.update_idletasks()
        self.assertAlmostEqual(self.app.pipeline_scroll.canvas.yview()[1], 1.0, places=3)
        self.assertTrue(self.app.cancel_button.winfo_ismapped())
        self.app.root.withdraw()

    def test_export_opens_actual_output_directory_after_success(self) -> None:
        project = self.app.pm.create_project(self.source, "export-folder", 1, 1, "white")
        self.app.load_project(project["id"])
        output = self.app.project_path() / "exports" / "final result.png"
        output.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGBA", (2, 2), (0, 0, 0, 0)).save(output)
        metadata = {"sheet": str(output), "preview": str(output.parent / "preview.png")}
        source_dir = self.app.project_path() / "01_frames_raw"
        final_source = FinalResultSource("pipeline", source_dir, "test", ("frame_000001.png",))

        with (
            patch("app.ui_main.resolve_final_result_source", return_value=final_source),
            patch("app.ui_main.simpledialog.askstring", return_value=output.name),
            patch("app.ui_main.export_sheet", return_value=metadata),
            patch("app.ui_main.os.startfile") as startfile,
        ):
            self.app.run_export()
            self.app.root.update_idletasks()

        startfile.assert_called_once_with(str(output.parent))

    def test_video_export_uses_frame_sequence_and_opens_final_frames(self) -> None:
        project = self.app.pm.create_project(self.source, "video-export-ui", 1, 1, "white")
        project["project_type"] = "video"
        self.app.pm.save_project(project["id"], project)
        self.app.load_project(project["id"])
        source_dir = self.app.project_path() / "01_frames_raw"
        final_source = FinalResultSource("pipeline", source_dir, "test", ("frame_000001.png",))
        output_dir = self.app.project_path() / "exports" / "final_frames"
        output_dir.mkdir(parents=True)
        Image.new("RGBA", (2, 2), (0, 0, 0, 0)).save(output_dir / "frame_000001.png")
        metadata = {"directory": str(output_dir), "frame_count": 1, "source_kind": "pipeline"}

        with (
            patch("app.ui_main.resolve_final_result_source", return_value=final_source),
            patch("app.ui_main.export_png_frame_sequence", return_value=metadata) as export_sequence,
            patch("app.ui_main.simpledialog.askstring") as askstring,
            patch("app.ui_main.os.startfile") as startfile,
        ):
            self.app.run_export()
            self.app.root.update_idletasks()

        export_sequence.assert_called_once_with(final_source, output_dir)
        askstring.assert_not_called()
        startfile.assert_called_once_with(str(output_dir))

    def test_basic_stage_params_start_at_zero_and_follow_frame_navigation(self) -> None:
        sheet = self.app_root / "two-frames.png"
        pixels = np.zeros((8, 16, 4), dtype=np.uint8)
        pixels[..., 3] = 255
        pixels[2:6, 2:6, :3] = (20, 30, 40)
        pixels[2:6, 10:14, :3] = (50, 60, 70)
        Image.fromarray(pixels, "RGBA").save(sheet)
        project = self.app.pm.create_project(sheet, "shared-stage-defaults", 1, 2, "white")
        stage = ensure_pipeline(project)["stages"][0]
        self.assertEqual(stage["params"]["background_threshold"], 0.0)
        self.assertEqual(stage["params"]["foreground_threshold"], 0.0)
        self.assertEqual(stage["params"]["feather_radius"], 0.0)
        self.assertEqual(stage["params"]["edge_erode"], 0)
        self.assertEqual(stage["params"]["alpha_gamma"], 1.0)

        self.app.load_project(project["id"])
        self.app.bg_threshold_var.set(0.23)
        self.app.fg_threshold_var.set(0.71)
        self.app.feather_var.set(2.5)
        self.app.edge_erode_var.set(2)
        self.app.frame_listbox.selection_clear(0, "end")
        self.app.frame_listbox.selection_set(1)
        self.app.on_frame_select()

        stage = ensure_pipeline(self.app.current_project)["stages"][0]
        self.assertEqual(self.app.current_frame_index, 2)
        self.assertEqual(stage["params"]["background_threshold"], 0.23)
        self.assertEqual(stage["params"]["foreground_threshold"], 0.71)
        self.assertEqual(stage["params"]["feather_radius"], 2.5)
        self.assertEqual(stage["params"]["edge_erode"], 2)
        self.assertEqual(self.app.bg_threshold_var.get(), 0.23)
        self.assertEqual(self.app.fg_threshold_var.get(), 0.71)
        self.assertNotIn("frame_000001.png", stage["frame_params"])

    def test_language_switch_preserves_project_stage_frame_and_params(self) -> None:
        project = self.app.pm.create_project(self.source, "language", 1, 1, "white")
        self.app.load_project(project["id"])
        self.app.intensity_var.set(4)
        self.app.save_selected_stage()
        self.app.language_combo.set("English")
        self.app.on_language_change()

        self.assertEqual(self.app.i18n.locale, "en_US")
        self.assertEqual(self.app.current_project_id, project["id"])
        self.assertEqual(self.app.current_frame_index, 1)
        self.assertEqual(self.app.selected_stage_index, 0)
        self.assertEqual(self.app.mode_var.get(), "White")
        self.assertEqual(self.app.intensity_var.get(), 4)
        self.assertEqual(json.loads((self.app_root / "settings.json").read_text(encoding="utf-8"))["language"], "en_US")

    def test_process_current_frame_saves_separate_settings(self) -> None:
        project = self.app.pm.create_project(self.source, "current-frame", 1, 1, "white")
        self.app.load_project(project["id"])
        self.app.intensity_var.set(5)
        self.app.process_current_frame_ui()
        self.app.worker.join(10)
        self.app.poll_worker_events()
        stage = ensure_pipeline(self.app.current_project)["stages"][0]
        self.assertEqual(stage["frame_params"]["frame_000001.png"]["intensity"], 5)
        self.assertIn("frame_000001.png", self.app.status_var.get())
        self.app.clear_current_frame_override_ui()
        self.assertNotIn("frame_000001.png", stage["frame_params"])


if __name__ == "__main__":
    unittest.main()
