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

from app.color_key_processor import process_image
from app.pipeline import make_stage, process_pipeline_image, run_pipeline, stage_signature
from app.ui_main import GameAssetKeyerApp
from app.compute_backend import current_backend
from app.color_key_processor import PROCESSOR_CACHE_VERSION


def sample(color=(20, 140, 30)):
    pixels = np.zeros((20, 20, 4), dtype=np.uint8)
    pixels[2:18, 2:18, :3] = color
    pixels[2:18, 2:18, 3] = 255
    pixels[1, 5:15, :3] = color
    pixels[1, 5:15, 3] = np.arange(1, 11) * 20
    return Image.fromarray(pixels)


class EdgeColorTests(unittest.TestCase):
    def params(self, **kwargs):
        return {"operation": "despill", "target_mode": "green", "despill_strength": 1,
                "despill_width": 2, **kwargs}

    def test_alpha_and_thin_hair_are_exactly_preserved_despite_key_settings(self):
        src = np.array(sample())
        src[0, 0] = (4, 250, 8, 0)
        out = np.array(process_image(Image.fromarray(src), self.params(edge_erode=8, feather_radius=8, output_alpha=0)))
        np.testing.assert_array_equal(src[..., 3], out[..., 3])
        np.testing.assert_array_equal(src[src[..., 3] == 0], out[src[..., 3] == 0])
        self.assertLess(out[1, 7, 1], src[1, 7, 1])

    def test_opaque_interior_and_unrelated_colors_are_unchanged(self):
        src = np.array(sample())
        src[8, 2, :3] = (160, 80, 40)
        out = np.array(process_image(Image.fromarray(src), self.params()))
        np.testing.assert_array_equal(out[7:13, 7:13], src[7:13, 7:13])
        np.testing.assert_array_equal(out[8, 2], src[8, 2])
        self.assertLess(out[8, 17, 1], src[8, 17, 1])

    def test_zero_strength_is_exact_noop(self):
        src = sample()
        self.assertEqual(src.tobytes(), process_image(src, self.params(despill_strength=0)).tobytes())

    def test_legacy_key_stage_signature_is_unchanged(self):
        stage = make_stage({'target_mode': 'green'})
        self.assertNotIn('operation', stage['params'])
        self.assertFalse(any(k.startswith('despill_') for k in stage['params']))
        payload = {'processor_cache_version': PROCESSOR_CACHE_VERSION,
                   'compute_backend': current_backend(), 'enabled': True,
                   'params': stage['params'], 'frame_params': {}}
        legacy = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()
        self.assertEqual(legacy, stage_signature(stage))

    def test_custom_blue_and_magenta(self):
        for color, target, channels in [((20, 25, 180), '#0000FF', [2]), ((180, 25, 180), '#FF00FF', [0, 2]), ((180, 180, 25), '#FFFF00', [0, 1])]:
            with self.subTest(target=target):
                out = np.array(process_image(sample(color), self.params(target_mode='custom', custom_color=target)))
                for channel in channels:
                    self.assertLess(out[8, 2, channel], color[channel])

    def test_neutral_target_reports_unsupported_and_transparent_input_is_safe(self):
        with self.assertRaises(ValueError):
            process_image(sample(), self.params(target_mode='white'))
        src = Image.new('RGBA', (2, 2), (0, 255, 0, 0))
        self.assertEqual(src.tobytes(), process_image(src, self.params()).tobytes())

    def test_pipeline_persistence_cache_and_disk_results(self):
        stage = make_stage(self.params())
        signature = stage_signature(stage)
        stage['params']['despill_strength'] = 0.5
        self.assertNotEqual(signature, stage_signature(stage))
        stage = json.loads(json.dumps(stage))
        self.assertEqual(stage['params']['operation'], 'despill')
        source = sample()
        expected = process_pipeline_image(source, [stage])
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
            root = Path(tmp)
            (root / '01_frames_raw').mkdir()
            source.save(root / '01_frames_raw/frame_000001.png')
            project = {'pipeline': {'stages': [stage]}}
            output = run_pipeline(project, root)
            with Image.open(output / 'frame_000001.png') as actual:
                self.assertEqual(actual.tobytes(), expected.tobytes())

    def test_ui_add_select_save_reload_and_old_stage_controls(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
            root = Path(tmp)
            (root / 'settings.json').write_text('{"language":"zh_CN"}', encoding='utf-8')
            src = root / 'source.png'
            sample().save(src)
            app = GameAssetKeyerApp(root)
            app.root.withdraw()
            try:
                project = app.pm.create_project(src, 'edge-ui', 1, 1, 'green')
                app.load_project(project['id'])
                app.add_despill_stage_ui()
                app.root.update_idletasks()
                self.assertEqual(app.operation_var.get(), 'despill')
                self.assertEqual(app.despill_editor.winfo_manager(), 'grid')
                self.assertEqual(app.advanced_button.winfo_manager(), '')
                app.custom_color_var.set('#0000FF')
                app.mode_var.set(app.mode_labels()['custom'])
                app.despill_strength_var.set(0.7)
                app.despill_width_var.set(4)
                app.save_selected_stage()
                app.load_project(project['id'])
                app.select_stage(1)
                self.assertEqual(app.collect_params()['despill_strength'], 0.7)
                self.assertEqual(app.collect_params()['custom_color'], '#0000FF')
                app.select_stage(0)
                self.assertEqual(app.advanced_button.winfo_manager(), 'grid')
                self.assertEqual(app.despill_editor.winfo_manager(), '')
                app.select_stage(1)
                app.add_stage_ui()
                self.assertEqual(app.operation_var.get(), 'key')
            finally:
                app.root.destroy()


if __name__ == '__main__':
    unittest.main()
