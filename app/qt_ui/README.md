# Qt source workbench

This is the editable Qt frontend, not the read-only design preview. It reuses
the existing project format, Pipeline workers, final-result resolver, trimming,
alignment and export services. No processing algorithm is implemented here.

## Run

`run.cmd` starts `GameAssetKeyer.py --qt`. It selects `GAK_QT_PYTHON`, a local
`.venv-qt/Scripts/python.exe`, or the existing isolated Qt review environment,
in that order. `run_legacy.cmd` continues to start the Tk source UI. Close one
frontend before editing the same project in the other.

For a new setup, create a separate virtual environment and install
`requirements-qt.txt` there. The release build creates its own isolated environment.
Running `GameAssetKeyer.py` without `--qt` keeps the existing Tk behavior.

Windows releases start this frontend automatically, remain CPU-only, and use
PyInstaller windowed onedir with the complete Tcl/Tk runtime retained.

## Workflow

- Create a Single PNG, Sprite Sheet or Video project in one parent-owned dialog.
- Edit shared stage defaults. Use **Frame override** before editing an exception;
  use **Stage defaults** to remove that exception.
- Preview a stage in memory, or process one/all frames with the existing workers.
- The final view is available only for a complete, valid output. It never shows
  stale trim/alignment data after a pipeline edit.
- Uniform trim and alignment are always below the two preview panels. Either
  can run after all frames are processed. Export uses the same final resolver.
- Video exports a PNG sequence; image/sheet projects export their PNG/sheet.
- Play preview replaces the two comparison canvases with one large inline
  animation surface and starts playback immediately. Source, pause, FPS, loop and
  seek controls stay in that area. Stop, Back or Escape restores the comparison
  without changing the selected editing frame. Editing or switching frames also
  exits playback, so an old animation cannot outlive its source settings.
- **Window playback** expands that same player over the application's client
  area, hiding the header, sidebars and status bar without opening another window
  or entering OS fullscreen. Play/pause and Exit remain available. Exit or Escape
  returns to inline playback, retaining the frame, FPS, loop and playback state.
- Independent sequence composition, video-range extraction and equal-grid
  expansion remain homepage tools. Confirmation dialogs are owned by the UI.

The material stylesheet uses optional local-only assets, excluded from public
source and release packages. Without them, the frontend automatically uses the
plain dark stylesheet and hides the unavailable material switch.

## Verification

In the isolated Qt environment, run:

```powershell
python -m unittest discover -s tests_qt -v
python GameAssetKeyer.py --qt --check
```

The integration suite uses disposable projects under `I:/CodexSafeCheck` when
available (otherwise the system temporary directory) and an
offscreen Qt platform at 125% scale. Existing tests in `tests/` remain separate
and must still pass in the existing Python environment. Offscreen tests do not
replace a human check of the real Windows display, dialogs and large assets.
