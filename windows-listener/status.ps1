# Shows whether the listener task/process is running and the last log lines.
Set-Location $PSScriptRoot
$t = Get-ScheduledTask -TaskName 'DiscordGrokBridge' -ErrorAction SilentlyContinue
if ($t) { Write-Host "Task: $($t.State)" } else { Write-Host 'Task: not registered' }
. (Join-Path $PSScriptRoot 'common.ps1')
$procs = @(Get-BridgeProcesses $PSScriptRoot | Where-Object { $_.Name -eq 'python.exe' })
if ($procs.Count) { $procs | ForEach-Object { Write-Host "Running: PID $($_.ProcessId) (parent $($_.ParentProcessId))" } }
else { Write-Host 'Running: no' }
if (Test-Path logs\bridge.log) { Write-Host '--- last log lines ---'; Get-Content logs\bridge.log -Tail 15 }
