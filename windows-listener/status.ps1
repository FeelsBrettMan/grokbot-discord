# Shows whether the listener task/process is running and the last log lines.
Set-Location $PSScriptRoot
$t = Get-ScheduledTask -TaskName 'DiscordGrokBridge' -ErrorAction SilentlyContinue
if ($t) { Write-Host "Task: $($t.State)" } else { Write-Host 'Task: not registered' }
$procs = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -like '*discord_bridge*' -and $_.ExecutablePath -like "$PSScriptRoot*" }
if ($procs) { $procs | ForEach-Object { Write-Host "Running: PID $($_.ProcessId)" } }
else { Write-Host 'Running: no' }
if (Test-Path logs\bridge.log) { Write-Host '--- last log lines ---'; Get-Content logs\bridge.log -Tail 15 }
