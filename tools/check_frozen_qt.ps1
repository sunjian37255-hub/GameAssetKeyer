# SPDX-License-Identifier: MPL-2.0
param([Parameter(Mandatory)][string]$AppDir, [Parameter(Mandatory)][string]$Output)
$ErrorActionPreference = 'Stop'
$exe = Join-Path $AppDir 'GameAssetKeyer.exe'
$check = Start-Process -FilePath $exe -ArgumentList '--check' -WindowStyle Hidden -Wait -PassThru
if ($check.ExitCode -ne 0) { throw "Packaged --check failed: $($check.ExitCode)" }
$process = Start-Process -FilePath $exe -ArgumentList @('--qt-smoke-output', ('"' + $Output + '"')) -WindowStyle Hidden -Wait -PassThru
if ($process.ExitCode -ne 0) { throw "Qt smoke failed: $($process.ExitCode)" }
$result = Get-Content -Raw -LiteralPath $Output | ConvertFrom-Json
if (-not $result.ok -or $result.material -or $result.backend -ne 'cpu' -or $result.platform -ne 'windows' -or $result.title -ne 'GameAssetKeyer') {
    throw "Unexpected Qt release state: $($result | ConvertTo-Json -Compress)"
}
$result | ConvertTo-Json
