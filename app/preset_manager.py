from __future__ import annotations

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0

import json
from pathlib import Path
from typing import Any

from .color_key_processor import DEFAULT_PARAMS


def load_preset(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    params = DEFAULT_PARAMS.copy()
    params.update({key: value for key, value in data.items() if key in DEFAULT_PARAMS})
    return params


def save_preset(path: Path, params: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(params, ensure_ascii=False, indent=2), encoding="utf-8")


def ensure_default_presets(presets_dir: Path) -> None:
    presets_dir.mkdir(parents=True, exist_ok=True)
    presets = {
        "green_character.json": {"target_mode": "green", "intensity": 3, "feather_radius": 1.5, "edge_erode": 1, "min_hole_size": 8},
        "black_fire_soft.json": {"target_mode": "black", "intensity": 5, "background_threshold": 0.04, "foreground_threshold": 0.36, "feather_radius": 2.0, "edge_erode": 0, "keep_sparks": True, "saturation_protect": 0.28},
        "black_fire_clean.json": {"target_mode": "black", "intensity": 3, "background_threshold": 0.04, "foreground_threshold": 0.22, "feather_radius": 1.2, "edge_erode": 0, "keep_sparks": True},
        "black_fx.json": {"target_mode": "black", "intensity": 4, "background_threshold": 0.05, "foreground_threshold": 0.30, "feather_radius": 1.5},
        "magenta_sheet.json": {"target_mode": "magenta", "intensity": 3, "feather_radius": 1.2, "edge_erode": 1, "min_hole_size": 6},
        "conservative.json": {"intensity": 2, "feather_radius": 2.0, "edge_erode": 0, "min_hole_size": 3, "keep_sparks": True},
        "aggressive.json": {"intensity": 5, "feather_radius": 0.8, "edge_erode": 1, "min_hole_size": 12, "keep_sparks": False},
    }
    for name, params in presets.items():
        path = presets_dir / name
        if not path.exists():
            merged = DEFAULT_PARAMS.copy()
            merged.update(params)
            save_preset(path, merged)
