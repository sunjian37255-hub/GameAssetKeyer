from __future__ import annotations

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0

import argparse
import shutil
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("release_dir", type=Path)
    args = parser.parse_args()
    source = Path(sys.base_prefix) / "tcl"
    destination = args.release_dir / "_internal" / "tcl"
    if not source.is_dir():
        raise FileNotFoundError(f"Tcl runtime not found: {source}")
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)
    print(f"Copied Tcl/Tk runtime: {source.name} -> {destination.relative_to(args.release_dir)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
