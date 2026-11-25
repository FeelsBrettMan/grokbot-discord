<#
  Installs the Discord -> Grok Bot listener and registers an auto-start task.
  Run from an *Administrator* PowerShell in the unzipped folder:
      powershell -ExecutionPolicy Bypass -File .\install.ps1
  Options:  -NoTask   (only set up Python; don't register the scheduled task)
#>
param([switch]$NoTask)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$TaskName = 'DiscordGrokBridge'   # also set in common.ps1

function Find-Python {
    foreach ($c in @(@('py', '-3.13'), @('py', '-3.12'), @('py', '-3'), @('python'))) {
        try {
            $exe = $c[0]; $args2 = @($c | Select-Object -Skip 1)
            $v = & $exe @args2 -c "import sys;print('%d.%d'%sys.version_info[:2])" 2>$null
            if ($LASTEXITCODE -eq 0 -and $v) {
                $maj, $min = $v.Trim().Split('.')
                if ([int]$maj -eq 3 -and [int]$min -ge 12) { return ,$c }
            }
        } catch { }
    }
    return $null
}

$py = Find-Python
if (-not $py) {
    Write-Host 'Python 3.12+ not found. Install it, open a NEW PowerShell, and re-run:' -ForegroundColor Yellow
    Write-Host '    winget install -e --id Python.Python.3.12 --scope machine'
    exit 1
}
Write-Host "Using Python: $($py -join ' ')"

if (-not (Test-Path .venv\Scripts\python.exe)) {
    & $py[0] @($py | Select-Object -Skip 1) -m venv .venv
}
$venvPy = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
& $venvPy -m pip install --disable-pip-version-check -q --upgrade pip
& $venvPy -m pip install --disable-pip-version-check -q -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'pip install failed' }

New-Item -ItemType Directory -Force -Path data, logs | Out-Null
if (-not (Test-Path .env)) {
    Copy-Item .env.example .env
    Write-Host 'Created .env from .env.example.' -ForegroundColor Yellow
}
# Lock .env down to you, SYSTEM and Administrators.
$me = "$env:USERDOMAIN\$env:USERNAME"
icacls .env /inheritance:r /grant:r "${me}:(M)" 'SYSTEM:(F)' '*S-1-5-32-544:(F)' | Out-Null

& $venvPy -m discord_bridge --check
if ($LASTEXITCODE -ne 0) {
    Write-Host ''
    Write-Host 'Config not ready. Open .env (notepad .env), replace the two "changeme"' -ForegroundColor Yellow
    Write-Host 'values (bot token, webhook key), save, then run install.ps1 again.' -ForegroundColor Yellow
    exit 2
}

if ($NoTask) { Write-Host 'Done (no task). Start manually with: .\run.ps1'; exit 0 }

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
    ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host 'Registering the auto-start task needs an Administrator PowerShell. Re-run there.' -ForegroundColor Yellow
    exit 3
}

# Re-install: stop any listener already running from this folder first.
. (Join-Path $PSScriptRoot 'common.ps1')
Stop-Bridge $PSScriptRoot

$run = Join-Path $PSScriptRoot 'run.ps1'
$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$run`"" `
    -WorkingDirectory $PSScriptRoot
$atBoot = New-ScheduledTaskTrigger -AtStartup
# Watchdog: every 5 minutes; IgnoreNew means it only starts the bridge if it is not running.
$watchdog = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 5)
# S4U = runs whether or not you are logged in, without storing your password.
$principal = New-ScheduledTaskPrincipal -UserId $me -LogonType S4U -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $atBoot, $watchdog `
    -Principal $principal -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Seconds 8
Write-Host "Task '$TaskName' registered and started." -ForegroundColor Green
& (Join-Path $PSScriptRoot 'status.ps1')
