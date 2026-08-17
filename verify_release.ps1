# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0

param(
    [Parameter(Mandatory = $true)]
    [string]$ReleaseDir
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath $ReleaseDir).Path
$failures = [System.Collections.Generic.List[string]]::new()

function Find-ReleaseItem {
    param([string]$Name)
    @(Get-ChildItem -LiteralPath $root -Recurse -Force | Where-Object { $_.Name -ieq $Name })
}

function Require-File {
    param([string]$Name)
    $matches = @(Find-ReleaseItem $Name | Where-Object { -not $_.PSIsContainer })
    if ($matches.Count -eq 0) { $failures.Add("Missing file: $Name") }
}

function Require-Directory {
    param([string]$Name)
    $matches = @(Find-ReleaseItem $Name | Where-Object { $_.PSIsContainer })
    if ($matches.Count -eq 0) { $failures.Add("Missing directory: $Name") }
}

if (-not (Test-Path -LiteralPath (Join-Path $root 'GameAssetKeyer.exe') -PathType Leaf)) {
    $failures.Add('Missing root executable: GameAssetKeyer.exe')
}

Require-File 'README.txt'
Require-File 'LICENSE'
Require-File 'SOURCE.txt'
Require-File 'THIRD_PARTY_NOTICES.txt'
Require-Directory 'THIRD_PARTY_LICENSES'

$license = Get-Content -Raw -LiteralPath (Join-Path $root 'LICENSE')
if (-not $license.StartsWith('Mozilla Public License Version 2.0')) {
    $failures.Add('Root LICENSE is not Mozilla Public License Version 2.0')
}
if ($license -match '(?im)^MIT License\s*$') {
    $failures.Add('Obsolete MIT root license found')
}
$sourceNotice = Get-Content -Raw -LiteralPath (Join-Path $root 'SOURCE.txt')
if ($sourceNotice -notmatch [regex]::Escape('https://github.com/sunjian37255-hub/GameAssetKeyer/tree/v1.1.0')) {
    $failures.Add('SOURCE.txt does not point to the v1.1.0 corresponding source')
}
$thirdParty = Join-Path $root 'THIRD_PARTY_LICENSES'
foreach ($pattern in @('CPython-3.14.3-LICENSE.txt', 'Tcl-Tk-8.6.15-license.terms', 'numpy-2.4.4', 'Pillow-12.2.0', 'opencv-python-headless-4.13.0.92', 'PyInstaller-6.21.0')) {
    if (@(Get-ChildItem -LiteralPath $thirdParty -Recurse -Force | Where-Object { $_.Name -ieq $pattern }).Count -eq 0) {
        $failures.Add("Missing third-party license material: $pattern")
    }
}

@('python314.dll', '_tkinter.pyd', 'tcl86t.dll', 'tk86t.dll', 'opencv_videoio_ffmpeg4130_64.dll', 'VCRUNTIME140.dll', 'VCRUNTIME140_1.dll') |
    ForEach-Object { Require-File $_ }
@('_tcl_data', '_tk_data', 'tcl', 'cv2', 'numpy', 'numpy.libs', 'PIL') |
    ForEach-Object { Require-Directory $_ }

if (@(Get-ChildItem -LiteralPath $root -Recurse -File -Filter '_imaging*.pyd').Count -eq 0) {
    $failures.Add('Missing Pillow native imaging component: _imaging*.pyd')
}
if (@(Get-ChildItem -LiteralPath $root -Recurse -File -Filter 'libscipy_openblas64_*.dll').Count -eq 0) {
    $failures.Add('Missing NumPy OpenBLAS runtime: numpy.libs\libscipy_openblas64_*.dll')
}
$ucrt = @(Get-ChildItem -LiteralPath $root -Recurse -File | Where-Object { $_.Name -ieq 'ucrtbase.dll' -or $_.Name -like 'api-ms-win-crt-runtime-*.dll' })
if ($ucrt.Count -eq 0) { $failures.Add('Missing UCRT runtime') }

$forbiddenPatterns = @('rembg', 'onnxruntime', 'pymatting', 'skimage', 'torch', 'tensorflow', 'cuda')
foreach ($item in Get-ChildItem -LiteralPath $root -Recurse -Force) {
    $relative = [IO.Path]::GetRelativePath($root, $item.FullName)
    foreach ($pattern in $forbiddenPatterns) {
        if ($relative -match [regex]::Escape($pattern)) {
            $failures.Add("Forbidden AI artifact: $relative")
            break
        }
    }
}

$projects = Join-Path $root 'projects'
if (-not (Test-Path -LiteralPath $projects -PathType Container)) {
    $failures.Add('Missing empty projects directory')
} elseif (@(Get-ChildItem -LiteralPath $projects -Force).Count -ne 0) {
    $failures.Add('Release projects directory is not empty')
}

$forbiddenFiles = @(Get-ChildItem -LiteralPath $root -Recurse -File | Where-Object {
    $_.Extension -in @('.pyc', '.log', '.mp4', '.avi', '.mov', '.mkv', '.webm') -or $_.FullName -match '__pycache__'
})
foreach ($item in $forbiddenFiles) {
    $failures.Add("Forbidden runtime or user artifact: $([IO.Path]::GetRelativePath($root, $item.FullName))")
}

if ($failures.Count -gt 0) {
    $failures | ForEach-Object { Write-Error $_ }
    exit 1
}

$files = @(Get-ChildItem -LiteralPath $root -Recurse -File)
$bytes = ($files | Measure-Object -Property Length -Sum).Sum
Write-Host "Release verification PASS"
Write-Host "Root: $root"
Write-Host "Files: $($files.Count)"
Write-Host "Bytes: $bytes"
exit 0
