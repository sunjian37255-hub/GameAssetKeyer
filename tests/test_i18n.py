from __future__ import annotations

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0

import json
import tempfile
import unittest
import warnings
from pathlib import Path

from app.i18n import I18n


class I18nTests(unittest.TestCase):
    def test_catalogs_have_identical_keys(self) -> None:
        root = Path(__file__).resolve().parent.parent
        zh = json.loads((root / "locales" / "zh_CN.json").read_text(encoding="utf-8"))
        en = json.loads((root / "locales" / "en_US.json").read_text(encoding="utf-8"))
        self.assertEqual(set(zh), set(en))
        self.assertIn("mode.white", zh)

    def test_fallback_missing_key_warning_and_persistence(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            root = Path(temp)
            i18n = I18n(root)
            i18n.set_locale("zh_CN")
            del i18n._catalogs["zh_CN"]["nav.home"]
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                self.assertEqual(i18n.tr("nav.home"), "Home")
                self.assertEqual(i18n.tr("does.not.exist"), "[does.not.exist]")
            self.assertGreaterEqual(len(caught), 2)
            self.assertEqual(I18n(root).locale, "zh_CN")


if __name__ == "__main__":
    unittest.main()
