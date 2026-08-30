<#
.SYNOPSIS
  Prepare an embedded Windows Python for the portable build (spec §4, §6).

.DESCRIPTION
  Downloads the official Windows "embeddable" CPython, enables site-packages,
  bootstraps pip, and installs the backend's optional dependencies into it.
  electron-builder then copies build/win-python -> resources/python (see
  package.json build.extraResources), and backend_bridge.js runs that
  interpreter so the end user needs no system Python installed.

.NOTES
  Run on Windows before `npm run dist`, or use `npm run build:win`.
#>

param(
  [string]$PythonVersion = "3.11.9",
  [string]$OutDir = "build/win-python"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$zipName = "python-$PythonVersion-embed-amd64.zip"
$url = "https://www.python.org/ftp/python/$PythonVersion/$zipName"
$tmp = Join-Path $env:TEMP $zipName

Write-Host "Downloading $url ..."
Invoke-WebRequest -Uri $url -OutFile $tmp

if (Test-Path $OutDir) { Remove-Item -Recurse -Force $OutDir }
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
Write-Host "Extracting to $OutDir ..."
Expand-Archive -Path $tmp -DestinationPath $OutDir -Force

# Enable `import site` so pip-installed packages are importable: uncomment the
# `#import site` line in the ._pth file.
$pth = Get-ChildItem -Path $OutDir -Filter "python*._pth" | Select-Object -First 1
if ($pth) {
  (Get-Content $pth.FullName) -replace '#\s*import site', 'import site' | Set-Content $pth.FullName
}

# Bootstrap pip.
$getpip = Join-Path $OutDir "get-pip.py"
Invoke-WebRequest -Uri "https://bootstrap.pypa.io/get-pip.py" -OutFile $getpip
& "$OutDir/python.exe" $getpip --no-warn-script-location

# Install runtime deps (skip the heavy embedding model by default; add it with
# -EmbedModel if you want it bundled).
& "$OutDir/python.exe" -m pip install --no-warn-script-location -r requirements.txt

Write-Host "Embedded Python ready at $OutDir"
Write-Host "Next: npm run dist  (produces dist/hamenagen-portable-<version>.exe)"
