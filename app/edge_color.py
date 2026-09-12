from __future__ import annotations

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0

import cv2
import numpy as np
from PIL import Image


def remove_edge_color(image: Image.Image, color: tuple[int, int, int], *,
                      strength: float = 0.8, width: int = 3,
                      tolerance: float = 0.35) -> Image.Image:
    """Suppress matching chroma without changing alpha or transparent RGB.

    Only the target's excess channels are reduced; complementary colors and
    opaque interiors outside the requested band are left untouched.
    """
    rgba = np.array(image.convert("RGBA"), dtype=np.uint8)
    strength = float(np.clip(strength, 0, 1))
    width = int(np.clip(width, 1, 32))
    tolerance = float(np.clip(tolerance, 0.01, 1))
    if strength == 0 or not np.any(rgba[..., 3]):
        return Image.fromarray(rgba)
    target = np.asarray(color, dtype=np.float32)
    direction = target - target.mean()
    length = float(np.linalg.norm(direction))
    if length < 1:
        raise ValueError("去色边请选择绿色、蓝色、洋红等彩色目标，不支持黑白灰。")
    direction /= length
    positive = np.maximum(direction, 0)

    # Pad so an opaque object touching the canvas still has a well-defined edge.
    occupied = np.pad((rgba[..., 3] > 0).astype(np.uint8), 1)
    distance = cv2.distanceTransform(occupied, cv2.DIST_L2, 5)[1:-1, 1:-1]
    band = np.clip((width + 1 - distance) / width, 0, 1)
    band *= rgba[..., 3] > 0
    rgb = rgba[..., :3].astype(np.float32)
    chroma = rgb - rgb.mean(axis=2, keepdims=True)
    projection = np.sum(chroma * direction, axis=2)
    norm = np.linalg.norm(chroma, axis=2)
    similarity = projection / np.maximum(norm, 1e-6)
    match = np.clip((similarity - (1 - tolerance)) / tolerance, 0, 1)
    amount = np.maximum(projection, 0) / float(np.dot(positive, positive))
    correction = (amount * match * band * strength)[..., None] * positive
    rgba[..., :3] = np.rint(np.clip(rgb - correction, 0, 255)).astype(np.uint8)
    return Image.fromarray(rgba)
