from __future__ import annotations

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0

import json
import tempfile
import unittest
from pathlib import Path

from app.branding import APP_NAME, CHINESE_TAGLINE, ENGLISH_TAGLINE
from app.project_manager import ProjectManager
from app.ui_main import GameAssetKeyerApp


class BrandingTests(unittest.TestCase):
    def test_public_product_identity_and_build_names_are_consistent(self) -> None:
        root = Path.cwd()
        self.assertEqual(APP_NAME, "GameAssetKeyer")
        self.assertEqual(ENGLISH_TAGLINE, "Offline chroma key and background removal for 2D game assets.")
        self.assertEqual(CHINESE_TAGLINE, "面向 2D 游戏素材的离线抠色与背景移除工具")
        self.assertTrue((root / "GameAssetKeyer.py").is_file())
        self.assertFalse((root / ("Sprite" + "SheetCleaner.py")).exists())
        self.assertTrue((root / "GameAssetKeyer.spec").is_file())
        self.assertFalse((root / ("Sprite" + "SheetCleaner.spec")).exists())
        self.assertEqual((root / "VERSION").read_text(encoding="utf-8").strip(), "1.2.0")

        spec = (root / "GameAssetKeyer.spec").read_text(encoding="utf-8")
        build = (root / "build_release.bat").read_text(encoding="utf-8")
        verify = (root / "verify_release.ps1").read_text(encoding="utf-8")
        launcher = (root / "run.cmd").read_text(encoding="utf-8")
        self.assertIn('name="GameAssetKeyer"', spec)
        self.assertIn('console=False', spec)
        self.assertIn('collect_submodules("tkinter")', spec)
        self.assertIn("GameAssetKeyer-v%VERSION%-Windows-x64.zip", build)
        self.assertIn("GameAssetKeyer.exe", build)
        self.assertIn("GameAssetKeyer.exe", verify)
        self.assertIn("GameAssetKeyer.py", launcher)
        self.assertIn("GameAssetKeyer-v1.2.0-Windows-x64.zip", (root / "README.md").read_text(encoding="utf-8"))

        license_text = (root / "LICENSE").read_text(encoding="utf-8")
        source_text = (root / "SOURCE.txt").read_text(encoding="utf-8")
        contributing = (root / "CONTRIBUTING.md").read_text(encoding="utf-8")
        self.assertTrue(license_text.startswith("Mozilla Public License Version 2.0"))
        self.assertNotIn("MIT License\n", license_text)
        self.assertIn("SPDX-License-Identifier: MPL-2.0", (root / "GameAssetKeyer.py").read_text(encoding="utf-8"))
        self.assertIn("GameAssetKeyer/tree/v1.2.0", source_text)
        self.assertIn("Mozilla Public License 2.0 (MPL-2.0)", contributing)
        for required in ("LICENSE", "SOURCE.txt", "THIRD_PARTY_NOTICES.txt", "copy_third_party_licenses.py"):
            self.assertIn(required, build)
        self.assertIn("THIRD_PARTY_LICENSES", verify)

    def test_gui_title_and_bilingual_taglines(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_name:
            app_root = Path(temp_name)
            (app_root / "settings.json").write_text(json.dumps({"language": "zh_CN"}), encoding="utf-8")
            app = GameAssetKeyerApp(app_root)
            try:
                self.assertEqual(app.root.title(), APP_NAME)
                self.assertEqual(app.t("home.subtitle"), CHINESE_TAGLINE)
                app.i18n.set_locale("en_US")
                self.assertEqual(app.t("home.subtitle"), ENGLISH_TAGLINE)
            finally:
                app.root.destroy()

    def test_legacy_project_without_brand_metadata_still_loads(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_name:
            manager = ProjectManager(Path(temp_name))
            legacy = manager.project_path("legacy_project")
            legacy.mkdir(parents=True)
            (legacy / "project.json").write_text(
                json.dumps({"id": "legacy_project", "name": "Legacy", "target_mode": "green"}),
                encoding="utf-8",
            )
            loaded = manager.load_project("legacy_project")
            self.assertEqual(loaded["name"], "Legacy")
            self.assertEqual(loaded["pipeline"]["stages"][0]["params"]["target_mode"], "green")


if __name__ == "__main__":
    unittest.main()
