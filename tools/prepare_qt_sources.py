"""Preserve official corresponding Qt sources and license notices for releases."""
# SPDX-License-Identifier: MPL-2.0
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import shutil
import tarfile
import urllib.request
import zipfile

VERSION = "6.12.0"
BASE = f"https://download.qt.io/official_releases/qt/6.12/{VERSION}/submodules/"
URLS = [BASE + f"{name}-everywhere-src-{VERSION}.tar.xz"
        for name in ("qtbase", "qtsvg", "qtimageformats")]
URLS.append(f"https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-{VERSION}-src/pyside-setup-everywhere-src-{VERSION}.tar.xz")
# Official download.qt.io SHA-256 values verified on 2026-10-10.
HASHES = {
    "qtbase": "a951bd163c7b80fc6b8c88d7668fb56abf91c152373e13c10666763238131307",
    "qtsvg": "e4ab39534ec97987b1b9b60ef7f4d3253d5912a69f8c713a01753174a4029331",
    "qtimageformats": "0943132b5db8de6b6a7f1d162682173e8763c7ed94e80fd39113292845f67762",
    "pyside": "099c1a597cf33c1b000e11cf68a0b82d216fb802bf81726efc720394f10c7751",
}


def download(url, directory):
    name = url.rsplit("/", 1)[-1]
    expected = HASHES[name.split("-", 1)[0]]
    target = directory / name
    if not target.exists():
        part = target.with_suffix(target.suffix + ".part")
        print(f"Downloading {name}", flush=True)
        with urllib.request.urlopen(url, timeout=60) as response, part.open("wb") as output:
            shutil.copyfileobj(response, output)
        part.rename(target)
    with target.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    if digest != expected:
        raise ValueError(f"Official SHA256 mismatch: {name}")
    print(f"Verified {name}", flush=True)
    return {"file": name, "url": url, "sha256": digest}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("cache", type=Path)
    parser.add_argument("--licenses", type=Path)
    parser.add_argument("--archive", type=Path)
    args = parser.parse_args()
    args.cache.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=4) as executor:
        records = list(executor.map(lambda url: download(url, args.cache), URLS))
    manifest = args.cache / "SOURCES.json"
    manifest.write_text(json.dumps(records, indent=2), encoding="utf-8")
    if args.licenses:
        for record in records:
            with tarfile.open(args.cache / record["file"]) as archive:
                for member in archive:
                    path = Path(member.name)
                    if not member.isfile() or path.is_absolute() or ".." in path.parts:
                        continue
                    if "LICENSES" in path.parts or path.name.lower().startswith(("license", "copying", "notice", "copyright", "qt_attribution")):
                        target = args.licenses / "Qt-sources" / path
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with archive.extractfile(member) as source, target.open("wb") as output:
                            shutil.copyfileobj(source, output)
    if args.archive:
        with zipfile.ZipFile(args.archive, "x", compression=zipfile.ZIP_STORED) as output:
            for record in records:
                output.write(args.cache / record["file"], record["file"])
            output.write(manifest, manifest.name)


if __name__ == "__main__":
    main()
