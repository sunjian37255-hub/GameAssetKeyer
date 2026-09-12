from __future__ import annotations

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image

from app.color_key_processor import DEFAULT_PARAMS, process_image
from app.compute_backend import CPU, GPU, configure_backend, current_backend, gpu_available, initialize_backend, save_backend_preference
from app.pipeline import make_stage, stage_signature


class ComputeBackendTests(unittest.TestCase):
    def tearDown(self) -> None:
        configure_backend(CPU)

    def test_frozen_build_forces_cpu(self) -> None:
        with patch("app.compute_backend.is_frozen_build", return_value=True):
            self.assertEqual(configure_backend(GPU), CPU)
            self.assertEqual(current_backend(), CPU)

    def test_source_preference_round_trip_preserves_other_settings(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            root = Path(temp)
            (root / "settings.json").write_text(json.dumps({"language": "zh_CN"}), encoding="utf-8")
            save_backend_preference(root, CPU)
            settings = json.loads((root / "settings.json").read_text(encoding="utf-8"))
            self.assertEqual(settings, {"language": "zh_CN", "compute_backend": CPU})
            self.assertEqual(initialize_backend(root), CPU)

    def test_backend_is_part_of_pipeline_cache_signature(self) -> None:
        stage = make_stage()
        configure_backend(CPU)
        cpu_signature = stage_signature(stage)
        if gpu_available():
            configure_backend(GPU)
            self.assertNotEqual(stage_signature(stage), cpu_signature)

    def test_opencl_path_preserves_processing_result(self) -> None:
        if not gpu_available():
            self.skipTest("OpenCL GPU is unavailable")
        pixels = np.zeros((32, 32, 4), dtype=np.uint8)
        pixels[..., :3] = (0, 255, 0)
        pixels[..., 3] = 255
        pixels[8:24, 8:24, :3] = (230, 40, 60)
        image = Image.fromarray(pixels, "RGBA")
        params = DEFAULT_PARAMS | {"target_mode": "green", "edge_erode": 2}
        configure_backend(CPU)
        cpu = np.asarray(process_image(image, params))
        self.assertEqual(configure_backend(GPU), GPU)
        gpu = np.asarray(process_image(image, params))
        np.testing.assert_allclose(gpu, cpu, atol=1)


if __name__ == "__main__":
    unittest.main()
