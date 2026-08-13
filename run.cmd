@echo off
rem This Source Code Form is subject to the terms of the Mozilla Public
rem License, v. 2.0. If a copy of the MPL was not distributed with this
rem file, You can obtain one at https://mozilla.org/MPL/2.0/.
rem SPDX-License-Identifier: MPL-2.0
setlocal
set "APP=%~dp0GameAssetKeyer.py"

where python.exe >nul 2>&1
if not errorlevel 1 (
    set "PY=python.exe"
) else (
    where py.exe >nul 2>&1
    if not errorlevel 1 set "PY=py.exe -3"
)

if not defined PY (
    echo [ERROR] Python 3 not found in PATH.
    echo Install Python 3, then run: pip install -r requirements.txt
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
%PY% "%APP%"
exit /b %ERRORLEVEL%
