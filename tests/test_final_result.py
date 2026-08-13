from __future__ import annotations

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0

import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from app.align_utils import align_frames
from app.final_result import (
    resolve_final_result_source,
    resolve_pipeline_result_source,
    resolve_pre_alignment_source,
)
from app.pipeline import ensure_pipeline, run_pipeline, run_pipeline_frame, set_frame_params, update_stage
from app.project_manager import ProjectManager
from app.sheet_exporter import export_sheet
from app.trim_utils import trim_frames


def make_source(path: Path) -> None:
    pixels = np.zeros((12, 24, 4), dtype=np.uint8)
    pixels[..., 3] = 255
    pixels[2:8, 3:9, :3] = (220, 60, 30)
    pixels[4:11, 15:22, :3] = (220, 60, 30)
    Image.fromarray(pixels, "RGBA").save(path)


class FinalResultTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.root = Path(self.temp.name)
        self.source = self.root / "source.png"
        make_source(self.source)
        self.manager = ProjectManager(self.root)
        self.project = self.manager.create_project(self.source, "final-result", 1, 2, "black")
        self.project_path = self.manager.project_path(self.project["id"])
        stage = ensure_pipeline(self.project)["stages"][0]
        stage["params"].update({"target_mode": "black", "feather_radius": 0, "enable_hole_punch": False})
        run_pipeline(self.project, self.project_path)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def assert_export_uses(self, source) -> None:
        meta = export_sheet(source.directory, self.project_path / "exports", 1, 2, "result.png")
        self.assertEqual(Path(meta["input_dir"]), source.directory)
        with Image.open(source.frame_path("frame_000001.png")) as frame:
            expected = np.asarray(frame.convert("RGBA")).copy()
        with Image.open(meta["sheet"]) as sheet:
            actual = np.asarray(sheet.convert("RGBA"))[:, : expected.shape[1]].copy()
        np.testing.assert_array_equal(actual, expected)

    def test_pipeline_only_preview_and_export_share_source(self) -> None:
        source = resolve_final_result_source(self.project, self.project_path)
        self.assertIsNotNone(source)
        self.assertEqual(source.kind, "pipeline")
        self.assert_export_uses(source)

    def test_legacy_complete_pipeline_without_generation_remains_usable(self) -> None:
        ensure_pipeline(self.project)["result_generation"] = ""
        source = resolve_final_result_source(self.project, self.project_path)
        self.assertIsNotNone(source)
        self.assertEqual(source.kind, "pipeline")
        self.assertTrue(source.signature.startswith("legacy-"))
        self.assert_export_uses(source)

    def test_trim_only_preview_and_export_share_trim_pixels(self) -> None:
        pipeline = resolve_pipeline_result_source(self.project, self.project_path)
        meta = trim_frames(pipeline.directory, self.project_path / "04_trimmed", 8, 0, pipeline.signature)
        self.project["trim"] = meta
        source = resolve_final_result_source(self.project, self.project_path)
        self.assertEqual(source.kind, "trim")
        with Image.open(source.frame_path("frame_000001.png")) as frame:
            self.assertLess(frame.width, 12)
        self.assert_export_uses(source)

    def test_align_only_preview_and_export_share_aligned_pixels(self) -> None:
        pipeline = resolve_pipeline_result_source(self.project, self.project_path)
        meta = align_frames(pipeline.directory, self.project_path / "05_aligned", "center", source_signature=pipeline.signature)
        self.project["align"] = meta
        source = resolve_final_result_source(self.project, self.project_path)
        self.assertEqual(source.kind, "align")
        self.assert_export_uses(source)

    def test_trim_and_align_preview_and_export_share_aligned_pixels(self) -> None:
        pipeline = resolve_pipeline_result_source(self.project, self.project_path)
        trim = trim_frames(pipeline.directory, self.project_path / "04_trimmed", 8, 0, pipeline.signature)
        self.project["trim"] = trim
        pre_align = resolve_pre_alignment_source(self.project, self.project_path)
        align = align_frames(pre_align.directory, self.project_path / "05_aligned", "center", source_signature=pre_align.signature)
        self.project["align"] = align
        source = resolve_final_result_source(self.project, self.project_path)
        self.assertEqual(source.kind, "align")
        with Image.open(source.frame_path("frame_000001.png")) as frame:
            self.assertLess(frame.width, 12)
        self.assert_export_uses(source)

    def test_pipeline_change_rejects_stale_trim_and_align_then_accepts_reprocessing(self) -> None:
        pipeline_v1 = resolve_pipeline_result_source(self.project, self.project_path)
        trim_v1 = trim_frames(pipeline_v1.directory, self.project_path / "04_trimmed", 8, 0, pipeline_v1.signature)
        self.project["trim"] = trim_v1
        pre_v1 = resolve_pre_alignment_source(self.project, self.project_path)
        align_v1 = align_frames(pre_v1.directory, self.project_path / "05_aligned", "center", source_signature=pre_v1.signature)
        self.project["align"] = align_v1

        params = ensure_pipeline(self.project)["stages"][0]["params"].copy()
        params["background_threshold"] = 0.1
        update_stage(self.project, 0, params)
        run_pipeline(self.project, self.project_path)
        pipeline_v2 = resolve_pipeline_result_source(self.project, self.project_path)
        final_v2 = resolve_final_result_source(self.project, self.project_path)
        self.assertNotEqual(pipeline_v1.signature, pipeline_v2.signature)
        self.assertEqual(final_v2.kind, "pipeline")
        self.assertNotEqual(final_v2.signature, align_v1["result_signature"])
        self.assert_export_uses(final_v2)

        trim_v2 = trim_frames(pipeline_v2.directory, self.project_path / "04_trimmed", 8, 0, pipeline_v2.signature)
        self.project["trim"] = trim_v2
        pre_v2 = resolve_pre_alignment_source(self.project, self.project_path)
        align_v2 = align_frames(pre_v2.directory, self.project_path / "05_aligned", "center", source_signature=pre_v2.signature)
        self.project["align"] = align_v2
        final_reprocessed = resolve_final_result_source(self.project, self.project_path)
        self.assertEqual(final_reprocessed.signature, align_v2["result_signature"])
        self.assert_export_uses(final_reprocessed)

    def test_current_frame_processing_invalidates_old_postprocess(self) -> None:
        pipeline = resolve_pipeline_result_source(self.project, self.project_path)
        trim = trim_frames(pipeline.directory, self.project_path / "04_trimmed", 8, 0, pipeline.signature)
        self.project["trim"] = trim
        pre_align = resolve_pre_alignment_source(self.project, self.project_path)
        align = align_frames(pre_align.directory, self.project_path / "05_aligned", "center", source_signature=pre_align.signature)
        self.project["align"] = align

        params = ensure_pipeline(self.project)["stages"][0]["params"].copy()
        params["background_threshold"] = 0.2
        set_frame_params(self.project, 0, "frame_000001.png", params)
        run_pipeline_frame(self.project, self.project_path, "frame_000001.png")
        current = resolve_final_result_source(self.project, self.project_path)
        self.assertEqual(current.kind, "pipeline")
        self.assertNotEqual(current.signature, align["result_signature"])

        run_pipeline_frame(self.project, self.project_path, "frame_000002.png")
        current = resolve_final_result_source(self.project, self.project_path)
        self.assertEqual(current.kind, "pipeline")
        self.assertNotEqual(current.signature, align["result_signature"])


if __name__ == "__main__":
    unittest.main()
