from __future__ import annotations

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0

import cv2
import numpy as np
from PIL import Image

REPAIR_CACHE_VERSION = 2


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


def repair_edge_color(image: Image.Image, color: tuple[int, int, int], *,
                      strength: float = 0.8, width: int = 3,
                      tolerance: float = 0.35) -> Image.Image:
    """Repair target-colored fringe from nearby interior RGB, never alpha.

    Local mixture repair is followed by chromatic suppression of remaining
    matching spill, including thin structures without a reference. Neutral
    targets have no suppression fallback. This cannot distinguish genuine
    target-colored edges or rim lighting from contamination; inspect them.
    """
    rgba = np.array(image.convert("RGBA"), dtype=np.uint8)
    strength = float(np.clip(strength, 0, 1))
    width = int(np.clip(width, 1, 32))
    tolerance = float(np.clip(tolerance, 0.01, 1))
    alpha = rgba[..., 3]
    visible = alpha > 8
    if strength == 0 or not np.any(alpha):
        return Image.fromarray(rgba)

    rgb = rgba[..., :3].astype(np.float32)
    target = np.asarray(color, dtype=np.float32)
    # Near-transparent noise must not turn the whole canvas into an interior.
    distance = cv2.distanceTransform(np.pad(visible.astype(np.uint8), 1), cv2.DIST_L2, 5)[1:-1, 1:-1]
    # Reference depth/radius must not grow with the affected band: increasing
    # width should include more pixels, not remove references for existing ones.
    donors = (distance > 3) & (alpha >= max(16, int(alpha.max()) // 4))
    direction = target - target.mean()
    length = float(np.linalg.norm(direction))
    if length > 8:
        chroma = rgb - rgb.mean(axis=2, keepdims=True)
        norm = np.linalg.norm(chroma, axis=2)
        similarity = np.sum(chroma * (direction / length), axis=2) / np.maximum(norm, 1e-6)
        # Do not propagate a visibly contaminated reference into the edge.
        donors &= ~((similarity > 0.8) & (norm > 8))
    band = (alpha > 0) & (distance <= width)
    repaired = rgb.copy()
    if np.any(donors):
        nearby, labels = cv2.distanceTransformWithLabels(
            (~donors).astype(np.uint8), cv2.DIST_L2, 5, labelType=cv2.DIST_LABEL_PIXEL,
        )
        _, components = cv2.connectedComponents(visible.astype(np.uint8), connectivity=8)
        lookup = np.zeros(int(labels.max()) + 1, dtype=np.intp)
        lookup[labels[donors]] = np.flatnonzero(donors)
        # Fit only nearby visible edge pixels, not full-frame RGB tensors.
        y, x = np.nonzero(band & visible & (nearby <= 12))
        references = lookup[labels[y, x]]
        valid = ((components[y, x] == components.ravel()[references])
                 & (alpha[y, x].astype(np.int16) <= alpha.ravel()[references].astype(np.int16) + 16))
        y, x, references = y[valid], x[valid], references[valid]
        foreground = rgb.reshape(-1, 3)[references]
        background_delta = target - foreground
        delta = rgb[y, x] - foreground
        if length > 8:
            # Preserve brightness variation in folds/hair while fitting chroma.
            model = background_delta - background_delta.mean(axis=1, keepdims=True)
            observed = delta - delta.mean(axis=1, keepdims=True)
        else:
            model, observed = background_delta, delta
        denominator = np.sum(model * model, axis=1)
        mix = np.sum(observed * model, axis=1) / np.maximum(denominator, 1)
        residual = np.linalg.norm(observed - mix[:, None] * model, axis=1)
        allowance = 2 + tolerance * np.linalg.norm(observed, axis=1)
        confidence = np.clip(1 - residual / allowance, 0, 1)
        confidence *= (denominator >= 16 ** 2) & (mix > 0.03) & (mix <= 1.05)
        repaired[y, x] -= background_delta * (mix * confidence)[:, None]

    if length > 8:
        # A missing/rejected reference must not leave obvious chromatic spill.
        # Use only the pixel's own excess channels, never a different object's
        # RGB. Keep neutral targets conservative to protect shading/highlights.
        direction /= length
        positive = np.maximum(direction, 0)
        chroma = repaired - repaired.mean(axis=2, keepdims=True)
        projection = np.sum(chroma * direction, axis=2)
        similarity = projection / np.maximum(np.linalg.norm(chroma, axis=2), 1e-6)
        match = np.clip((similarity - (1 - tolerance)) / tolerance, 0, 1)
        amount = np.maximum(projection, 0) / float(np.dot(positive, positive))
        repaired -= (amount * match * band)[..., None] * positive

    # Apply strength once, not independently at each step of the hybrid repair.
    repaired = np.clip(repaired, 0, 255)
    rgba[..., :3] = np.rint(rgb + (repaired - rgb) * strength).astype(np.uint8)
    return Image.fromarray(rgba)
