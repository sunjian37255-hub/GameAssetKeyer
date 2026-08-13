from __future__ import annotations

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0

import argparse
import importlib.metadata
import shutil
import sys
from pathlib import Path


PACKAGES = ("numpy", "Pillow", "opencv-python-headless", "PyInstaller")


def copy_package_licenses(package: str, destination: Path) -> int:
    distribution = importlib.metadata.distribution(package)
    license_files = [
        item
        for item in distribution.files or ()
        if "licenses" in item.parts
        or item.name.lower().startswith(("license", "copying", "notice"))
    ]
    if not license_files:
        raise RuntimeError(f"No license files found for {package}")
    package_dir = destination / f"{package}-{distribution.version}"
    copied = 0
    for item in license_files:
        source = Path(distribution.locate_file(item))
        if not source.is_file():
            continue
        target = package_dir / Path(*item.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied += 1
    if copied == 0:
        raise RuntimeError(f"License files for {package} were not readable")
    return copied


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("release_dir", type=Path)
    args = parser.parse_args()
    release_dir = args.release_dir.resolve()
    destination = release_dir / "THIRD_PARTY_LICENSES"
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)

    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if not python_license.is_file():
        raise FileNotFoundError(str(python_license))
    shutil.copy2(python_license, destination / "CPython-3.14.3-LICENSE.txt")

    tk_license = Path(sys.base_prefix) / "tcl" / "tk8.6" / "license.terms"
    if not tk_license.is_file():
        raise FileNotFoundError(str(tk_license))
    shutil.copy2(tk_license, destination / "Tcl-Tk-8.6.15-license.terms")

    count = 2
    for package in PACKAGES:
        count += copy_package_licenses(package, destination)
    print(f"Copied {count} third-party license files to {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
