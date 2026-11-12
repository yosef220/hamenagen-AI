<#
.SYNOPSIS
  Prepare an embedded Windows Python for the packaged app (every edition).

.DESCRIPTION
  Downloads the official Windows "embeddable" CPython, enables site-packages,
  bootstraps pip, and installs the backend's optional dependencies into it.
  electron-builder then copies build/win-python -> resources/python (see
  electron-builder.config.js), and backend_bridge.js runs that interpreter so
  the end user needs no system Python installed.

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
  # In the packaged layout the interpreter lives at resources/python and the
  # backend at resources/backend, so add ..\backend to sys.path. (The bridge
  # also inserts it at runtime; this makes `-m hamenagen.rpc` work too.)
  Add-Content $pth.FullName "..\backend"
}

# Bootstrap pip.
$getpip = Join-Path $OutDir "get-pip.py"
Invoke-WebRequest -Uri "https://bootstrap.pypa.io/get-pip.py" -OutFile $getpip
# A fixed pip, so the embedded Python is the same in every build.
& "$OutDir/python.exe" $getpip --no-warn-script-location --no-setuptools --no-wheel "pip==26.2.2"

# Install the core's libraries (the AI model itself is fetched separately:
# backend/scripts/prepare_model.py, for the offline edition).
# Exact versions (requirements-lock.txt): the same files in every build, so the
# smart update sends this part only when a version really changed.
& "$OutDir/python.exe" -m pip install --no-warn-script-location --no-compile --no-deps -r requirements-lock.txt
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

# Trim what the app never uses at runtime: pip itself stays (yt-dlp updates
# through it), caches and test suites go.
Get-ChildItem -Path $OutDir -Recurse -Directory -Include "__pycache__", "tests" -ErrorAction SilentlyContinue |
  Where-Object { $_.FullName -match "site-packages" } |
  Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

Write-Host "Embedded Python ready at $OutDir"
Write-Host "Next: npm run dist  (produces dist/Hamenagen-<version>-Windows.zip)"
