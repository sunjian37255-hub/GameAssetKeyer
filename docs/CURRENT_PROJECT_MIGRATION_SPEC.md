# Current Project Migration Specification

## v1.1.0 to v1.1.1

No project-data migration is performed.

- `intensity` remains an integer from `1` through `5`.
- The existing strength mapping remains `0.72, 0.86, 1.00, 1.18, 1.38`.
- `background_threshold` and `foreground_threshold` retain their saved values.
- Explicit `0.0 / 0.0` values remain the not-yet-configured state.
- Stage defaults and per-frame overrides retain the same field names and values.
- Presets retain the same field names and values.

The Black processing behavior changes when a frame is next processed: Black
now uses normalized RGB Euclidean distance to pure black and applies the same
Detection Strength scale as the other target colors. Moving the Detection
Strength control no longer rewrites either Alpha threshold.

The processor cache version is part of Stage and per-frame cache signatures in
v1.1.1. Existing cached outputs are therefore recalculated without modifying
the saved project parameters.
