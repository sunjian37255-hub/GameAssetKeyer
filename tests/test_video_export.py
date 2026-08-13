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
from app.final_result import resolve_final_result_source, resolve_pipeline_result_source, resolve_pre_alignment_source
from app.frame_sequence_exporter import export_png_frame_sequence
from app.pipeline import ensure_pipeline, run_pipeline, update_stage
from app.project_manager import ProjectManager
from app.sheet_exporter import export_sheet
from app.trim_utils import trim_frames


def make_sheet(path: Path, frame_count: int) -> None:
    pixels = np.zeros((12, 12 * frame_count, 4), dtype=np.uint8)
    pixels[..., 3] = 255
    for index in range(frame_count):
        left = index * 12
        offset = index % 3
        pixels[2 + offset : 8 + offset, left + 3 : left + 9, :3] = (40 + index, 120, 230)
    Image.fromarray(pixels, "RGBA").save(path)


class VideoExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.root = Path(self.temp.name)
        source = self.root / "video-frames.png"
        make_sheet(source, 10)
        self.manager = ProjectManager(self.root)
        self.project = self.manager.create_project(source, "video-export", 1, 10, "black")
        self.project["project_type"] = "video"
        self.project["source_type"] = "video"
        self.project_path = self.manager.project_path(self.project["id"])
        run_pipeline(self.project, self.project_path)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def export_current(self):
        source = resolve_final_result_source(self.project, self.project_path)
        self.assertIsNotNone(source)
        metadata = export_png_frame_sequence(source, self.project_path / "exports" / "final_frames")
        return source, metadata

    def assert_rgba_sequence(self, count: int) -> None:
        output = self.project_path / "exports" / "final_frames"
        frames = sorted(output.glob("frame_*.png"))
        self.assertEqual([path.name for path in frames], [f"frame_{index:06d}.png" for index in range(1, count + 1)])
        for path in frames:
            with Image.open(path) as image:
                self.assertEqual(image.mode, "RGBA")

    def test_video_pipeline_exports_exact_png_sequence_without_sheet(self) -> None:
        source, metadata = self.export_current()
        self.assertEqual(source.kind, "pipeline")
        self.assertEqual(metadata["frame_count"], 10)
        self.assert_rgba_sequence(10)
        self.assertFalse((self.project_path / "exports" / "sheet_transparent.png").exists())

    def test_video_trim_exports_trimmed_frames(self) -> None:
        pipeline = resolve_pipeline_result_source(self.project, self.project_path)
        self.project["trim"] = trim_frames(
            pipeline.directory,
            self.project_path / "04_trimmed",
            threshold=8,
            padding=0,
            source_signature=pipeline.signature,
        )
        source, metadata = self.export_current()
        self.assertEqual(source.kind, "trim")
        self.assertEqual(metadata["source_kind"], "trim")
        with Image.open(source.frame_path(source.frame_names[0])) as expected, Image.open(
            self.project_path / "exports" / "final_frames" / "frame_000001.png"
        ) as actual:
            np.testing.assert_array_equal(np.asarray(actual.convert("RGBA")), np.asarray(expected.convert("RGBA")))

    def test_video_trim_and_alignment_exports_aligned_frames(self) -> None:
        pipeline = resolve_pipeline_result_source(self.project, self.project_path)
        self.project["trim"] = trim_frames(
            pipeline.directory,
            self.project_path / "04_trimmed",
            threshold=8,
            padding=0,
            source_signature=pipeline.signature,
        )
        pre_align = resolve_pre_alignment_source(self.project, self.project_path)
        self.project["align"] = align_frames(
            pre_align.directory,
            self.project_path / "05_aligned",
            mode="center",
            source_signature=pre_align.signature,
        )
        source, metadata = self.export_current()
        self.assertEqual(source.kind, "align")
        self.assertEqual(metadata["source_kind"], "align")

    def test_pipeline_change_rejects_stale_video_alignment(self) -> None:
        pipeline = resolve_pipeline_result_source(self.project, self.project_path)
        self.project["align"] = align_frames(
            pipeline.directory,
            self.project_path / "05_aligned",
            mode="center",
            source_signature=pipeline.signature,
        )
        params = ensure_pipeline(self.project)["stages"][0]["params"].copy()
        params["background_threshold"] = 0.2
        update_stage(self.project, 0, params)
        run_pipeline(self.project, self.project_path)

        source, metadata = self.export_current()
        self.assertEqual(source.kind, "pipeline")
        self.assertEqual(metadata["source_kind"], "pipeline")

    def test_shorter_reexport_removes_historical_frames(self) -> None:
        self.export_current()
        raw_dir = self.project_path / "01_frames_raw"
        for index in range(7, 11):
            (raw_dir / f"frame_{index:06d}.png").unlink()
        self.project["frame_count"] = 6
        params = ensure_pipeline(self.project)["stages"][0]["params"].copy()
        params["foreground_threshold"] = 0.1
        update_stage(self.project, 0, params)
        run_pipeline(self.project, self.project_path)

        _source, metadata = self.export_current()
        self.assertEqual(metadata["frame_count"], 6)
        self.assert_rgba_sequence(6)
        self.assertFalse((self.project_path / "exports" / "final_frames" / "frame_000007.png").exists())

    def test_sprite_sheet_and_single_png_exports_remain_sheet_files(self) -> None:
        sheet_source = resolve_final_result_source(self.project, self.project_path)
        sheet = export_sheet(sheet_source.directory, self.project_path / "exports", 1, 10, "sheet.png")
        self.assertTrue(Path(sheet["sheet"]).is_file())

        single_source_path = self.root / "single.png"
        make_sheet(single_source_path, 1)
        single = self.manager.create_project(single_source_path, "single-export", 1, 1, "black")
        single_path = self.manager.project_path(single["id"])
        run_pipeline(single, single_path)
        final = resolve_final_result_source(single, single_path)
        exported = export_sheet(final.directory, single_path / "exports", 1, 1, "single.png")
        with Image.open(exported["sheet"]) as image:
            self.assertEqual(image.mode, "RGBA")
        self.assertEqual(exported["frame_count"], 1)


if __name__ == "__main__":
    unittest.main()
