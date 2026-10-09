from __future__ import annotations

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from app.color_key_processor import PROCESSOR_CACHE_VERSION, process_image
from app.compute_backend import current_backend
from app.edge_color import REPAIR_CACHE_VERSION
from app.final_result import resolve_final_result_source
from app.pipeline import make_stage, normalize_params, process_pipeline_image, run_pipeline, stage_signature, update_stage


def mixed_edge(target, *, halo=False):
    foreground = np.array((110, 70, 40))
    pixels = np.zeros((32, 32, 4), dtype=np.uint8)
    pixels[..., :3] = (7, 9, 11)
    if halo:
        pixels[..., 3] = 1
    pixels[5:27, 5:27] = (*foreground, 255)
    mixture = np.rint(foreground * 0.4 + np.array(target) * 0.6).astype(np.uint8)
    pixels[5:8, 5:27, :3] = mixture
    pixels[24:27, 5:27, :3] = mixture
    pixels[5:27, 5:8, :3] = mixture
    pixels[5:27, 24:27, :3] = mixture
    return pixels


class EdgeRepairTests(unittest.TestCase):
    def repair(self, pixels, target=(0, 255, 0), **overrides):
        params = dict(operation="despill", despill_method="repair", target_mode="custom",
                      custom_color="#%02X%02X%02X" % target, despill_width=3,
                      despill_strength=1, despill_tolerance=0.35)
        params.update(overrides)
        return np.array(process_image(Image.fromarray(pixels), params))

    def test_chromatic_and_neutral_mixed_edges_recover_local_color(self):
        for target in [(0, 255, 0), (0, 0, 255), (255, 0, 255), (0, 0, 0),
                       (255, 255, 255), (180, 180, 180), (80, 150, 80)]:
            with self.subTest(target=target):
                src = mixed_edge(target)
                out = self.repair(src, target)
                for column in (5, 6, 7):
                    np.testing.assert_allclose(out[16, column, :3], (110, 70, 40), atol=2)
                np.testing.assert_array_equal(out[..., 3], src[..., 3])
                np.testing.assert_array_equal(out[src[..., 3] == 0], src[src[..., 3] == 0])
                np.testing.assert_array_equal(out[8:24, 8:24], src[8:24, 8:24])

    def test_faint_alpha_halo_does_not_hide_actual_object_boundary(self):
        src = mixed_edge((0, 255, 0), halo=True)
        out = self.repair(src)
        np.testing.assert_allclose(out[16, 5, :3], (110, 70, 40), atol=2)
        np.testing.assert_array_equal(out[..., 3], src[..., 3])
        np.testing.assert_array_equal(out[src[..., 3] == 1], src[src[..., 3] == 1])

    def test_unrelated_edge_color_is_not_replaced(self):
        src = mixed_edge((0, 255, 0))
        src[16, 5, :3] = (220, 30, 50)
        out = self.repair(src)
        np.testing.assert_array_equal(out[16, 5], src[16, 5])

    def test_strength_is_gradual_and_zero_is_noop(self):
        src = mixed_edge((0, 255, 0))
        np.testing.assert_array_equal(self.repair(src, despill_strength=0), src)
        half = self.repair(src, despill_strength=0.5)
        expected = (src[16, 5, :3].astype(float) + (110, 70, 40)) / 2
        np.testing.assert_allclose(half[16, 5, :3], expected, atol=2)

    def test_selected_rgb_not_just_hue_changes_result(self):
        src = mixed_edge((80, 150, 80))
        sampled = self.repair(src, (80, 150, 80))
        saturated = self.repair(src, (0, 255, 0))
        self.assertFalse(np.array_equal(sampled, saturated))

    def test_no_reference_neutral_targets_preserve_thin_input(self):
        for shape, alpha in [((1, 1), 255), ((2, 20), 128), ((20, 20), 0)]:
            src = np.full((*shape, 4), (30, 150, 30, alpha), dtype=np.uint8)
            for target in [(0, 0, 0), (255, 255, 255), (128, 128, 128)]:
                np.testing.assert_array_equal(self.repair(src, target), src)

    def test_chromatic_thin_input_without_reference_suppresses_spill_not_alpha(self):
        for target, tint, expected in [((0,255,0), (30,150,30), (30,30,30)),
                                       ((0,0,255), (30,30,150), (30,30,30)),
                                       ((255,0,255), (150,30,150), (30,30,30))]:
            src = np.full((2, 20, 4), (*tint, 128), dtype=np.uint8)
            out = self.repair(src, target)
            np.testing.assert_array_equal(out[..., 3], src[..., 3])
            np.testing.assert_allclose(out[0, 0, :3], expected, atol=1)
            src[..., 3] = 0
            np.testing.assert_array_equal(self.repair(src, target), src)

    def test_disconnected_thin_object_does_not_borrow_another_objects_color(self):
        src = np.zeros((32, 32, 4), dtype=np.uint8)
        src[4:28, 4:20] = (110, 70, 40, 255)
        src[10:22, 21:23] = (44, 181, 16, 255)
        out = self.repair(src)
        isolated = src.copy()
        isolated[4:28, 4:20] = 0
        # The island may suppress its own green excess, but must not borrow RGB
        # from the neighboring object; its result is identical in isolation.
        np.testing.assert_array_equal(out[10:22, 21:23], self.repair(isolated)[10:22, 21:23])
        np.testing.assert_array_equal(out[..., 3], src[..., 3])
        self.assertLess(out[15, 21, 1], src[15, 21, 1])

    def test_widening_band_does_not_undo_existing_correction(self):
        for target in [(0,255,0), (255,255,255), (0,0,0)]:
            src = mixed_edge(target)
            narrow = self.repair(src, target)
            for width in (6, 12, 32):
                wide = self.repair(src, target, despill_width=width)
                changed = np.any(narrow[..., :3] != src[..., :3], axis=2)
                self.assertTrue(changed.any())
                np.testing.assert_array_equal(wide[changed], narrow[changed])

    def test_fallback_obeys_band_and_preserves_nonmatching_colors(self):
        src = np.full((30,30,4), (30,150,30,255), dtype=np.uint8)
        src[0,10:15,:3] = (180,80,30)
        out = self.repair(src, despill_width=3)
        np.testing.assert_array_equal(out[3:-3,3:-3], src[3:-3,3:-3])
        np.testing.assert_array_equal(out[0,10:15], src[0,10:15])
        self.assertLess(out[0,0,1], src[0,0,1])

    def test_fallback_strength_is_applied_once(self):
        src = np.full((2,20,4), (30,150,30,128), dtype=np.uint8)
        out = self.repair(src, despill_strength=0.5)
        np.testing.assert_allclose(out[0,0], (30,90,30,128), atol=1)

    def test_soft_foreground_has_local_references_and_keeps_coverage(self):
        src = mixed_edge((0, 255, 0))
        src[src[..., 3] > 0, 3] = 80
        out = self.repair(src)
        np.testing.assert_allclose(out[16, 5, :3], (110, 70, 40), atol=2)
        np.testing.assert_array_equal(out[..., 3], src[..., 3])

    def test_chromatic_repair_preserves_local_brightness_variation(self):
        src = mixed_edge((0, 255, 0))
        src[16, 5, :3] += 15
        out = self.repair(src)
        np.testing.assert_allclose(out[16, 5, :3], (125, 85, 55), atol=2)

    def test_opaque_interior_highlight_is_preserved_with_neutral_target(self):
        src = mixed_edge((255, 255, 255))
        src[14:18, 14:18, :3] = 255
        out = self.repair(src, (255, 255, 255))
        np.testing.assert_array_equal(out[14:18, 14:18], src[14:18, 14:18])

    def test_legacy_cache_stable_and_method_switch_invalidates_downstream(self):
        stage = make_stage({"operation": "despill", "target_mode": "green"})
        self.assertNotIn("despill_method", stage["params"])
        payload = dict(processor_cache_version=PROCESSOR_CACHE_VERSION,
                       compute_backend=current_backend(), enabled=True, params=stage["params"], frame_params={})
        expected = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self.assertEqual(stage_signature(stage), expected)
        project = {"pipeline": {"stages": [stage, make_stage()], "result_generation": "old"}}
        params = dict(stage["params"], despill_method="repair")
        update_stage(project, 0, params)
        self.assertNotEqual(stage_signature(project["pipeline"]["stages"][0]), expected)
        self.assertEqual(project["pipeline"]["result_generation"], "")
        self.assertTrue(all(s["status"] == "dirty" for s in project["pipeline"]["stages"]))

    def test_repair_preview_and_disk_pipeline_match_and_reuse_cache(self):
        source = Image.fromarray(mixed_edge((255, 255, 255)))
        stage = make_stage(dict(operation="despill", despill_method="repair", target_mode="white",
                                despill_strength=1, despill_width=3))
        preview = process_pipeline_image(source, [stage])
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            root = Path(folder)
            (root / "01_frames_raw").mkdir()
            source.save(root / "01_frames_raw/frame_000001.png")
            project = {"pipeline": {"stages": [stage]}}
            output = run_pipeline(project, root)
            frame = output / "frame_000001.png"
            with Image.open(frame) as result:
                self.assertEqual(preview.tobytes(), result.tobytes())
            stamp = frame.stat().st_mtime_ns
            run_pipeline(project, root)
            self.assertEqual(frame.stat().st_mtime_ns, stamp)

    def test_previous_repair_cache_is_rejected_and_rebuilt(self):
        params = dict(operation="despill", despill_method="repair", target_mode="green")
        stage = make_stage(params)
        old_params = dict(stage["params"])
        old_params.pop("despill_revision")
        old_payload = dict(processor_cache_version=PROCESSOR_CACHE_VERSION,
                           compute_backend=current_backend(), enabled=True, params=old_params, frame_params={})
        old_signature = hashlib.sha256(json.dumps(old_payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self.assertNotEqual(stage_signature(stage), old_signature)
        self.assertEqual(normalize_params(dict(params, despill_revision=-1))["despill_revision"], REPAIR_CACHE_VERSION)
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            root = Path(folder)
            (root / "01_frames_raw").mkdir()
            Image.fromarray(mixed_edge((0,255,0))).save(root / "01_frames_raw/frame_000001.png")
            project = {"pipeline": {"stages": [stage]}}
            run_pipeline(project, root)
            self.assertIsNotNone(resolve_final_result_source(project, root))
            project["pipeline"]["stages"][0]["cache_signature"] = old_signature
            self.assertIsNone(resolve_final_result_source(project, root))
            run_pipeline(project, root)
            self.assertIsNotNone(resolve_final_result_source(project, root))
