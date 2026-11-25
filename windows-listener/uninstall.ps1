<#
  Stops the listener and removes the scheduled task (Administrator PowerShell).
      powershell -ExecutionPolicy Bypass -File .\uninstall.ps1          # keep files
      powershell -ExecutionPolicy Bypass -File .\uninstall.ps1 -Purge   # also delete venv, data, logs, .env
#>
param([switch]$Purge)
Set-Location $PSScriptRoot
$TaskName = 'DiscordGrokBridge'
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed task $TaskName"
}
Get-CimInstance Win32_Process |
    Where-Object { $_.CommandLine -and $_.CommandLine -like "*$PSScriptRoot*" -and $_.ProcessId -ne $PID } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
                     Write-Host "Stopped PID $($_.ProcessId)" }
if ($Purge) {
    Remove-Item -Recurse -Force .venv, data, logs -ErrorAction SilentlyContinue
    Remove-Item -Force .env -ErrorAction SilentlyContinue
    Write-Host 'Deleted .venv, data, logs and .env'
}
Write-Host 'Uninstalled.'
