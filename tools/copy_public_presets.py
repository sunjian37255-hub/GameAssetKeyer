"""Release allowlist: never ship locally created user presets."""
# SPDX-License-Identifier: MPL-2.0
import shutil
import sys
from pathlib import Path

PUBLIC_PRESETS = (
    "aggressive.json", "black_fire_clean.json", "black_fire_soft.json", "black_fx.json",
    "conservative.json", "green_character.json", "magenta_sheet.json", "基础参数.json",
)

if __name__ == "__main__":
    root = Path(__file__).resolve().parent.parent
    destination = Path(sys.argv[1]) / "presets"
    destination.mkdir(parents=True, exist_ok=True)
    for name in PUBLIC_PRESETS:
        shutil.copy2(root / "presets" / name, destination / name)
