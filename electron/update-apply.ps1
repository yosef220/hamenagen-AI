# Swap in the parts of a smart update, after the player has closed.
#
# Written next to the plan by electron/main.js and started detached, just
# before the app quits. It waits for the app (and anything else running from
# its folder) to exit; then, part by part, it moves the old files aside and
# the new ones in. If anything fails, everything moved so far goes back, so
# the old version keeps working. The outcome goes to result.json, which the
# app reads on its next start; then the app is started again.
#
# The plan (plan.json, made by backend/hamenagen/smart_update.py):
#   root, resources, work, result, parts_json, version,
#   parts: [{ name, kind (root|files|dir), staging, old: [...], new: [...] }]
#
# ASCII only: Windows PowerShell reads a script without a byte-order mark in
# the local code page. Every path comes from the plan, read as UTF-8.

param(
  [Parameter(Mandatory = $true)][string]$Plan,
  [int]$WaitPid = 0,
  [string]$Relaunch = '',
  [int]$FailAfter = -1   # tests: fail on purpose after this many moves
)

$ErrorActionPreference = 'Stop'
$plan = Get-Content -LiteralPath $Plan -Raw -Encoding UTF8 | ConvertFrom-Json
$log = Join-Path $plan.work 'apply.log'

function Log([string]$text) {
  try { Add-Content -LiteralPath $log -Value ("{0:s} {1}" -f (Get-Date), $text) -Encoding UTF8 } catch { }
}

function Write-Result([bool]$ok, [string]$errorText) {
  $result = @{ ok = $ok; version = $plan.version; error = $errorText; at = (Get-Date).ToString('s') }
  [IO.File]::WriteAllText($plan.result, ($result | ConvertTo-Json -Compress), (New-Object Text.UTF8Encoding $false))
}

function Move-WithRetry([string]$from, [string]$to) {
  for ($i = 0; $i -lt 40; $i++) {
    try {
      Move-Item -LiteralPath $from -Destination $to -Force
      return
    } catch {
      Start-Sleep -Milliseconds 500   # a virus scanner or the indexer may hold a file for a moment
    }
  }
  throw "cannot move $from"
}

Log "update to $($plan.version): waiting for the player to close"
if ($WaitPid -gt 0) {
  try { Wait-Process -Id $WaitPid -Timeout 90 -ErrorAction SilentlyContinue } catch { }
}
# Anything still running from the program's folder (the core, ffmpeg, yt-dlp).
$root = [IO.Path]::GetFullPath($plan.root).TrimEnd('\') + '\'
$deadline = (Get-Date).AddSeconds(90)
while ((Get-Date) -lt $deadline) {
  $busy = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
      Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($root, [StringComparison]::OrdinalIgnoreCase) })
  if ($busy.Count -eq 0) { break }
  Start-Sleep -Milliseconds 500
}

$backup = Join-Path $plan.work 'backup'
if (Test-Path -LiteralPath $backup) { Remove-Item -LiteralPath $backup -Recurse -Force -ErrorAction SilentlyContinue }
New-Item -ItemType Directory -Force -Path $backup | Out-Null
$done = New-Object System.Collections.ArrayList   # @(target, backup or $null) in the order done
$moves = 0
$ok = $false
$message = ''

try {
  foreach ($part in $plan.parts) {
    $base = if ($part.kind -eq 'root') { $plan.root } else { $plan.resources }
    Log "part $($part.name)"
    foreach ($entry in @($part.old)) {
      $target = Join-Path $base $entry
      if (Test-Path -LiteralPath $target) {
        $aside = Join-Path $backup ("{0}__{1}" -f $part.name, $entry)
        Move-WithRetry $target $aside
        [void]$done.Add(@($target, $aside))
        $moves++
        if ($FailAfter -ge 0 -and $moves -ge $FailAfter) { throw "failing on purpose (test)" }
      }
    }
    foreach ($entry in @($part.new)) {
      $source = Join-Path $part.staging $entry
      $target = Join-Path $base $entry
      if (Test-Path -LiteralPath $target) {
        # Not in the old list but in the way (an older leftover): set it aside too.
        $aside = Join-Path $backup ("{0}__new__{1}" -f $part.name, $entry)
        Move-WithRetry $target $aside
        [void]$done.Add(@($target, $aside))
      }
      Move-WithRetry $source $target
      [void]$done.Add(@($target, $null))
      $moves++
      if ($FailAfter -ge 0 -and $moves -ge $FailAfter) { throw "failing on purpose (test)" }
    }
  }
  Copy-Item -LiteralPath $plan.parts_json -Destination (Join-Path $plan.resources 'parts.json') -Force
  $ok = $true
  Log "done"
} catch {
  $message = "$_"
  Log "failed: $message; putting the old version back"
  for ($i = $done.Count - 1; $i -ge 0; $i--) {
    $target = $done[$i][0]
    $aside = $done[$i][1]
    try {
      if ($null -eq $aside) {
        if (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Recurse -Force }
      } else {
        if (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Recurse -Force }
        Move-Item -LiteralPath $aside -Destination $target -Force
      }
    } catch {
      Log "could not restore ${target}: $_"
    }
  }
}

# The installed version in "Apps" follows the program (installed editions).
if ($ok) {
  try {
    Get-ChildItem 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall' -ErrorAction SilentlyContinue | ForEach-Object {
      $item = Get-ItemProperty -LiteralPath $_.PSPath -ErrorAction SilentlyContinue
      if ($item -and $item.InstallLocation -and
          ([IO.Path]::GetFullPath($item.InstallLocation).TrimEnd('\') + '\') -ieq $root) {
        Set-ItemProperty -LiteralPath $_.PSPath -Name DisplayVersion -Value $plan.version
      }
    }
  } catch { }
}

Write-Result $ok $message
if ($Relaunch -and (Test-Path -LiteralPath $Relaunch)) {
  Start-Process -FilePath $Relaunch
}
if ($ok) {
  Remove-Item -LiteralPath $backup -Recurse -Force -ErrorAction SilentlyContinue
}
