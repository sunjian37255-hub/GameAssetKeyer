"""Qt integration tests: use disposable projects, never the user's asset library."""
# SPDX-License-Identifier: MPL-2.0
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import cv2
import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_SCALE_FACTOR", "1.25")

from PIL import Image, ImageDraw
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QSlider

from app.final_result import resolve_final_result_source
from app.pipeline import run_pipeline
from app.qt_ui.common import apply_theme
from app.qt_ui.dialogs import CreateDialog, PostprocessDialog
from app.qt_ui.session import render_preview
from app.qt_ui.tools_dialog import ToolDialog
from app.qt_ui.window import Window

APP = QApplication.instance() or QApplication([])
APP.setStyle("Fusion")


class WorkbenchTests(unittest.TestCase):
    def test_frozen_plain_theme_hides_skin_and_disables_gpu(self):
        import sys
        from PySide6.QtWidgets import QPushButton
        with patch.object(sys, "frozen", True, create=True), patch("app.qt_ui.window.ASSETS", self.root / "absent"):
            release_window = Window(self.root)
            try:
                self.assertEqual(release_window.windowTitle(), "GameAssetKeyer")
                self.assertFalse(release_window.material)
                self.assertFalse(release_window.backend.isEnabled())
                self.assertEqual(release_window.backend.currentData(), "cpu")
                skins = [item for item in release_window.findChildren(QPushButton) if item.text() == "Materials"]
                self.assertEqual(len(skins), 1)
                self.assertTrue(skins[0].isHidden())
            finally:
                release_window.close()

    def setUp(self):
        temp_root = "I:/CodexSafeCheck" if Path("I:/CodexSafeCheck").is_dir() else None
        self.temp = tempfile.TemporaryDirectory(prefix="gak-qt-test-", dir=temp_root)
        self.root = Path(self.temp.name)
        (self.root / "settings.json").write_text(json.dumps({"language": "en_US"}), encoding="utf-8")
        image = Image.new("RGBA", (48, 24), (0, 255, 0, 255))
        draw = ImageDraw.Draw(image)
        draw.rectangle((5, 5, 15, 17), fill=(240, 60, 30, 255))
        draw.rectangle((30, 5, 41, 17), fill=(240, 60, 30, 255))
        self.source = self.root / "中文 空格.png"
        image.save(self.source)
        self.window = Window(self.root)
        self.window.fail = lambda error: self.fail(str(error))
        self.window.resize(1420, 780)
        self.window.show()
        APP.processEvents()
        data = self.window.session.manager.create_project(self.source, "Test", 1, 2, "green")
        self.project_id = data["id"]

    def settle(self):
        deadline = time.monotonic() + 20
        while self.window.jobs.busy or self.window.debounce.isActive():
            APP.processEvents()
            QTest.qWait(10)
            if time.monotonic() > deadline:
                self.fail("Background job failed to finish")
        APP.processEvents()

    def open(self):
        self.window.open_project(self.project_id)
        self.settle()
        return self.window.session

    def processed(self):
        session = self.open()
        self.window.editor.fields["background_threshold"].setValue(.2)
        self.window.editor.fields["foreground_threshold"].setValue(.7)
        self.settle()
        self.window.process(True)
        self.settle()
        return session

    def tearDown(self):
        self.settle()
        self.window.close()
        self.window.deleteLater()
        APP.processEvents()
        self.temp.cleanup()

    def test_editable_dual_preview_and_worker(self):
        session = self.processed()
        self.assertFalse(self.window.left.image.isNull())
        self.assertFalse(self.window.right.image.isNull())
        self.assertTrue(self.window.left.isVisible())
        self.assertTrue(self.window.right.isVisible())
        self.assertTrue(self.window.editor.isEnabled())
        self.assertIsNotNone(resolve_final_result_source(session.project, session.directory))
        self.assertIsNotNone(self.window.images["final"])

    def test_defaults_persist_across_frames_and_override_is_separate(self):
        session = self.open()
        self.window.editor.fields["background_threshold"].setValue(.35)
        self.settle()
        self.window.frame_list.setCurrentRow(1)
        self.settle()
        self.assertEqual(session.params()["background_threshold"], .35)

        self.window.make_override()
        self.settle()
        self.window.editor.fields["background_threshold"].setValue(.55)
        self.settle()
        self.window.frame_list.setCurrentRow(0)
        self.settle()
        self.assertEqual(session.params()["background_threshold"], .35)
        self.window.frame_list.setCurrentRow(1)
        self.settle()
        self.assertEqual(session.params()["background_threshold"], .55)
        self.window.clear_override()
        self.settle()
        self.assertEqual(session.params()["background_threshold"], .35)

    def test_intensity_slider_preserves_range_preview_and_saved_settings(self):
        session = self.open()
        editor = self.window.editor
        slider = editor.fields["intensity"]
        self.assertIsInstance(slider, QSlider)
        self.assertEqual(slider.orientation(), Qt.Orientation.Horizontal)
        self.assertEqual((slider.minimum(), slider.maximum(), slider.singleStep()), (1, 5, 1))
        before = editor.collect()
        slider.setFocus()
        QTest.keyClick(slider, Qt.Key.Key_End)
        self.settle()
        self.assertEqual(session.params()["intensity"], 5)
        self.assertEqual(editor.intensity_value.text(), "5 / 5")
        self.assertEqual(editor.intensity_hint.text(), self.window.t("intensity.green.5"))
        self.assertEqual(editor.collect(), {**before, "intensity": 5})
        self.window.frame_list.setCurrentRow(1)
        self.settle()
        self.assertEqual(slider.value(), 5)
        self.window.make_override()
        self.settle()
        QTest.keyClick(slider, Qt.Key.Key_Home)
        self.settle()
        self.assertEqual(session.params()["intensity"], 1)
        self.window.frame_list.setCurrentRow(0)
        self.settle()
        self.assertEqual(slider.value(), 5)
        self.assertEqual(editor.intensity_value.text(), "5 / 5")
        self.assertIsNotNone(self.window.images.get("result"))

    def test_stage_two_and_repair_controls(self):
        session = self.processed()
        self.window.change_stage("repair")
        self.settle()
        self.assertEqual(len(session.stages), 2)
        self.assertEqual(session.params()["operation"], "despill")
        self.assertTrue(self.window.editor.repair_body.isVisible())
        self.window.process(True)
        self.settle()
        self.assertEqual(self.window.images["input"].size, (24, 24))
        self.assertIsNotNone(self.window.images["final"])
        self.window.stage_list.item(1).setCheckState(Qt.CheckState.Unchecked)
        self.settle()
        self.assertFalse(session.stages[1]["enabled"])
        self.window.change_stage("up")
        self.settle()
        self.assertEqual(session.stage_index, 0)

    def test_current_frame_processing_uses_existing_worker(self):
        session = self.open()
        self.window.process(False)
        self.settle()
        self.assertTrue(session.has_override())
        self.assertIsNone(resolve_final_result_source(session.project, session.directory))
        self.assertIsNone(self.window.images["final"])

    def test_trim_alignment_final_matches_export_and_invalidation(self):
        session = self.processed()
        self.window.start_job("trim", lambda: session.trim(8, 0))
        self.settle()
        self.window.start_job("align", lambda: session.align("center"))
        self.settle()
        final = resolve_final_result_source(session.project, session.directory)
        self.assertEqual(final.kind, "align")
        preview = self.window.images["final"]
        self.assertLess(preview.width, 24)
        folder = session.export("透明 成品.png")
        with Image.open(folder / "透明 成品.png") as output:
            self.assertEqual(output.mode, "RGBA")
            self.assertEqual(output.size, (preview.width * 2, preview.height))
        self.window.editor.fields["background_threshold"].setValue(.4)
        self.settle()
        self.assertIsNone(self.window.images["final"])
        with self.assertRaises(ValueError):
            session.export()

    def test_video_export_sequence_replaces_old_extra_frames(self):
        session = self.processed()
        session.project["project_type"] = "video"
        # Replace only the disposable fixture's raw sequence with ten frames.
        raw = session.directory / "01_frames_raw"
        for index in range(10):
            self.window.images["original"].save(raw / f"video_{index:06d}.png")
        for path in raw.glob("frame_*.png"):
            path.unlink()
        for index, path in enumerate(sorted(raw.glob("video_*.png"))):
            path.rename(raw / f"frame_{index:06d}.png")
        run_pipeline(session.project, session.directory)
        session.save()
        folder = session.export()
        self.assertEqual(len(list(folder.glob("*.png"))), 10)
        self.assertFalse((folder.parent / "sheet_transparent.png").exists())
        for path in sorted(raw.glob("frame_*.png"))[6:]:
            path.unlink()
        run_pipeline(session.project, session.directory)
        session.export()
        self.assertEqual(len(list(folder.glob("*.png"))), 6)
        for path in folder.glob("*.png"):
            with Image.open(path) as frame:
                self.assertEqual(frame.mode, "RGBA")

    def test_single_png_export(self):
        session = self.window.session
        project = session.manager.create_project(self.source, "Single", 1, 1, "green")
        session.open(project["id"])
        run_pipeline(session.project, session.directory)
        folder = session.export("single.png")
        with Image.open(folder / "single.png") as image:
            self.assertEqual(image.size, (48, 24))

    def test_export_folder_opens_only_on_success(self):
        session = self.processed()
        with patch("app.qt_ui.window.QDesktopServices.openUrl", return_value=True) as opened:
            self.window.start_job("export", session.export)
            self.settle()
            self.assertEqual(opened.call_count, 1)
            self.assertEqual(Path(opened.call_args.args[0].toLocalFile()), session.directory / "exports")
            self.window.fail = lambda error: None
            self.window.start_job("export", lambda: (_ for _ in ()).throw(ValueError("failure")))
            self.settle()
            self.assertEqual(opened.call_count, 1)

    def test_stale_preview_job_does_not_replace_new_selection(self):
        session = self.open()
        args = session.preview_request()
        self.window.preview_revision = self.window.revision
        self.window.start_job("preview", lambda: (time.sleep(.08), render_preview(*args))[1])
        self.window.editor.fields["background_threshold"].setValue(.7)
        self.window.frame_list.setCurrentRow(1)
        self.settle()
        self.assertEqual(session.frame_index, 1)
        self.assertEqual(session.params()["background_threshold"], .7)
        expected = render_preview(*session.preview_request())["result"]
        self.assertEqual(expected.tobytes(), self.window.images["result"].tobytes())

    def test_create_dialog_validates_all_three_types(self):
        for kind in ("image", "sheet", "video"):
            dialog = CreateDialog(self.window, kind)
            self.assertIs(dialog.parent(), self.window)
            self.assertEqual(dialog.rows is not None, kind == "sheet")
            self.assertEqual(dialog.interval is not None, kind == "video")
            dialog.source.setText(str(self.source))
            dialog.name.setText("Name")
            dialog.accept()
            self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
            self.assertEqual(dialog.request["kind"], kind)

    def test_home_create_uses_real_project_manager(self):
        request = dict(source=self.source, name="New PNG", target_mode="white", custom_color="#FFFFFF")
        with patch("app.qt_ui.window.CreateDialog") as dialog:
            dialog.return_value.exec.return_value = QDialog.DialogCode.Accepted
            dialog.return_value.request = request
            self.window.create_project("image")
        self.settle()
        self.assertEqual(self.window.session.project["name"], "New PNG")
        self.assertEqual(len(self.window.session.frames), 1)
        self.assertEqual(self.window.session.params()["background_threshold"], 0)

    def test_postprocess_dialogs_keep_expected_controls(self):
        trim = PostprocessDialog(self.window, "trim")
        trim.threshold.setValue(10)
        trim.padding.setValue(3)
        trim.accept()
        self.assertEqual(trim.request, (10, 3))
        align = PostprocessDialog(self.window, "align")
        align.accept()
        self.assertEqual(align.request, ("center",))

    def test_compose_tool_rows_columns_and_real_export(self):
        session = self.open()
        dialog = ToolDialog(self.window, "compose")
        dialog.set_files(session.frames)
        dialog.fields["rows"].setValue(2)
        self.assertEqual(dialog.fields["cols"].value(), 1)
        self.assertIn("24 × 48", dialog.info.text())
        dialog.output.setText(str(self.root / "composed.png"))
        dialog.accept()
        with patch("app.qt_ui.window.ToolDialog", return_value=dialog), patch.object(dialog, "exec", return_value=QDialog.DialogCode.Accepted), patch.object(self.window, "open_output") as opened:
            self.window.run_tool("compose")
            self.settle()
            opened.assert_called_once_with(self.root)
        with Image.open(self.root / "composed.png") as image:
            self.assertEqual(image.size, (24, 48))

    def test_grid_dialog_keeps_advanced_values(self):
        dialog = ToolDialog(self.window, "grid")
        dialog.source.setText(str(self.source))
        dialog.output.setText(str(self.root / "expanded.png"))
        dialog.fields["cols"].setValue(2)
        dialog.fields["cell_width"].setValue(32)
        dialog.accept()
        self.assertEqual(dialog.request["cell_width"], 32)
        with patch("app.qt_ui.window.ToolDialog", return_value=dialog), patch.object(dialog, "exec", return_value=QDialog.DialogCode.Accepted), patch.object(self.window, "open_output"):
            self.window.run_tool("grid")
            self.settle()
        self.assertTrue((self.root / "expanded.png").is_file())

    def test_picker_both_views_tracks_image_coordinates_and_alpha(self):
        self.open()
        for canvas in (self.window.left, self.window.right):
            canvas.zoom = 1.7
            canvas.pan = QPointF(13, -9)
            rect = canvas.image_rect()
            point = QPointF(rect.x() + 8.5 * rect.width() / 24, rect.y() + 8.5 * rect.height() / 24)
            self.assertEqual(canvas.image_point(point), (8, 8))
            self.window.pick_button.setChecked(True)
            QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=point.toPoint())
            self.settle()
            self.assertEqual(self.window.editor.color.text(), "#F03C1E")
            self.assertEqual(self.window.editor.mode.currentData(), "custom")

    def test_animation_final_source_and_return_to_editor(self):
        session = self.processed()
        self.window.frame_list.setCurrentRow(1)
        self.settle()
        self.window.right_source.setCurrentIndex(self.window.right_source.findData("final"))
        left_image = self.window.left.image.copy()
        left_width = self.window.left.width()
        top_windows = set(APP.topLevelWidgets())
        self.window.animation_button.click()
        APP.processEvents()
        player = self.window.animation
        self.assertEqual(player.source.frame_count, len(session.frames))
        self.assertEqual(player.source.key, "final_result")
        self.assertFalse(player.canvas.image.isNull())
        self.assertTrue(player.timer.isActive())
        self.assertEqual(set(APP.topLevelWidgets()), top_windows)
        self.assertFalse(player.isWindow())
        self.assertTrue(player.isVisible())
        self.assertFalse(self.window.left.isVisible())
        self.assertFalse(self.window.right.isVisible())
        self.assertGreater(player.canvas.width(), left_width * 1.8)
        player.canvas.zoom = 3
        self.window.fit_preview()
        self.assertEqual(player.canvas.zoom, 1)
        player.seek.setValue(0)
        self.assertEqual(session.frame_index, 1)
        player.back.click()
        APP.processEvents()
        self.assertFalse(player.timer.isActive())
        self.assertEqual(len(player.cache), 0)
        self.assertEqual(self.window.preview_stack.currentIndex(), 0)
        self.assertTrue(self.window.left.isVisible())
        self.assertTrue(self.window.right.isVisible())
        self.assertEqual(self.window.left.image, left_image)
        self.assertEqual(session.frame_index, 1)

    def test_inline_animation_pause_fps_loop_and_stop(self):
        self.processed()
        self.window.animate()
        player = self.window.animation
        player.play.click()
        self.assertFalse(player.timer.isActive())
        self.assertEqual(self.window.preview_stack.currentIndex(), 1)
        player.fps.setValue(20)
        player.play.click()
        self.assertEqual(player.timer.interval(), 50)
        player.seek.setValue(player.source.frame_count - 1)
        player.advance()
        self.assertEqual(player.seek.value(), 0)
        player.loop.setChecked(False)
        player.seek.setValue(player.source.frame_count - 1)
        player.advance()
        self.assertFalse(player.timer.isActive())
        self.window.animation_button.click()
        self.assertEqual(self.window.preview_stack.currentIndex(), 0)

    def test_inline_animation_exits_when_editing_switching_or_leaving(self):
        self.processed()
        self.window.animate()
        self.window.editor.fields["background_threshold"].setValue(.4)
        self.assertFalse(self.window.animation.timer.isActive())
        self.assertEqual(self.window.preview_stack.currentIndex(), 0)
        self.settle()
        self.window.animate()
        # A dirty stage must not expose a stale cached animation.
        self.assertIsNone(self.window.animation.source)
        self.assertFalse(self.window.animation.play.isEnabled())
        self.window.animation.choice.setCurrentIndex(0)
        self.window.animation.play.click()
        self.assertTrue(self.window.animation.timer.isActive())
        self.window.frame_list.setCurrentRow(1)
        self.assertFalse(self.window.animation.timer.isActive())
        self.assertEqual(self.window.preview_stack.currentIndex(), 0)
        self.settle()
        self.window.animate()
        self.window.escape_preview()
        self.assertEqual(self.window.preview_stack.currentIndex(), 0)
        self.window.animate()
        self.window.show_home()
        self.assertFalse(self.window.animation.timer.isActive())
        self.assertEqual(self.window.pages.currentIndex(), 0)

    def test_inline_animation_controls_fit_narrow_window(self):
        self.processed()
        for code in ("en_US", "zh_CN"):
            self.window.language.setCurrentIndex(self.window.language.findData(code))
            self.window.resize(1000, 640)
            self.window.animate()
            APP.processEvents()
            player = self.window.animation
            self.assertTrue(player.isVisible())
            for control in (player.choice, player.play, player.back, player.fps, player.loop, player.seek, player.window_playback):
                self.assertTrue(player.rect().contains(control.mapTo(player, control.rect().bottomRight())))
            self.window.stop_animation()

    def test_window_playback_covers_ui_and_preserves_player_state(self):
        session = self.processed()
        self.window.animate()
        player = self.window.animation
        player.play.click()
        player.seek.setValue(1)
        player.fps.setValue(20)
        player.loop.setChecked(False)
        before = player.canvas.image.copy()
        windows = set(APP.topLevelWidgets())
        window_size = self.window.size()
        inline_size = player.canvas.size()
        for _ in range(3):
            player.window_playback.click()
            APP.processEvents()
            self.assertIs(self.window.workspace_stack.currentWidget(), player)
            self.assertFalse(player.isWindow())
            self.assertEqual(set(APP.topLevelWidgets()), windows)
            self.assertFalse(self.window.isFullScreen())
            self.assertEqual(self.window.size(), window_size)
            self.assertEqual(player.size(), self.window.centralWidget().size())
            self.assertFalse(self.window.header.isVisible())
            self.assertFalse(self.window.inspector.isVisible())
            self.assertFalse(self.window.frame_list.isVisible())
            self.assertFalse(self.window.statusBar().isVisible())
            self.assertTrue(player.play.isVisible())
            self.assertTrue(player.back.isVisible())
            self.assertGreater(player.canvas.width(), inline_size.width())
            self.assertGreater(player.canvas.height(), inline_size.height())
            self.assertEqual(player.canvas.image, before)
            self.assertEqual(player.seek.value(), 1)
            self.assertEqual(player.fps.value(), 20)
            self.assertFalse(player.loop.isChecked())
            self.assertFalse(player.timer.isActive())
            player.back.click()
            APP.processEvents()
            self.assertIs(self.window.preview_stack.currentWidget(), player)
            self.assertTrue(self.window.header.isVisible())
            self.assertTrue(self.window.statusBar().isVisible())
            self.assertEqual(self.window.workspace_stack.count(), 1)
            self.assertEqual(self.window.preview_stack.count(), 2)
            self.assertEqual(session.frame_index, 0)

    def test_window_playback_escape_stop_and_active_playback(self):
        self.processed()
        self.window.animate()
        player = self.window.animation
        player.window_playback.click()
        self.assertTrue(player.timer.isActive())
        player.play.click()
        self.assertFalse(player.timer.isActive())
        player.play.click()
        self.assertTrue(player.timer.isActive())
        self.window.escape_preview()
        self.assertIs(self.window.preview_stack.currentWidget(), player)
        self.assertTrue(player.timer.isActive())
        player.window_playback.click()
        self.window.stop_animation()
        self.assertEqual(self.window.workspace_stack.currentIndex(), 0)
        self.assertEqual(self.window.preview_stack.currentIndex(), 0)
        self.assertFalse(player.timer.isActive())
        self.assertTrue(self.window.left.isVisible())
        self.assertTrue(self.window.right.isVisible())

    def test_window_playback_bilingual_controls_fit_after_resize(self):
        self.processed()
        for code in ("en_US", "zh_CN"):
            self.window.language.setCurrentIndex(self.window.language.findData(code))
            self.window.animate()
            player = self.window.animation
            player.window_playback.click()
            for width, height in ((1420, 780), (1000, 640)):
                self.window.resize(width, height)
                APP.processEvents()
                self.assertEqual(player.size(), self.window.centralWidget().size())
                for control in (player.play, player.back, player.window_playback, player.seek):
                    self.assertTrue(control.isVisible())
                    self.assertTrue(player.rect().contains(control.mapTo(player, control.rect().bottomRight())))
            self.window.stop_animation()

    def test_scrollbar_and_fixed_actions_at_125_percent(self):
        self.open()
        for code in ("en_US", "zh_CN"):
            self.window.language.setCurrentIndex(self.window.language.findData(code))
            self.check_layout()
        self.window.change_stage("repair")
        self.settle()
        self.check_layout()

    def check_layout(self):
        self.window.editor.advanced_toggle.setChecked(True)
        for material in (False, True):
            apply_theme(APP, material)
            for width in (1420, 1100, 1000):
                self.window.resize(width, 780)
                APP.processEvents()
                scroll = self.window.scroll
                bar = scroll.verticalScrollBar()
                self.assertTrue(bar.isVisible())
                self.assertTrue(scroll.rect().contains(bar.mapTo(scroll, bar.rect().bottomRight())))
                self.assertLessEqual(scroll.widget().width(), scroll.viewport().width())
                bar.setValue(bar.maximum())
                APP.processEvents()
                for widget in (self.window.process_actions, self.window.trim_button, self.window.align_button, self.window.export_button):
                    self.assertTrue(widget.isVisible())
                    self.assertTrue(self.window.rect().contains(widget.mapTo(self.window, widget.rect().bottomRight())))
                self.assertLess(self.window.columns.sizes()[0], 190)

    def test_locale_switch_preserves_project_and_frame(self):
        session = self.open()
        self.window.frame_list.setCurrentRow(1)
        self.settle()
        self.window.language.setCurrentIndex(self.window.language.findData("zh_CN"))
        self.settle()
        self.assertEqual(session.frame_index, 1)
        self.assertEqual(self.window.pages.currentIndex(), 1)
        self.assertEqual(self.window.trim_button.text(), "统一裁切")

    def test_close_is_deferred_while_worker_is_active(self):
        self.window.start_job("test", lambda: time.sleep(.1))
        self.assertFalse(self.window.close())
        self.assertTrue(self.window.isVisible())
        self.settle()
        self.assertTrue(self.window.close())

    def test_video_creation_and_range_tool_real_files(self):
        video = self.root / "clip.avi"
        writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"MJPG"), 10, (32, 32))
        self.assertTrue(writer.isOpened())
        try:
            for index in range(10):
                pixels = np.full((32, 32, 3), (0, 255, 0), dtype=np.uint8)
                pixels[8:24, 8:24] = (0, 0, 150 + index * 10)
                writer.write(pixels)
        finally:
            writer.release()
        request = dict(source=video, name="Video", target_mode="green", custom_color="#00FF00", frame_interval=1)
        with patch("app.qt_ui.window.CreateDialog") as dialog:
            dialog.return_value.exec.return_value = QDialog.DialogCode.Accepted
            dialog.return_value.request = request
            self.window.create_project("video")
        self.settle()
        self.assertEqual(len(self.window.session.frames), 10)
        self.assertEqual(self.window.session.project["project_type"], "video")
        self.assertEqual(self.window.export_button.text(), "Export PNG Frame Sequence")
        dialog = ToolDialog(self.window, "video")
        dialog.source.setText(str(video))
        dialog.output.setText(str(self.root / "range_frames"))
        dialog.fields["start"].setValue(.2)
        dialog.fields["end"].setValue(.6)
        dialog.accept()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        with patch("app.qt_ui.window.ToolDialog", return_value=dialog), patch.object(dialog, "exec", return_value=QDialog.DialogCode.Accepted), patch.object(self.window, "open_output") as opened:
            self.window.run_tool("video")
            self.settle()
            opened.assert_called_once_with(self.root / "range_frames")
        self.assertEqual(len(list((self.root / "range_frames").glob("*.png"))), 4)


if __name__ == "__main__":
    unittest.main()
