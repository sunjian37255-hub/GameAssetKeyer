@echo off
rem This Source Code Form is subject to the terms of the Mozilla Public
rem License, v. 2.0. If a copy of the MPL was not distributed with this
rem file, You can obtain one at https://mozilla.org/MPL/2.0/.
rem SPDX-License-Identifier: MPL-2.0
setlocal
set "APP=%~dp0GameAssetKeyer.py"
set "PY="

rem Prefer the real CPython installation.  WindowsApps may contain a
rem python.exe alias that `where` can see even though cmd.exe cannot run it.
if exist "%LocalAppData%\Python\pythoncore-3.14-64\python.exe" set "PY=%LocalAppData%\Python\pythoncore-3.14-64\python.exe"
if not defined PY if exist "%LocalAppData%\Python\bin\python.exe" set "PY=%LocalAppData%\Python\bin\python.exe"

if not defined PY (
    for /f "delims=" %%P in ('where python.exe 2^>nul') do (
        echo %%P | findstr /i /c:"\WindowsApps\" >nul
        if errorlevel 1 if not defined PY set "PY=%%P"
    )
)

if not defined PY (
    where py.exe >nul 2>&1
    if not errorlevel 1 (
        cd /d "%~dp0"
        py.exe -3 "%APP%" %*
        exit /b %ERRORLEVEL%
    )
    echo [ERROR] Python 3 not found.
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
"%PY%" "%APP%" %*
exit /b %ERRORLEVEL%
