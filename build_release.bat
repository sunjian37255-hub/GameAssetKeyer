@echo off
rem This Source Code Form is subject to the terms of the Mozilla Public
rem License, v. 2.0. If a copy of the MPL was not distributed with this
rem file, You can obtain one at https://mozilla.org/MPL/2.0/.
rem SPDX-License-Identifier: MPL-2.0
setlocal EnableExtensions
cd /d "%~dp0"

set "ROOT=%CD%"
set "VERSION="
set /p VERSION=<"%ROOT%\VERSION"
set "VENV=%ROOT%\.build-venv"
set "WORK=%ROOT%\build-release"
set "DIST=%ROOT%\dist-release"
set "RELEASE=%ROOT%\release"
set "APPDIR=%DIST%\GameAssetKeyer"
set "ZIP=%RELEASE%\GameAssetKeyer-v%VERSION%-Windows-x64.zip"
if defined GAK_PYTHON (set "BASEPY=%GAK_PYTHON%") else (set "BASEPY=python.exe")

echo [1/13] Checking base Python 3.14.3 x64...
"%BASEPY%" -c "import platform,struct,sys; raise SystemExit(0 if platform.python_version()=='3.14.3' and struct.calcsize('P')==8 else 1)" || goto :fail

echo [2/13] Creating isolated build environment...
if exist "%VENV%" rmdir /s /q "%VENV%"
"%BASEPY%" -m venv "%VENV%" || goto :fail
set "BUILDPY=%VENV%\Scripts\python.exe"

echo [3/13] Installing locked build dependencies into the isolated environment...
"%BUILDPY%" -m pip install --disable-pip-version-check -r "%ROOT%\requirements-runtime.txt" -r "%ROOT%\requirements-build.txt" || goto :fail

echo [4/13] Verifying exact dependency versions and OpenCV wheel purity...
"%BUILDPY%" "%ROOT%\tools\check_build_environment.py" || goto :fail

echo [5/13] Running source checks and tests...
"%BUILDPY%" "%ROOT%\GameAssetKeyer.py" --check || goto :fail
"%BUILDPY%" -m unittest discover -s "%ROOT%\tests" -v || goto :fail

echo [6/13] Cleaning dedicated build outputs...
if exist "%WORK%" rmdir /s /q "%WORK%"
if exist "%DIST%" rmdir /s /q "%DIST%"
if not exist "%RELEASE%" mkdir "%RELEASE%" || goto :fail
if exist "%ZIP%" del /f /q "%ZIP%" || goto :fail
if exist "%ZIP%.sha256" del /f /q "%ZIP%.sha256" || goto :fail
mkdir "%WORK%" "%DIST%" || goto :fail

echo [7/13] Building PyInstaller windowed onedir package...
"%BUILDPY%" -m PyInstaller --noconfirm --clean --workpath "%WORK%" --distpath "%DIST%" "%ROOT%\GameAssetKeyer.spec" || goto :fail

echo [8/13] Copying the complete Tcl/Tk runtime from the build Python...
"%BUILDPY%" "%ROOT%\tools\copy_tcl_runtime.py" "%APPDIR%" || goto :fail

echo [9/13] Copying public presets, licensing, and documentation...
xcopy "%ROOT%\presets" "%APPDIR%\presets\" /E /I /Y /Q >nul || goto :fail
copy /Y "%ROOT%\README.md" "%APPDIR%\README.txt" >nul || goto :fail
copy /Y "%ROOT%\LICENSE" "%APPDIR%\LICENSE" >nul || goto :fail
copy /Y "%ROOT%\SOURCE.txt" "%APPDIR%\SOURCE.txt" >nul || goto :fail
copy /Y "%ROOT%\THIRD_PARTY_NOTICES.txt" "%APPDIR%\THIRD_PARTY_NOTICES.txt" >nul || goto :fail
"%BUILDPY%" "%ROOT%\tools\copy_third_party_licenses.py" "%APPDIR%" || goto :fail
mkdir "%APPDIR%\projects" || goto :fail
"%BUILDPY%" "%ROOT%\tools\check_build_environment.py" --output "%APPDIR%\BUILD_MANIFEST.json" || goto :fail

echo [10/13] Verifying the release directory...
pwsh.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%ROOT%\verify_release.ps1" -ReleaseDir "%APPDIR%" || goto :fail

echo [11/13] Running packaged import smoke test...
"%APPDIR%\GameAssetKeyer.exe" --check || goto :fail

echo [12/13] Creating ZIP and SHA-256...
pwsh.exe -NoLogo -NoProfile -Command "Compress-Archive -LiteralPath '%APPDIR%' -DestinationPath '%ZIP%' -CompressionLevel Optimal -Force" || goto :fail
pwsh.exe -NoLogo -NoProfile -Command "$h=(Get-FileHash -LiteralPath '%ZIP%' -Algorithm SHA256).Hash.ToLowerInvariant(); Set-Content -LiteralPath '%ZIP%.sha256' -Value ($h+'  '+[IO.Path]::GetFileName('%ZIP%')) -Encoding ascii; Write-Host ('SHA256: '+$h)" || goto :fail

echo [13/13] Build complete. Removing isolated environment...
rmdir /s /q "%VENV%"
echo Release: "%ZIP%"
echo Verify:  "%ZIP%.sha256"
exit /b 0

:fail
echo.
echo [ERROR] Release build failed. System Python was not modified.
echo Isolated environment retained for diagnostics: "%VENV%"
exit /b 1
