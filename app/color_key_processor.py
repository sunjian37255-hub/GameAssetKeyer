from __future__ import annotations

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0

import math
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageFilter

TARGETS = {
    "green": (0, 255, 0),
    "black": (0, 0, 0),
    "white": (255, 255, 255),
    "magenta": (255, 0, 255),
}

PROCESSOR_CACHE_VERSION = 2

MODE_LABELS = {
    "green": ["\u6781\u4e25\u683c\u7eff / \u9c9c\u8273\u7eff", "\u4e25\u683c\u7eff", "\u6807\u51c6\u7eff", "\u5bbd\u677e\u7eff", "\u6781\u5bbd\u677e\u7eff / \u6697\u6c89\u7eff"],
    "black": ["\u6781\u4e25\u683c\u9ed1 / \u7eaf\u9ed1", "\u4e25\u683c\u9ed1", "\u6807\u51c6\u9ed1", "\u5bbd\u677e\u9ed1", "\u6781\u5bbd\u677e\u9ed1 / \u7070\u9ed1\u6b8b\u7559"],
    "white": ["\u6781\u4e25\u683c\u767d / \u7eaf\u767d", "\u4e25\u683c\u767d", "\u6807\u51c6\u767d", "\u5bbd\u677e\u767d", "\u6781\u5bbd\u677e\u767d / \u7070\u767d\u6b8b\u7559"],
    "magenta": ["\u6781\u4e25\u683c\u6d0b\u7ea2 / \u7eaf\u6d0b\u7ea2", "\u4e25\u683c\u6d0b\u7ea2", "\u6807\u51c6\u6d0b\u7ea2", "\u5bbd\u677e\u6d0b\u7ea2", "\u6781\u5bbd\u677e\u6d0b\u7ea2 / \u504f\u79fb\u6d0b\u7ea2"],
    "custom": ["\u6781\u4e25\u683c", "\u4e25\u683c", "\u6807\u51c6", "\u5bbd\u677e", "\u6781\u5bbd\u677e"],
}

