<#
  Stops the listener and removes the scheduled task (Administrator PowerShell).
      powershell -ExecutionPolicy Bypass -File .\uninstall.ps1          # keep files
      powershell -ExecutionPolicy Bypass -File .\uninstall.ps1 -Purge   # also delete venv, data, logs, .env
#>
param([switch]$Purge)
Set-Location $PSScriptRoot
. (Join-Path $PSScriptRoot 'common.ps1')
Stop-Bridge $PSScriptRoot
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed task $TaskName"
}
if ($Purge) {
    Remove-Item -Recurse -Force .venv, data, logs -ErrorAction SilentlyContinue
    Remove-Item -Force .env -ErrorAction SilentlyContinue
    Write-Host 'Deleted .venv, data, logs and .env'
}
Write-Host 'Uninstalled.'
