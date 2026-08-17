from __future__ import annotations

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0

import argparse
import sys
from pathlib import Path

from app.branding import APP_NAME
from app.ui_main import GameAssetKeyerApp


def get_app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def run_import_check() -> int:
    import tkinter as tk

    import cv2
    import numpy
    import PIL

    from app.color_key_processor import TARGETS
    from app.animation_preview import fps_interval_ms, resolve_animation_source
    from app.frame_sequence_composer import compose_sprite_sheet, natural_sort_key
    from app.i18n import I18n
    from app.pipeline import make_stage, process_pipeline_image
    from app.workers import PipelineWorker

    i18n = I18n(get_app_root())
    zh_keys = set(i18n._catalogs["zh_CN"])
    en_keys = set(i18n._catalogs["en_US"])
    if not zh_keys or zh_keys != en_keys:
        raise RuntimeError("Locale catalogs are missing or have different keys")
    if "white" not in TARGETS:
        raise RuntimeError("White key-color preset is unavailable")
    # Keep these imports and symbols live so frozen-build analysis includes the
    # normal runtime path exercised by source and release smoke checks.
    if (
        not callable(process_pipeline_image)
        or not callable(make_stage)
        or not callable(fps_interval_ms)
        or not callable(resolve_animation_source)
        or not callable(compose_sprite_sheet)
        or not callable(natural_sort_key)
        or not issubclass(PipelineWorker, object)
    ):
        raise RuntimeError("Core runtime imports failed")
    tcl = tk.Tcl()
    print(f"{APP_NAME} import check OK")
    print(f"app_root={get_app_root()}")
    print(f"Python={sys.version.split()[0]}")
    print(f"Tcl/Tk={tcl.eval('info patchlevel')}")
    print(f"Pillow={PIL.__version__}")
    print(f"NumPy={numpy.__version__}")
    print(f"OpenCV={cv2.__version__}")
    print(f"i18n_keys={len(zh_keys)}")
    return 0


def run_self_test(image_path: Path, output_path: Path | None = None) -> int:
    import json
    import time
    from app.color_key_processor import process_frame_file
    from app.project_manager import ProjectManager
    from app.sheet_exporter import export_sheet
    from app.trim_utils import trim_frames

    app_root = get_app_root()
    result: dict[str, object] = {
        "app_root": str(app_root),
        "image_path": str(image_path),
    }
    try:
        if not image_path.exists():
            raise FileNotFoundError(str(image_path))
        pm = ProjectManager(app_root)
        project = pm.create_project(image_path, "source_self_test", 3, 3, "black")
        project_path = pm.project_path(project["id"])
        frames = sorted((project_path / "01_frames_raw").glob("frame_*.png"))
        params = {
            "target_mode": "black",
            "custom_color": "#000000",
            "intensity": 3,
            "background_threshold": 0.40,
            "foreground_threshold": 0.76,
            "feather_radius": 1.5,
            "edge_erode": 0,
            "min_hole_size": 4,
            "alpha_gamma": 1.0,
            "saturation_protect": 0.35,
            "output_alpha": 1.0,
            "keep_sparks": True,
            "enable_hole_punch": True,
        }
        started = time.time()
        for frame in frames:
            process_frame_file(frame, project_path / "02_no_bg" / frame.name, project_path / "03_hole_punched" / frame.name, params)
        trim_meta = trim_frames(project_path / "03_hole_punched", project_path / "04_trimmed", 8, 0)
        export_meta = export_sheet(project_path / "04_trimmed", project_path / "exports", 3, 3, "sheet_transparent_self_test.png")
        project["last_params"] = params
        project["last_output_dir"] = "03_hole_punched"
        project["trim"] = trim_meta
        project["exports"] = export_meta
        pm.save_project(project["id"], project)
        result.update({
            "ok": True,
            "project_id": project["id"],
            "project_path": str(project_path),
            "frame_count": len(frames),
            "processed_output_count": len(list((project_path / "03_hole_punched").glob("frame_*.png"))),
            "sheet": export_meta.get("sheet"),
            "preview": export_meta.get("preview"),
            "seconds": round(time.time() - started, 2),
        })
        code = 0
    except Exception as exc:
        result.update({"ok": False, "error_type": type(exc).__name__, "error": str(exc)})
        code = 1
    if output_path is None:
        output_path = app_root / "self_test_result.json"
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return code


def main() -> int:
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--check", action="store_true", help="Import-check only, do not open GUI")
    parser.add_argument("--self-test-image", default="", help="Run deterministic smoke test with a 3x3 PNG image")
    parser.add_argument("--self-test-output", default="", help="Write self-test JSON to this path")
    args = parser.parse_args()
    if args.check:
        return run_import_check()
    if args.self_test_image:
        output = Path(args.self_test_output) if args.self_test_output else None
        return run_self_test(Path(args.self_test_image), output)
    app = GameAssetKeyerApp(get_app_root())
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
