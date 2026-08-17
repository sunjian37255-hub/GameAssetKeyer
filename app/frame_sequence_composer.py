from __future__ import annotations

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0

"""Pure PNG-sequence-to-sprite-sheet composition helpers."""

import ctypes
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, NamedTuple

from PIL import Image


_DIGIT_RE = re.compile(r"(\d+)")
ALIGNMENTS = ("center", "bottom_center")


def natural_sort_key(value: str | Path) -> tuple[object, ...]:
    """Sort names by text and embedded numbers (frame_2 before frame_10)."""

    text = Path(value).name if isinstance(value, Path) else str(value)
    parts = _DIGIT_RE.split(text)
    return tuple((1, int(part)) if part.isdigit() else (0, part.casefold()) for part in parts)


def _is_hidden(path: Path) -> bool:
    if path.name.startswith("."):
        return True
    try:
        get_attributes = getattr(ctypes, "windll", None)
        kernel32 = getattr(get_attributes, "kernel32", None) if get_attributes is not None else None
        get_file_attributes = getattr(kernel32, "GetFileAttributesW", None) if kernel32 is not None else None
        if get_file_attributes is None:
            return False
        attributes = int(get_file_attributes(str(path)))
        return attributes != -1 and bool(attributes & 0x2)
    except (AttributeError, OSError, TypeError, ValueError):
        return False


def is_hidden_path(path: Path) -> bool:
    """Public visibility predicate shared by folder and multi-file input."""

    return _is_hidden(Path(path))


def list_png_files(directory: Path) -> list[Path]:
    """List only visible PNG files directly inside ``directory``."""

    directory = Path(directory)
    if not directory.is_dir():
        return []
    return sorted(
        (path for path in directory.iterdir() if path.is_file() and path.suffix.lower() == ".png" and not _is_hidden(path)),
        key=natural_sort_key,
    )


def _coerce_paths(source: Path | str | Iterable[Path | str]) -> list[Path]:
    if isinstance(source, (Path, str)):
        paths = list_png_files(Path(source))
    else:
        paths = [Path(path) for path in source]
        paths = [path for path in paths if path.suffix.lower() == ".png" and not _is_hidden(path)]
    return paths


@dataclass(frozen=True)
class FrameInfo:
    path: Path
    width: int
    height: int
    mode: str


def load_sequence_info(source: Path | str | Iterable[Path | str]) -> tuple[FrameInfo, ...]:
    """Read dimensions/modes without retaining decoded full-size frames."""

    if isinstance(source, FrameInfo):
        return (source,)
    if not isinstance(source, (Path, str)):
        possible_infos = tuple(source)
        if all(isinstance(item, FrameInfo) for item in possible_infos):
            return possible_infos
        source = possible_infos
    infos: list[FrameInfo] = []
    for path in _coerce_paths(source):
        try:
            with Image.open(path) as image:
                infos.append(FrameInfo(path, int(image.width), int(image.height), str(image.mode)))
        except (OSError, ValueError) as exc:
            raise ValueError(f"Could not read PNG frame: {path}: {exc}") from exc
    return tuple(infos)


class GridSize(NamedTuple):
    columns: int
    rows: int


class SequenceLayout(NamedTuple):
    frame_count: int
    columns: int
    rows: int
    cell_width: int
    cell_height: int
    output_width: int
    output_height: int


def validate_padding(padding: int | str) -> int:
    try:
        value = int(padding)
    except (TypeError, ValueError):
        raise ValueError("Padding must be an integer from 0 to 256") from None
    if not 0 <= value <= 256:
        raise ValueError("Padding must be an integer from 0 to 256")
    return value


def validate_alignment(alignment: str) -> str:
    normalized = str(alignment).strip().lower().replace(" ", "_")
    aliases = {"centre": "center", "bottomcentre": "bottom_center", "bottom_center": "bottom_center"}
    normalized = aliases.get(normalized, normalized)
    if normalized not in ALIGNMENTS:
        raise ValueError(f"Unsupported alignment: {alignment}")
    return normalized


def calculate_grid(frame_count: int, columns: int | None = None) -> GridSize:
    count = int(frame_count)
    if count < 1:
        raise ValueError("At least one PNG frame is required")
    if columns is None:
        columns = max(1, math.ceil(math.sqrt(count)))
    columns = int(columns)
    if columns < 1:
        raise ValueError("Columns must be greater than zero")
    return GridSize(columns, math.ceil(count / columns))


