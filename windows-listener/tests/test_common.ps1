# Checks which processes restart/update/uninstall would stop (mocked process list).
# Run: powershell -ExecutionPolicy Bypass -File tests\test_common.ps1   (exit 0 = pass)
. (Join-Path $PSScriptRoot "..\common.ps1")
$me = [uint32]$PID
function Get-CimInstance { @(
  [pscustomobject]@{ProcessId=[uint32]1; ParentProcessId=[uint32]0; Name='explorer.exe'; CommandLine='explorer'; ExecutablePath='C:\Windows\explorer.exe'},
  [pscustomobject]@{ProcessId=[uint32]50; ParentProcessId=[uint32]1; Name='powershell.exe'; CommandLine='powershell -File C:\discord-bridge\restart.ps1 x'; ExecutablePath='C:\W\powershell.exe'},
  [pscustomobject]@{ProcessId=$me; ParentProcessId=[uint32]50; Name='pwsh'; CommandLine='pwsh C:\discord-bridge\restart.ps1'; ExecutablePath='x'},
  [pscustomobject]@{ProcessId=[uint32]10; ParentProcessId=[uint32]9; Name='powershell.exe'; CommandLine='powershell -File "C:\discord-bridge\run.ps1"'; ExecutablePath='C:\W\powershell.exe'},
  [pscustomobject]@{ProcessId=[uint32]11; ParentProcessId=[uint32]10; Name='python.exe'; CommandLine='"C:\discord-bridge\.venv\Scripts\python.exe" -m discord_bridge'; ExecutablePath='C:\discord-bridge\.venv\Scripts\python.exe'},
  [pscustomobject]@{ProcessId=[uint32]12; ParentProcessId=[uint32]11; Name='python.exe'; CommandLine='"C:\Python312\python.exe" -m discord_bridge'; ExecutablePath='C:\Python312\python.exe'},
  [pscustomobject]@{ProcessId=[uint32]20; ParentProcessId=[uint32]1; Name='python.exe'; CommandLine='C:\discord-bridge-other\x.py'; ExecutablePath='C:\Python312\python.exe'}
)}
$r = (Get-BridgeProcesses 'C:\discord-bridge' | ForEach-Object ProcessId) -join ','
"matched: $r"; if ($r -ne '10,11,12') { exit 1 }
"PASS"
