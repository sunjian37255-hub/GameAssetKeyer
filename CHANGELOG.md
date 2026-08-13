# Changelog

All notable changes to this project will be documented in this file.

## [1.0.3] - 2026-08-14

### Changed

- Relicensed the current GameAssetKeyer codebase under Mozilla Public License 2.0.
- Added MPL 2.0 source-file notices.
- Added corresponding-source information and third-party license notices to the Windows distribution.

No processing or runtime behavior changed. Versions published before this migration used MIT.

## [1.0.2] - 2026-08-13

### Fixed

- The eyedropper now samples the image currently displayed in either side of the dual preview.
- Eyedropper activation, cancellation, transparent-pixel handling, and outside-image feedback now stay synchronized across both preview canvases.

## [1.0.1] - 2026-08-13

### Fixed

- Video projects now export an ordered RGBA PNG frame sequence instead of rebuilding a Sprite Sheet.
- Video export uses the same validated Pipeline, Trim, and Alignment resolver as Final Result preview.
- Shorter frame-sequence re-exports replace the previous output without leaving stale frames.
- Unsaved basic Stage parameters now remain Stage defaults when navigating between Sprite Sheet or video frames.

### Changed

- New projects start with zero values for the basic threshold, feather, and edge-erosion fields while advanced defaults remain unchanged.
- The Video action is labeled `Export PNG Frame Sequence` / `导出 PNG 帧序列`.

## [1.0.0] - 2026-08-13

### Added

- Single-image, Sprite Sheet, and video-frame workflows
- Multi-pass chroma key with preset and custom target colors
- Eyedropper, per-stage parameters, and per-frame overrides
- Background batch worker with progress and cancellation
- Unified trimming, frame alignment, and Sprite Sheet export
- Standalone equal-grid expansion utility
- Simplified Chinese and English interfaces
- Portable Windows x64 onedir release

### Reliability

- Alpha monotonic protection across stages
- Pipeline and post-processing cache invalidation
- Final Preview and Export consistency through one resolver
- Isolated Windows Sandbox validation workflow