DEFAULT_PARAMS: dict[str, Any] = {
    "target_mode": "black",
    "custom_color": "#000000",
    "intensity": 3,
    "background_threshold": 0.40,
    "foreground_threshold": 0.76,
    "feather_radius": 1.5,
    "edge_erode": 0,
    "min_hole_size": 4,
    "alpha_gamma": 1.0,
    "saturation_protect": 0.35,
    "output_alpha": 1.0,
    "keep_sparks": True,
    "enable_hole_punch": True,
}


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def parse_color(mode: str, custom_color: str = "#000000") -> tuple[int, int, int]:
    if mode in TARGETS:
        return TARGETS[mode]
    text = (custom_color or "#000000").strip()
    if text.startswith("#"):
        text = text[1:]
    if len(text) != 6:
        raise ValueError("\u81ea\u5b9a\u4e49\u989c\u8272\u5fc5\u987b\u662f #RRGGBB")
    return tuple(int(text[i:i+2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def intensity_params(mode: str, level: int) -> dict[str, float]:
    level = int(clamp(level, 1, 5))
    if mode == "black":
        low_high = {
            1: (0.025, 0.10),
            2: (0.035, 0.15),
            3: (0.050, 0.22),
            4: (0.070, 0.30),
            5: (0.095, 0.40),
        }[level]
        return {"low": low_high[0], "high": low_high[1], "rgb_tol": 0.30, "hue_tol": 0.10}
    rgb_tol = {1: 0.12, 2: 0.18, 3: 0.25, 4: 0.33, 5: 0.44}[level]
    hue_tol = {1: 0.035, 2: 0.055, 3: 0.080, 4: 0.120, 5: 0.170}[level]
    return {"rgb_tol": rgb_tol, "hue_tol": hue_tol, "low": 0.0, "high": 1.0}


def smoothstep(edge0: float, edge1: float, x: np.ndarray) -> np.ndarray:
    denom = max(edge1 - edge0, 1e-6)
    t = np.clip((x - edge0) / denom, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def rgb_to_hsv_np(rgb: np.ndarray) -> np.ndarray:
    bgr = rgb[..., ::-1].astype(np.float32)
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    hsv[..., 0] = hsv[..., 0] / 179.0
    hsv[..., 1] = hsv[..., 1] / 255.0
    hsv[..., 2] = hsv[..., 2] / 255.0
    return hsv


def remove_small_transparent_holes(alpha: np.ndarray, min_area: int) -> np.ndarray:
    if min_area <= 0:
        return alpha
    transparent = (alpha < 32).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(transparent, 8)
    result = alpha.copy()
    for idx in range(1, count):
        area = int(stats[idx, cv2.CC_STAT_AREA])
        if area < min_area:
            result[labels == idx] = 255
    return result


def _process_rule_image(image: Image.Image, params: dict[str, Any], apply_hole_punch: bool = True) -> Image.Image:
    cfg = DEFAULT_PARAMS.copy()
    cfg.update(params or {})
    mode = cfg.get("target_mode", "black")
    if mode not in TARGETS and mode != "custom":
        mode = DEFAULT_PARAMS["target_mode"]
        cfg["target_mode"] = mode
    target = np.array(parse_color(mode, cfg.get("custom_color", "#000000")), dtype=np.float32) / 255.0
    level = int(cfg.get("intensity", 3))
    ip = intensity_params(mode, level)
    strength_scale = {1: 0.72, 2: 0.86, 3: 1.0, 4: 1.18, 5: 1.38}.get(level, 1.0)

    rgba = np.array(image.convert("RGBA"), dtype=np.float32) / 255.0
    rgb = rgba[..., :3]
    original_alpha = rgba[..., 3]

    if mode == "black":
        target_rgb = target.reshape((1, 1, 3))
        color_distance = np.linalg.norm(rgb - target_rgb, axis=2) / math.sqrt(3.0)
        color_distance = np.clip(color_distance / strength_scale, 0.0, 1.0)
        low = float(cfg.get("background_threshold", ip["low"]))
        high = float(cfg.get("foreground_threshold", ip["high"]))
        alpha = smoothstep(low, high, color_distance)
        hsv = rgb_to_hsv_np(rgb)
        hue = hsv[..., 0]
        sat = hsv[..., 1]
        val = hsv[..., 2]
        fire_hue = (hue < 0.13) | (hue > 0.94)
        spark = (sat >= float(cfg.get("saturation_protect", 0.35))) & fire_hue & (val > 0.08)
        if cfg.get("keep_sparks", True):
            alpha = np.where(spark, np.maximum(alpha, 0.28 + 0.12 * (level - 1) / 4.0), alpha)
    else:
        target_rgb = target.reshape((1, 1, 3))
        rgb_dist = np.linalg.norm(rgb - target_rgb, axis=2) / math.sqrt(3.0)
        hsv = rgb_to_hsv_np(rgb)
        target_hsv = rgb_to_hsv_np(target.reshape((1, 1, 3)))[0, 0]
        hue_dist = np.abs(hsv[..., 0] - target_hsv[0])
        hue_dist = np.minimum(hue_dist, 1.0 - hue_dist)
        hue_dist = hue_dist / 0.5
        sat = hsv[..., 1]
        val = hsv[..., 2]
        target_sat = float(target_hsv[1])
        target_val = float(target_hsv[2])
        sat_miss = np.maximum(target_sat - sat, 0.0)
        val_dist = np.abs(val - target_val)
        key_distance = np.maximum(rgb_dist, hue_dist * 0.55)
        if target_sat > 0.35:
            key_distance = np.maximum(key_distance, sat_miss * 0.45)
        key_distance = np.maximum(key_distance, val_dist * 0.35)
        key_distance = np.clip(key_distance / strength_scale, 0.0, 1.0)
        low = clamp(float(cfg.get("background_threshold", 0.40)), 0.0, 1.0)
        high = clamp(float(cfg.get("foreground_threshold", 0.76)), 0.0, 1.0)
        if high <= low:
            high = min(1.0, low + 0.01)
        alpha = smoothstep(low, high, key_distance)
        alpha = np.clip(alpha, 0.0, 1.0)

    gamma = max(float(cfg.get("alpha_gamma", 1.0)), 0.1)
    alpha = np.power(np.clip(alpha, 0.0, 1.0), gamma)
    alpha = alpha * original_alpha * float(cfg.get("output_alpha", 1.0))
    alpha8 = np.clip(alpha * 255.0, 0, 255).astype(np.uint8)

    edge_erode = int(float(cfg.get("edge_erode", 0)))
    if edge_erode > 0:
        kernel = np.ones((edge_erode * 2 + 1, edge_erode * 2 + 1), np.uint8)
        alpha8 = cv2.erode(alpha8, kernel, iterations=1)

    feather = float(cfg.get("feather_radius", 0))
    if feather > 0:
        alpha_img = Image.fromarray(alpha8, "L").filter(ImageFilter.GaussianBlur(radius=feather))
        alpha8 = np.array(alpha_img, dtype=np.uint8)

    if apply_hole_punch and cfg.get("enable_hole_punch", True):
        alpha8 = remove_small_transparent_holes(alpha8, int(float(cfg.get("min_hole_size", 0))))

    out = np.array(image.convert("RGBA"), dtype=np.uint8)
    out[..., 3] = alpha8
    return Image.fromarray(out, "RGBA")


def process_image(image: Image.Image, params: dict[str, Any], apply_hole_punch: bool = True) -> Image.Image:
    return _process_rule_image(image, params, apply_hole_punch=apply_hole_punch)


def process_frame_file(input_path: Path, no_bg_path: Path, punched_path: Path, params: dict[str, Any]) -> None:
    cfg = DEFAULT_PARAMS.copy()
    cfg.update(params or {})
    with Image.open(input_path) as src:
        no_bg = _process_rule_image(src, cfg, apply_hole_punch=False)
        punched = _process_rule_image(src, cfg, apply_hole_punch=True)
    no_bg_path.parent.mkdir(parents=True, exist_ok=True)
    punched_path.parent.mkdir(parents=True, exist_ok=True)
    no_bg.save(no_bg_path)
    punched.save(punched_path)


def make_dark_preview(image: Image.Image, bg=(32, 36, 44)) -> Image.Image:
    rgba = image.convert("RGBA")
    base = Image.new("RGBA", rgba.size, bg + (255,))
    base.alpha_composite(rgba)
    return base.convert("RGB")