def calculate_cell_size(frame_info: Iterable[FrameInfo] | FrameInfo | Path | str, padding: int = 0) -> tuple[int, int]:
    infos = load_sequence_info(frame_info)
    if not infos:
        raise ValueError("At least one PNG frame is required")
    padding = validate_padding(padding)
    return max(info.width for info in infos) + padding * 2, max(info.height for info in infos) + padding * 2


def calculate_layout(
    source: Iterable[Path | str] | Path | str,
    columns: int | None = None,
    padding: int = 0,
) -> SequenceLayout:
    infos = load_sequence_info(source)
    if not infos:
        raise ValueError("At least one PNG frame is required")
    grid = calculate_grid(len(infos), columns)
    cell_width, cell_height = calculate_cell_size(infos, padding)
    return SequenceLayout(
        len(infos),
        grid.columns,
        grid.rows,
        cell_width,
        cell_height,
        grid.columns * cell_width,
        grid.rows * cell_height,
    )


def _compose_from_infos(
    infos: tuple[FrameInfo, ...],
    layout: SequenceLayout,
    alignment: str,
    *,
    scale: float = 1.0,
) -> Image.Image:
    if scale <= 0:
        raise ValueError("Scale must be positive")
    sheet_size = (max(1, round(layout.output_width * scale)), max(1, round(layout.output_height * scale)))
    sheet = Image.new("RGBA", sheet_size, (0, 0, 0, 0))
    # Layout dimensions include padding, so compute the max frame area from
    # the observed frame dimensions and use explicit padding in placement.
    padding_x = max(0, (layout.cell_width - max(info.width for info in infos)) // 2)
    padding_y = max(0, (layout.cell_height - max(info.height for info in infos)) // 2)
    max_width = max(info.width for info in infos)
    max_height = max(info.height for info in infos)
    for index, info in enumerate(infos):
        with Image.open(info.path) as source:
            image = source.convert("RGBA")
            if scale != 1.0:
                image = image.resize(
                    (max(1, round(info.width * scale)), max(1, round(info.height * scale))),
                    Image.Resampling.LANCZOS,
                )
            cell_x = (index % layout.columns) * layout.cell_width
            cell_y = (index // layout.columns) * layout.cell_height
            x = cell_x + padding_x + (max_width - info.width) // 2
            if alignment == "bottom_center":
                y = cell_y + padding_y + max_height - info.height
            else:
                y = cell_y + padding_y + (max_height - info.height) // 2
            destination = (round(x * scale), round(y * scale))
            sheet.paste(image, destination)
            image.close()
    return sheet


def compose_sprite_sheet(
    source: Iterable[Path | str] | Path | str,
    columns: int | None = None,
    alignment: str = "center",
    padding: int = 0,
) -> Image.Image:
    """Compose RGBA cells without scaling or changing source frame pixels."""

    infos = load_sequence_info(source)
    if not infos:
        raise ValueError("At least one PNG frame is required")
    layout = calculate_layout(infos, columns, padding)
    return _compose_from_infos(infos, layout, validate_alignment(alignment))


def render_sprite_sheet_thumbnail(
    source: Iterable[Path | str] | Path | str,
    columns: int | None = None,
    alignment: str = "center",
    padding: int = 0,
    max_size: int = 640,
) -> Image.Image:
    """Render a bounded preview by scaling each frame as it is read."""

    infos = load_sequence_info(source)
    if not infos:
        raise ValueError("At least one PNG frame is required")
    layout = calculate_layout(infos, columns, padding)
    max_size = max(1, int(max_size))
    scale = min(1.0, max_size / max(layout.output_width, layout.output_height))
    return _compose_from_infos(infos, layout, validate_alignment(alignment), scale=scale)


def export_sprite_sheet(
    source: Iterable[Path | str] | Path | str,
    output_path: Path | str,
    columns: int | None = None,
    alignment: str = "center",
    padding: int = 0,
) -> SequenceLayout:
    """Compose and save a PNG, returning the exact output layout."""

    output_path = Path(output_path)
    if output_path.suffix.lower() != ".png":
        raise ValueError("Output file must use the .png extension")
    source_items = list(source) if not isinstance(source, (Path, str)) else source
    image = compose_sprite_sheet(source_items, columns, alignment, padding)
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        image.save(output_path, format="PNG")
    finally:
        image.close()
    return calculate_layout(source_items, columns, padding)


# Explicit alias for callers that prefer the task's terminology.
compose_to_file = export_sprite_sheet
