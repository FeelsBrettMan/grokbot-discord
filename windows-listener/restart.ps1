<#
  Restarts the listener after you edit .env. From an *Administrator* PowerShell:
      cd C:\discord-bridge
      powershell -ExecutionPolicy Bypass -File .\restart.ps1
  Stops the task, kills any leftover listener from this folder, checks .env,
  starts the task and shows the last log lines (look for "config ok",
  "listener starting: version ..." and "online as ...").
#>
param([string]$Target = $PSScriptRoot)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')
$Target = (Resolve-Path $Target).Path.TrimEnd('\')
if (-not (Test-Path (Join-Path $Target '.env'))) { throw "No .env in $Target - is that the install folder?" }
if (-not (Test-IsAdmin)) {
    Write-Host 'Run this from an Administrator PowerShell (right-click PowerShell > Run as administrator).' -ForegroundColor Yellow
    exit 1
}
if (-not (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue)) {
    Write-Host "Task '$TaskName' is not registered. Run install.ps1 first." -ForegroundColor Yellow
    exit 1
}

Stop-Bridge $Target
if (-not (Test-BridgeConfig $Target)) {
    Write-Host ''
    Write-Host 'Config check FAILED (see the config error above). The listener is stopped.' -ForegroundColor Red
    Write-Host 'Fix .env (notepad .env), then run restart.ps1 again.' -ForegroundColor Red
    exit 2
}
Start-Bridge $Target 10
Write-Host 'Restarted.' -ForegroundColor Green
