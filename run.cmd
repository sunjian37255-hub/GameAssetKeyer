@echo off
rem This Source Code Form is subject to the terms of the Mozilla Public
rem License, v. 2.0. If a copy of the MPL was not distributed with this
rem file, You can obtain one at https://mozilla.org/MPL/2.0/.
rem SPDX-License-Identifier: MPL-2.0
setlocal
set "APP=%~dp0GameAssetKeyer.py"
set "PY="

rem Qt stays isolated from the verified release build environment.
if defined GAK_QT_PYTHON if exist "%GAK_QT_PYTHON%" set "PY=%GAK_QT_PYTHON%"
if not defined PY if exist "%~dp0.venv-qt\Scripts\python.exe" set "PY=%~dp0.venv-qt\Scripts\python.exe"
if not defined PY if exist "I:\CodexSafeCheck\GameAssetKeyer-QtPreview\venv\Scripts\python.exe" set "PY=I:\CodexSafeCheck\GameAssetKeyer-QtPreview\venv\Scripts\python.exe"

if not defined PY (
    echo [ERROR] Qt source environment not found.
    echo Create .venv-qt and install requirements-qt.txt, or set GAK_QT_PYTHON.
    echo The existing Tk source UI is available through run_legacy.cmd.
    pause
    exit /b 1
)

if not exist "%APP%" (
    echo [ERROR] App not found:
    echo %APP%
    pause
    exit /b 1
)

cd /d "%~dp0"
"%PY%" "%APP%" --qt %*
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" (
    echo [ERROR] GameAssetKeyer exited with code %RESULT%.
    if "%~1"=="" pause
)
exit /b %RESULT%
