from __future__ import annotations

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0

import argparse
import importlib.metadata
import json
import platform
import struct
import sys
import tkinter
from pathlib import Path

LOCKED = {
    "numpy": "2.4.4",
    "opencv-python-headless": "4.13.0.92",
    "Pillow": "12.2.0",
    "PyInstaller": "6.21.0",
    "pyinstaller-hooks-contrib": "2026.6",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    errors: list[str] = []
    python_version = platform.python_version()
    if python_version != "3.14.3":
        errors.append(f"Python must be 3.14.3, found {python_version}")
    architecture = struct.calcsize("P") * 8
    if architecture != 64:
        errors.append(f"Python must be x64, found {architecture}-bit")
    installed: dict[str, str] = {}
    for package, expected in LOCKED.items():
        try:
            actual = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            actual = "NOT_INSTALLED"
        installed[package] = actual
        if actual != expected:
            errors.append(f"{package} must be {expected}, found {actual}")
    conflicting = []
    for package in ("opencv-python", "opencv-contrib-python", "opencv-contrib-python-headless"):
        try:
            conflicting.append(f"{package}=={importlib.metadata.version(package)}")
        except importlib.metadata.PackageNotFoundError:
            pass
    if conflicting:
        errors.append("Conflicting OpenCV wheels installed: " + ", ".join(conflicting))
    tcl = tkinter.Tcl()
    tcl_version = str(tcl.eval("info patchlevel"))
    if tcl_version != "8.6.15":
        errors.append(f"Tcl/Tk must be 8.6.15, found {tcl_version}")
    manifest = {
        "python": python_version,
        "architecture": f"x{architecture}",
        "tcl_tk": tcl_version,
        "packages": installed,
        "platform": platform.platform(),
        "executable": Path(sys.executable).name,
        "packaging": "PyInstaller windowed onedir",
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    if errors:
        for error in errors:
            print(f"[ERROR] {error}")
        return 1
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
