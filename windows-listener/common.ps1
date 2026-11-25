<#
  Shared helpers for restart.ps1 and update.ps1 (dot-source: . .\common.ps1).
#>
$TaskName = 'DiscordGrokBridge'

function Test-IsAdmin {
    ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
    ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

# Every process started from the install folder (run.ps1's powershell, the venv
# python.exe and the base python it launches), plus all their descendants.
# Never includes this script ($PID) or its parent shells.
function Get-BridgeProcesses([string]$Target) {
    $dir = $Target.TrimEnd('\') + '\'
    $all = @(Get-CimInstance Win32_Process)
    # never touch this script or the shells that started it
    $skip = New-Object 'System.Collections.Generic.HashSet[uint32]'
    $cur = [uint32]$PID
    while ($cur -and $skip.Add($cur)) {
        $parent = $all | Where-Object { $_.ProcessId -eq $cur } | Select-Object -First 1
        if (-not $parent) { break }
        $cur = [uint32]$parent.ParentProcessId
    }
    $ids = New-Object 'System.Collections.Generic.HashSet[uint32]'
    foreach ($p in $all) {
        if ($skip.Contains($p.ProcessId)) { continue }
        if (($p.CommandLine -and $p.CommandLine -like "*$dir*") -or
            ($p.ExecutablePath -and $p.ExecutablePath -like "$dir*")) { [void]$ids.Add($p.ProcessId) }
    }
    do {
        $added = $false
        foreach ($p in $all) {
            if (-not $skip.Contains($p.ProcessId) -and -not $ids.Contains($p.ProcessId) -and $ids.Contains($p.ParentProcessId)) {
                [void]$ids.Add($p.ProcessId); $added = $true
            }
        }
    } while ($added)
    return @($all | Where-Object { $ids.Contains($_.ProcessId) })
}

# Stop the scheduled task and kill every listener process from the install folder.
function Stop-Bridge([string]$Target) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    }
    $killed = 0
    foreach ($round in 1..3) {
        $procs = Get-BridgeProcesses $Target
        if ($procs.Count -eq 0) { break }
        foreach ($p in $procs) {
            Write-Output ("stopping PID {0} ({1})" -f $p.ProcessId, $p.Name)
            Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
            $killed++
        }
        Start-Sleep -Seconds 2
    }
    $left = Get-BridgeProcesses $Target
    if ($left.Count -gt 0) {
        throw ("Could not stop PID(s) {0}. Run this from an Administrator PowerShell." -f
               (($left | ForEach-Object { $_.ProcessId }) -join ', '))
    }
    if ($killed -eq 0) { Write-Output 'no listener process was running' }
}

# Same check install.ps1 / update.ps1 use. Returns $true if .env is valid.
function Test-BridgeConfig([string]$Target) {
    $venvPy = Join-Path $Target '.venv\Scripts\python.exe'
    if (-not (Test-Path $venvPy)) { throw "Missing $venvPy - run install.ps1 in $Target first." }
    Push-Location $Target
    try { & $venvPy -m discord_bridge --check; return ($LASTEXITCODE -eq 0) }
    finally { Pop-Location }
}

function Start-Bridge([string]$Target, [int]$WaitSeconds = 10) {
    Start-ScheduledTask -TaskName $TaskName
    Write-Output "task started; waiting $WaitSeconds s for the listener to log in..."
    Start-Sleep -Seconds $WaitSeconds
    $t = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($t) { Write-Output "Task: $($t.State)" }
    $py = @(Get-BridgeProcesses $Target | Where-Object { $_.Name -eq 'python.exe' })
    Write-Output ("Listener python processes: {0} (venv launcher + interpreter = 2 is normal)" -f $py.Count)
    $log = Join-Path $Target 'logs\bridge.log'
    if (Test-Path $log) { Write-Output '--- last log lines ---'; Get-Content $log -Tail 10 }
}
