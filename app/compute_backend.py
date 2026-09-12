from __future__ import annotations

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0

import json
import sys
from pathlib import Path
from typing import Any

import cv2
import numpy as np

CPU = "cpu"
GPU = "gpu"
SUPPORTED_BACKENDS = (CPU, GPU)

_current_backend = CPU


def is_frozen_build() -> bool:
    return bool(getattr(sys, "frozen", False))


def gpu_available() -> bool:
    """Return whether OpenCV can execute UMat operations through OpenCL."""
    if is_frozen_build() or not cv2.ocl.haveOpenCL():
        return False
    previous = bool(cv2.ocl.useOpenCL())
    try:
        cv2.ocl.setUseOpenCL(True)
        probe = cv2.add(cv2.UMat(np.ones((2, 2), dtype=np.uint8)), 1)
        probe.get()
        device = cv2.ocl.Device_getDefault()
        return bool(cv2.ocl.useOpenCL()) and bool(device.type() & cv2.ocl.DEVICE_TYPE_GPU)
    except (AttributeError, cv2.error):
        return False
    finally:
        cv2.ocl.setUseOpenCL(previous)


def configure_backend(requested: str) -> str:
    """Select the process backend; frozen releases are always CPU-only."""
    global _current_backend
    selected = str(requested or CPU).lower()
    if is_frozen_build() or selected != GPU or not gpu_available():
        selected = CPU
        cv2.ocl.setUseOpenCL(False)
    else:
        cv2.ocl.setUseOpenCL(True)
    _current_backend = selected
    return selected


def current_backend() -> str:
    return _current_backend


def _read_settings(settings_path: Path) -> dict[str, Any]:
    try:
        value = json.loads(settings_path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def initialize_backend(app_root: Path) -> str:
    settings = _read_settings(Path(app_root) / "settings.json")
    requested = str(settings.get("compute_backend", CPU))
    return configure_backend(requested)


def save_backend_preference(app_root: Path, backend: str) -> None:
    if is_frozen_build():
        return
    settings_path = Path(app_root) / "settings.json"
    settings = _read_settings(settings_path)
    settings["compute_backend"] = GPU if backend == GPU else CPU
    settings_path.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")


def opencl_device_name() -> str:
    if not gpu_available():
        return ""
    try:
        return str(cv2.ocl.Device_getDefault().name())
    except (AttributeError, cv2.error):
        return "OpenCL"


def cvt_color(source: np.ndarray, code: int) -> np.ndarray:
    if _current_backend == GPU:
        return cv2.cvtColor(cv2.UMat(source), code).get()
    return cv2.cvtColor(source, code)


def erode(source: np.ndarray, kernel: np.ndarray, *, iterations: int = 1) -> np.ndarray:
    if _current_backend == GPU:
        return cv2.erode(cv2.UMat(source), kernel, iterations=iterations).get()
    return cv2.erode(source, kernel, iterations=iterations)
