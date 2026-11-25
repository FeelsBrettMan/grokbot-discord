<#
  Updates an existing install in place. Keeps .env, data\ (state.json) and logs\.
  1. Unzip the new discord-bridge-windows.zip somewhere (e.g. Downloads).
  2. In an *Administrator* PowerShell, from that unzipped discord-bridge folder:
       powershell -ExecutionPolicy Bypass -File .\update.ps1 -Target C:\discord-bridge
#>
param([Parameter(Mandatory = $true)][string]$Target)
$ErrorActionPreference = 'Stop'
$TaskName = 'DiscordGrokBridge'
$Source = $PSScriptRoot
$Target = (Resolve-Path $Target).Path
if ($Source -eq $Target) { throw 'Run update.ps1 from the NEW unzipped folder, not from the install folder.' }
if (-not (Test-Path (Join-Path $Target '.env'))) { throw "No .env in $Target - is that the install folder?" }

# 1. Stop the task and any listener running from the install folder.
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
}
Get-CimInstance Win32_Process |
    Where-Object { $_.CommandLine -and $_.CommandLine -like "*$Target*" -and $_.ProcessId -ne $PID } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 2

# 2. Replace code files only (never .env, data, logs, .venv).
$reqOld = Join-Path $Target 'requirements.txt'
$oldHash = if (Test-Path $reqOld) { (Get-FileHash $reqOld).Hash } else { '' }
Remove-Item -Recurse -Force (Join-Path $Target 'discord_bridge'), (Join-Path $Target 'tests') -ErrorAction SilentlyContinue
Copy-Item -Recurse -Force (Join-Path $Source 'discord_bridge'), (Join-Path $Source 'tests') $Target
foreach ($f in @('install.ps1', 'run.ps1', 'status.ps1', 'uninstall.ps1', 'update.ps1', 'requirements.txt',
                 'requirements-dev.txt', 'pyproject.toml', 'README.md', 'ROUTINE-PROMPT.md', 'LICENSE',
                 '.env.example')) {
    $p = Join-Path $Source $f
    if (Test-Path $p) { Copy-Item -Force $p $Target }
}
Get-ChildItem -Path $Target -Recurse -Directory -Filter __pycache__ | Remove-Item -Recurse -Force

# 3. Reinstall dependencies only if requirements changed (or the venv is missing).
$venvPy = Join-Path $Target '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPy)) { throw "Missing $venvPy - run install.ps1 in $Target instead." }
if ((Get-FileHash $reqOld).Hash -ne $oldHash) {
    Write-Output 'requirements changed: reinstalling dependencies'
    & $venvPy -m pip install --disable-pip-version-check -q -r $reqOld
    if ($LASTEXITCODE -ne 0) { throw 'pip install failed' }
}

# 4. Move .env off the old, larger payload defaults (secrets untouched).
$envPath = Join-Path $Target '.env'
$lines = [System.Collections.Generic.List[string]](Get-Content -Path $envPath)
$wanted = [ordered]@{ HISTORY_LIMIT = @('20', '12'); HISTORY_CHAR_CAP = @('8000', '3000');
                      HISTORY_ENTRY_CHAR_CAP = @($null, '600'); TEXT_CHAR_CAP = @($null, '4000') }
foreach ($k in $wanted.Keys) {
    $old, $new = $wanted[$k]
    $i = -1
    for ($j = 0; $j -lt $lines.Count; $j++) { if ($lines[$j] -match "^\s*$k\s*=") { $i = $j } }
    if ($i -lt 0) { $lines.Add("$k=$new") }
    elseif ($old -and ($lines[$i] -replace '^\s*[^=]+=\s*', '').Trim() -eq $old) { $lines[$i] = "$k=$new" }
}
Set-Content -Path $envPath -Value $lines -Encoding ASCII   # keeps the file's locked-down ACL

# 5. Check config, then restart.
Set-Location $Target
& $venvPy -m discord_bridge --check
if ($LASTEXITCODE -ne 0) { throw 'Config check failed - fix .env, then Start-ScheduledTask DiscordGrokBridge' }
Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Seconds 8
& (Join-Path $Target 'status.ps1')
