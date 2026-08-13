# -*- mode: python ; coding: utf-8 -*-
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

root = Path(SPEC).resolve().parent
hiddenimports = ["tkinter", "_tkinter"] + collect_submodules("tkinter")

a = Analysis(
    [str(root / "GameAssetKeyer.py")],
    pathex=[str(root)],
    binaries=[],
    datas=[(str(root / "locales"), "locales")],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "rembg",
        "onnxruntime",
        "pymatting",
        "skimage",
        "scipy",
        "torch",
        "tensorflow",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="GameAssetKeyer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch="x86_64",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="GameAssetKeyer",
)
