"""Isolated native Qt startup check for the windowed release executable."""
# SPDX-License-Identifier: MPL-2.0
import json
from pathlib import Path
import tempfile

from PIL import Image
from PySide6.QtCore import qVersion
from PySide6.QtWidgets import QApplication

from ..compute_backend import current_backend
from .common import to_qimage
from .window import Window


def run_smoke(output):
    output = Path(output).resolve()
    result = {"ok": False}
    window = None
    try:
        app = QApplication.instance() or QApplication([])
        app.setStyle("Fusion")
        with tempfile.TemporaryDirectory(prefix="gak-smoke-", dir=output.parent) as directory:
            window = Window(Path(directory))
            # Exercise native window creation without interrupting the desktop.
            window.winId()
            app.processEvents()
            window.left.set_image(to_qimage(Image.new("RGBA", (32, 32), (255, 0, 0, 128))))
            if window.left.image.isNull() or not all(window.i18n._catalogs.values()):
                raise RuntimeError("Preview or locale catalogs failed to load")
            result.update(ok=True, qt=qVersion(), platform=app.platformName(),
                          backend=current_backend(), title=window.windowTitle(),
                          material=window.material, locales=len(window.i18n._catalogs))
            window.close()
            window = None
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if window is not None:
            window.close()
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return 0 if result["ok"] else 1
