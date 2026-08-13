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

from app.pipeline import (
    add_stage,
    delete_stage,
    duplicate_stage,
    ensure_pipeline,
    make_stage,
    move_stage,
    process_pipeline_image,
    run_pipeline,
    run_pipeline_frame,
    set_frame_params,
    clear_frame_params,
    set_stage_enabled,
    update_stage,
)


def sample_image() -> Image.Image:
    image = np.zeros((24, 24, 4), dtype=np.uint8)
    image[..., 3] = 255
    image[:8, :, :3] = (0, 0, 0)
    image[8:16, :, :3] = (0, 255, 0)
    image[16:, :, :3] = (255, 0, 255)
    image[4:20, 6:18, :3] = (220, 80, 40)
    return Image.fromarray(image, "RGBA")


class PipelineTests(unittest.TestCase):
    def test_one_two_three_stages_and_alpha_monotonicity(self) -> None:
        source = sample_image()
        stages = [
            make_stage({"target_mode": "black", "feather_radius": 0}),
            make_stage({"target_mode": "green", "feather_radius": 0}),
            make_stage({"target_mode": "magenta", "feather_radius": 0}),
        ]
        previous = np.array(source)[..., 3]
        for count in (1, 2, 3):
            result = process_pipeline_image(source, stages[:count])
            alpha = np.array(result)[..., 3]
            self.assertTrue(np.all(alpha <= previous))
            previous = alpha

    def test_custom_color_and_disabled_stage(self) -> None:
        source = sample_image()
        custom = make_stage({"target_mode": "custom", "custom_color": "#DC5028", "feather_radius": 0})
        disabled = make_stage({"target_mode": "green"}, enabled=False)
        direct = process_pipeline_image(source, [custom])
        with_disabled = process_pipeline_image(source, [disabled, custom])
        self.assertEqual(direct.tobytes(), with_disabled.tobytes())

    def test_white_preset_removes_white_and_preserves_dark_pixels(self) -> None:
        pixels = np.zeros((4, 4, 4), dtype=np.uint8)
        pixels[..., 3] = 255
        pixels[:2, :, :3] = (255, 255, 255)
        source = Image.fromarray(pixels, "RGBA")
        result = process_pipeline_image(
            source,
            [make_stage({"target_mode": "white", "feather_radius": 0, "enable_hole_punch": False})],
        )
        alpha = np.array(result)[..., 3]
        self.assertTrue(np.all(alpha[:2] == 0))
        self.assertTrue(np.all(alpha[2:] == 255))

    def test_edit_delete_duplicate_move_invalidation(self) -> None:
        project: dict = {"target_mode": "black"}
        pipeline = ensure_pipeline(project)
        add_stage(project, {"target_mode": "green"})
        add_stage(project, {"target_mode": "magenta"})
        for stage in pipeline["stages"]:
            stage["status"] = "complete"
            stage["cache_signature"] = "old"
        update_stage(project, 1, {"target_mode": "custom", "custom_color": "#123456"})
        self.assertEqual(pipeline["stages"][0]["status"], "complete")
        self.assertEqual([stage["status"] for stage in pipeline["stages"][1:]], ["dirty", "dirty"])
        duplicated = duplicate_stage(project, 0)
        self.assertEqual(duplicated, 1)
        set_stage_enabled(project, 1, False)
        self.assertEqual(pipeline["stages"][1]["status"], "disabled")
        destination = move_stage(project, 2, -1)
        self.assertEqual(destination, 1)
        before = len(pipeline["stages"])
        delete_stage(project, 1)
        self.assertEqual(len(pipeline["stages"]), before - 1)

    def test_old_project_compatibility(self) -> None:
        project = {"target_mode": "green", "last_params": {"target_mode": "custom", "custom_color": "#112233"}}
        pipeline = ensure_pipeline(project)
        self.assertEqual(len(pipeline["stages"]), 1)
        self.assertEqual(pipeline["stages"][0]["params"]["target_mode"], "custom")

    def test_disk_cache_and_disabled_chaining(self) -> None:
        project = {"target_mode": "black"}
        stages = ensure_pipeline(project)["stages"]
        stages[0]["params"].update({"target_mode": "black", "feather_radius": 0})
        add_stage(project, {"target_mode": "green", "feather_radius": 0})
        add_stage(project, {"target_mode": "magenta", "feather_radius": 0})
        set_stage_enabled(project, 1, False)
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            project_path = Path(temp)
            raw = project_path / "01_frames_raw"
            raw.mkdir()
            sample_image().save(raw / "frame_000001.png")
            output = run_pipeline(project, project_path)
            self.assertEqual(len(list(output.glob("frame_*.png"))), 1)
            self.assertEqual(stages[0]["status"], "complete")
            self.assertEqual(stages[1]["status"], "disabled")
            self.assertEqual(stages[2]["status"], "complete")

    def test_per_frame_params_and_individual_processing(self) -> None:
        project: dict = {"target_mode": "black"}
        stage = ensure_pipeline(project)["stages"][0]
        stage["params"].update({"target_mode": "black", "feather_radius": 0, "enable_hole_punch": False})
        set_frame_params(project, 0, "frame_000001.png", {"target_mode": "white", "feather_radius": 0, "enable_hole_punch": False})
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            project_path = Path(temp)
            raw = project_path / "01_frames_raw"
            raw.mkdir()
            white = Image.new("RGBA", (8, 8), (255, 255, 255, 255))
            black = Image.new("RGBA", (8, 8), (0, 0, 0, 255))
            white.save(raw / "frame_000001.png")
            black.save(raw / "frame_000002.png")

            first = run_pipeline_frame(project, project_path, "frame_000001.png")
            self.assertEqual(np.array(Image.open(first))[0, 0, 3], 0)
            self.assertEqual(stage["status"], "dirty")
            self.assertFalse(ensure_pipeline(project)["final_output_dir"])

            second = run_pipeline_frame(project, project_path, "frame_000002.png")
            self.assertEqual(np.array(Image.open(second))[0, 0, 3], 0)
            self.assertEqual(stage["status"], "complete")
            self.assertTrue(ensure_pipeline(project)["final_output_dir"])

            clear_frame_params(project, 0, "frame_000001.png")
            self.assertNotIn("frame_000001.png", stage["frame_params"])


if __name__ == "__main__":
    unittest.main()
