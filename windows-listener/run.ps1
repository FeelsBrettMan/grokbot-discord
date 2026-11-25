<#
  Runs the listener with an auto-restart loop. The scheduled task calls this;
  you can also run it by hand in a PowerShell window (Ctrl+C to stop).
#>
$ErrorActionPreference = 'Continue'
Set-Location $PSScriptRoot
$env:PYTHONUNBUFFERED = '1'
$venvPy = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
New-Item -ItemType Directory -Force -Path logs | Out-Null
$sup = Join-Path $PSScriptRoot 'logs\supervisor.log'
function Note($m) { Add-Content -Path $sup -Value ("{0} {1}" -f (Get-Date -Format s), $m) }

if (-not (Test-Path $venvPy)) { Note 'venv missing: run install.ps1'; exit 1 }
$delay = 10
while ($true) {
    Note 'starting bridge'
    & $venvPy -m discord_bridge
    $rc = $LASTEXITCODE
    if ($rc -eq 2) { Note 'config error (see logs\bridge.log); not restarting'; exit 2 }
    if ($rc -eq 3) { Note 'another instance is already running; exiting'; exit 0 }
    Note "bridge exited rc=$rc; restarting in $delay s"
    Start-Sleep -Seconds $delay
    $delay = [Math]::Min($delay * 2, 300)
}
