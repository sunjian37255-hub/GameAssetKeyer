from __future__ import annotations

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0

import json
import locale
import warnings
from pathlib import Path
from typing import Any

SUPPORTED_LOCALES = ("zh_CN", "en_US")
FALLBACK_LOCALE = "en_US"


def detect_system_locale() -> str:
    language = (locale.getlocale()[0] or "").replace("-", "_").lower()
    return "zh_CN" if language.startswith("zh") else FALLBACK_LOCALE


class I18n:
    def __init__(self, app_root: Path):
        self.app_root = Path(app_root)
        app_locales = self.app_root / "locales"
        bundled_locales = Path(__file__).resolve().parent.parent / "locales"
        self.locales_dir = app_locales if app_locales.is_dir() else bundled_locales
        self.settings_path = self.app_root / "settings.json"
        self._catalogs = {code: self._load_catalog(code) for code in SUPPORTED_LOCALES}
        self.locale = self._load_preference()

    def _load_catalog(self, code: str) -> dict[str, str]:
        path = self.locales_dir / f"{code}.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            warnings.warn(f"i18n catalog unavailable: {path}: {exc}", RuntimeWarning, stacklevel=2)
            return {}
        if not isinstance(data, dict):
            warnings.warn(f"i18n catalog must be an object: {path}", RuntimeWarning, stacklevel=2)
            return {}
        return {str(key): str(value) for key, value in data.items()}

    def _load_preference(self) -> str:
        try:
            settings = json.loads(self.settings_path.read_text(encoding="utf-8"))
            selected = settings.get("language") if isinstance(settings, dict) else None
            if selected in SUPPORTED_LOCALES:
                return selected
        except (OSError, json.JSONDecodeError):
            pass
        return detect_system_locale()

    def set_locale(self, code: str) -> None:
        if code not in SUPPORTED_LOCALES:
            code = FALLBACK_LOCALE
        self.locale = code
        settings: dict[str, Any] = {}
        try:
            existing = json.loads(self.settings_path.read_text(encoding="utf-8"))
            if isinstance(existing, dict):
                settings.update(existing)
        except (OSError, json.JSONDecodeError):
            pass
        settings["language"] = code
        self.settings_path.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")

    def tr(self, key: str, **values: object) -> str:
        text = self._catalogs.get(self.locale, {}).get(key)
        if text is None:
            text = self._catalogs.get(FALLBACK_LOCALE, {}).get(key)
            warnings.warn(f"missing i18n key: {self.locale}:{key}", RuntimeWarning, stacklevel=2)
        if text is None:
            return f"[{key}]"
        try:
            return text.format(**values)
        except (KeyError, ValueError) as exc:
            warnings.warn(f"invalid i18n format: {key}: {exc}", RuntimeWarning, stacklevel=2)
            return text
