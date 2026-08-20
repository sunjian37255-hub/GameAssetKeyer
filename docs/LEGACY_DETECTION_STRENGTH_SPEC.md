# Legacy Detection Strength Specification

## Reference build

- `OLD_PORTABLE_PATH`: `D:\SpriteSheetCleaner`
- `EXE_NAME`: `SpriteSheetCleaner.exe`
- File size: `5,943,468` bytes
- SHA-256: `B6214AC5423674AA2E639B4BF108B4D722840753B88DB90FE7302711F08207CE`
- Windows version information: not present
- Recovery method: PyInstaller CArchive/PYZ inspection followed by Python 3.14
  code-object disassembly and direct execution of the extracted
  `app.color_key_processor` bytecode.

## Confidence

`LEGACY_SPEC_CONFIDENCE: EXACT`

The executable's `SpriteSheetCleaner`, `app.color_key_processor`,
`app.ui_main`, `app.project_manager`, and `app.preset_manager` code objects were
recovered. A 326-pixel diagnostic set was evaluated at all five strength values
for gray custom, green, black, and white-equivalent custom targets. The 1,630
legacy Alpha results matched GameAssetKeyer v1.1.0 with the same parameters
exactly (maximum Alpha difference: `0`).

## UI control

- Old UI label: `检测强度`
- Control type: `ttk.Scale`
- Minimum: `1`
- Maximum: `5`
- Default: `3`
- Step: the Scale has no explicit resolution option; values are read and saved
  through integer conversion, so the effective persisted step is `1`.
- The old UI displays five strict/standard/loose labels.

The supplied legacy executable does **not** contain a continuous 0-255 or other
continuous color-tolerance control.

## Target color representation

Built-in legacy targets are RGB byte triples:

- Green: `(0, 255, 0)`
- Black: `(0, 0, 0)`
- Magenta: `(255, 0, 255)`
- Custom: parsed from `#RRGGBB`

Processing converts target and input RGB values to floating-point `[0, 1]`.
The legacy executable has no native White mode; its equivalent is Custom
`#FFFFFF`.

## Non-black distance metric

For Green, Magenta, and Custom targets, the recovered implementation computes:

```text
rgb_dist = L2(rgb - target_rgb) / sqrt(3)
hue_dist = min(abs(hue - target_hue), 1 - abs(hue - target_hue)) / 0.5
sat_miss = max(target_saturation - saturation, 0)
val_dist = abs(value - target_value)

key_distance = max(rgb_dist, hue_dist * 0.55)
if target_saturation > 0.35:
    key_distance = max(key_distance, sat_miss * 0.45)
key_distance = max(key_distance, val_dist * 0.35)
```

HSV values come from OpenCV and are normalized to `[0, 1]`.

## Detection Strength formula

The recovered legacy implementation maps the five strength levels to a scale:

```text
1 -> 0.72
2 -> 0.86
3 -> 1.00
4 -> 1.18
5 -> 1.38
```

It then evaluates:

```text
scaled_distance = clip(key_distance / strength_scale, 0, 1)
alpha = smoothstep(background_threshold, foreground_threshold, scaled_distance)
```

Therefore the supplied legacy executable's Detection Strength is a five-level
scale applied to a hybrid RGB/HSV distance. It is not a direct numeric
per-channel deviation or continuous tolerance value.

`intensity_params()` also contains `rgb_tol` and `hue_tol` lookup tables, but
the recovered non-black processing path never reads either result. They are
dead implementation data in this reference executable and are not evidence of
an active legacy tolerance formula.

## Black behavior

Black uses a separate brightness path:

```text
brightness = max(red, green, blue)
alpha = smoothstep(background_threshold, foreground_threshold, brightness)
```

Changing Detection Strength in the legacy UI rewrites the two thresholds:

| Strength | Background threshold | Foreground threshold |
| ---: | ---: | ---: |
| 1 | 0.025 | 0.10 |
| 2 | 0.035 | 0.15 |
| 3 | 0.050 | 0.22 |
| 4 | 0.070 | 0.30 |
| 5 | 0.095 | 0.40 |

When spark preservation is enabled, saturated red/orange pixels can receive a
minimum Alpha after this calculation.

## Alpha behavior

The core transition is soft, not binary:

```text
t = clip((x - low) / max(high - low, 1e-6), 0, 1)
smoothstep = t * t * (3 - 2 * t)
```

After the target-color calculation, the legacy implementation applies Alpha
gamma, original input Alpha, output Alpha, uint8 conversion, optional erosion,
optional Gaussian feathering, and optional small-hole removal, in that order.

## Per-mode summary

- Black: maximum-channel brightness plus UI-coupled threshold presets.
- Green: hybrid RGB/HSV distance divided by the five-level strength scale.
- Magenta: the same non-black hybrid distance path.
- Custom: the same non-black hybrid distance path using `#RRGGBB`.
- White: no native legacy mode; Custom `#FFFFFF` uses the non-black path.

## New-project defaults

The legacy project manager writes an empty `last_params` object for a new
project. Loading it therefore applies the processor defaults:

```text
background_threshold = 0.40
foreground_threshold = 0.76
```

GameAssetKeyer v1.1.0 instead writes explicit `0.0 / 0.0` basic parameters.
`ensure_pipeline()` and `normalize_params()` preserve those explicit zeros.
This is a verified behavior difference from the supplied legacy executable.

## Recovery verdict

`CURRENT_INTENSITY_IS_PRESET_SELECTOR: YES`

The same statement is also true of the supplied legacy executable. Restoring
that executable's exact Detection Strength behavior requires retaining the
five-level hybrid-distance scale and the Black threshold coupling. A change to
a continuous or direct color-tolerance formula would be a new design rather
than recovery of this reference implementation.

## v1.1.1 product decision

After recovery, the user clarified that the legacy Black threshold coupling was
an omitted implementation rather than the intended Black semantics. v1.1.1
therefore intentionally departs from the recovered Black behavior:

- Black uses normalized RGB Euclidean distance to `(0, 0, 0)`.
- The same five-level `strength_scale` expands the accepted Black color range.
- Changing Detection Strength no longer overwrites Background/Foreground
  Threshold.
- Explicit `0.0 / 0.0` threshold values remain unchanged as the project's
  not-yet-configured state.

The recovered facts in the preceding sections remain the exact specification
of the supplied legacy executable.
