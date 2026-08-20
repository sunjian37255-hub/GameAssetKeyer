from __future__ import annotations

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0

import json
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from app.color_key_processor import process_image


BASE_PARAMS = {
    "background_threshold": 0.20,
    "foreground_threshold": 0.40,
    "feather_radius": 0.0,
    "edge_erode": 0,
    "min_hole_size": 0,
    "alpha_gamma": 1.0,
    "saturation_protect": 1.0,
    "output_alpha": 1.0,
    "keep_sparks": False,
    "enable_hole_punch": False,
}


def output_alpha(
    mode: str,
    colors: tuple[tuple[int, int, int], ...],
    intensity: int,
    *,
    custom_color: str = "#000000",
    thresholds: tuple[float, float] | None = None,
) -> np.ndarray:
    pixels = np.zeros((1, len(colors), 4), dtype=np.uint8)
    pixels[0, :, :3] = colors
    pixels[..., 3] = 255
    params = {
        **BASE_PARAMS,
        "target_mode": mode,
        "custom_color": custom_color,
        "intensity": intensity,
    }
    if thresholds is not None:
        params["background_threshold"], params["foreground_threshold"] = thresholds
    result = process_image(Image.fromarray(pixels, "RGBA"), params, apply_hole_punch=False)
    return np.array(result, dtype=np.uint8)[0, :, 3]


class DetectionStrengthTests(unittest.TestCase):
    def test_non_black_outputs_match_legacy_golden_fixture(self) -> None:
        fixture_path = Path(__file__).parent / "fixtures" / "legacy_detection" / "non_black_alpha.json"
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        thresholds = (fixture["background_threshold"], fixture["foreground_threshold"])

        for case_name, case in fixture["cases"].items():
            mode = "white" if case_name == "white" else case["legacy_mode"]
            colors = tuple(tuple(color) for color in case["colors"])
            for level_text, expected_alpha in case["expected_alpha"].items():
                with self.subTest(case=case_name, intensity=level_text):
                    actual = output_alpha(
                        mode,
                        colors,
                        int(level_text),
                        custom_color=case["custom_color"],
                        thresholds=thresholds,
                    )
                    self.assertEqual(actual.tolist(), expected_alpha)

    def test_detection_range_expands_monotonically_for_every_target_mode(self) -> None:
        cases = {
            "green": ((0, 255, 0), (20, 235, 20), (40, 215, 40), (60, 195, 60), (80, 175, 80)),
            "black": ((0, 0, 0), (32, 32, 32), (64, 64, 64), (96, 96, 96), (128, 128, 128)),
            "white": ((255, 255, 255), (235, 235, 235), (215, 215, 215), (195, 195, 195), (175, 175, 175)),
            "magenta": ((255, 0, 255), (235, 20, 235), (215, 40, 215), (195, 60, 195), (175, 80, 175)),
            "custom": ((128, 128, 128), (148, 148, 148), (168, 168, 168), (188, 188, 188), (208, 208, 208)),
        }
        for mode, colors in cases.items():
            with self.subTest(mode=mode):
                custom_color = "#808080" if mode == "custom" else "#000000"
                levels = [output_alpha(mode, colors, level, custom_color=custom_color) for level in range(1, 6)]
                for stricter, looser in zip(levels, levels[1:]):
                    self.assertTrue(np.all(looser <= stricter))
                self.assertTrue(np.any(levels[-1] < levels[0]))

    def test_black_uses_rgb_color_distance_at_the_threshold_boundary(self) -> None:
        distance = 64
        alpha = output_alpha(
            "black",
            ((distance - 1,) * 3, (distance,) * 3, (distance + 1,) * 3),
            3,
            thresholds=(distance / 255.0, (distance + 1) / 255.0),
        )
        self.assertEqual(alpha.tolist(), [0, 0, 255])

    def test_black_uses_rgb_distance_instead_of_max_channel_brightness(self) -> None:
        alpha = output_alpha(
            "black",
            ((64, 0, 0), (64, 64, 64)),
            3,
            thresholds=(0.10, 0.30),
        )
        self.assertLess(int(alpha[0]), int(alpha[1]))


if __name__ == "__main__":
    unittest.main()
