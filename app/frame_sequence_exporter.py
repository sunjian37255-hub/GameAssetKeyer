from __future__ import annotations

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0

import json
import shutil
from pathlib import Path
from typing import Any
from uuid import uuid4

from PIL import Image

from .final_result import FinalResultSource


def export_png_frame_sequence(source: FinalResultSource, output_dir: Path) -> dict[str, Any]:
    """Export one RGBA PNG per resolved final-result frame.

    A sibling staging directory is completed first, then swapped into place so
    a shorter re-export cannot leave stale frames from an older export.
    """
    if not source.frame_names:
        raise ValueError("No final-result frames found")

    output_dir = Path(output_dir)
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = output_dir.parent / f".{output_dir.name}.tmp-{uuid4().hex}"
    backup = output_dir.parent / f".{output_dir.name}.old-{uuid4().hex}"
    staging.mkdir()

    width = max(6, len(str(len(source.frame_names))))
    exported_names: list[str] = []
    try:
        for index, source_name in enumerate(source.frame_names, start=1):
            source_path = source.frame_path(source_name)
            if not source_path.is_file():
                raise FileNotFoundError(source_path)
            output_name = f"frame_{index:0{width}d}.png"
            with Image.open(source_path) as image:
                image.convert("RGBA").save(staging / output_name, format="PNG")
            exported_names.append(output_name)

        metadata = {
            "export_type": "png_frame_sequence",
            "directory": str(output_dir),
            "input_dir": str(source.directory),
            "source_kind": source.kind,
            "source_signature": source.signature,
            "frame_count": len(exported_names),
            "first_frame": exported_names[0],
            "last_frame": exported_names[-1],
        }
        (staging / "metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        if output_dir.exists():
            output_dir.replace(backup)
        try:
            staging.replace(output_dir)
        except Exception:
            if backup.exists() and not output_dir.exists():
                backup.replace(output_dir)
            raise
        if backup.exists():
            shutil.rmtree(backup)
        return metadata
    except Exception:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        raise
