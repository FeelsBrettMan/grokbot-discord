<#
  Updates an existing install in place. Keeps .env, data\ (state.json) and logs\.
  1. Unzip the new discord-bridge-windows.zip somewhere (e.g. Downloads).
  2. In an *Administrator* PowerShell, from that unzipped discord-bridge folder:
       powershell -ExecutionPolicy Bypass -File .\update.ps1 -Target C:\discord-bridge
#>
param([Parameter(Mandatory = $true)][string]$Target)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')
$Source = $PSScriptRoot
$Target = (Resolve-Path $Target).Path.TrimEnd('\')
if ($Source -eq $Target) { throw 'Run update.ps1 from the NEW unzipped folder, not from the install folder.' }
if (-not (Test-Path (Join-Path $Target '.env'))) { throw "No .env in $Target - is that the install folder?" }
if (-not (Test-IsAdmin)) { throw 'Run update.ps1 from an Administrator PowerShell.' }

# 1. Stop the task and any listener running from the install folder.
Stop-Bridge $Target

# 2. Replace code files only (never .env, data, logs, .venv).
$reqOld = Join-Path $Target 'requirements.txt'
$oldHash = if (Test-Path $reqOld) { (Get-FileHash $reqOld).Hash } else { '' }
Remove-Item -Recurse -Force (Join-Path $Target 'discord_bridge'), (Join-Path $Target 'tests') -ErrorAction SilentlyContinue
Copy-Item -Recurse -Force (Join-Path $Source 'discord_bridge'), (Join-Path $Source 'tests') $Target
foreach ($f in @('install.ps1', 'run.ps1', 'status.ps1', 'uninstall.ps1', 'update.ps1', 'restart.ps1',
                 'common.ps1', 'requirements.txt',
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

# 4. Migrate .env (secrets untouched):
#    - DISCORD_AUTHOR_ALLOWLIST (deprecated) -> DISCORD_TRUSTED_AUTHORS
#    - add DISCORD_CHAT_AUTHORS= (empty) if missing
#    - move old default size limits to the new ones; add new caps if missing
$envPath = Join-Path $Target '.env'
$lines = [System.Collections.Generic.List[string]](Get-Content -Path $envPath)
function Find-Key($name) {
    $i = -1
    for ($j = 0; $j -lt $lines.Count; $j++) { if ($lines[$j] -match "^\s*$name\s*=") { $i = $j } }
    return $i
}
$legacy = Find-Key 'DISCORD_AUTHOR_ALLOWLIST'
$trusted = Find-Key 'DISCORD_TRUSTED_AUTHORS'
if ($legacy -ge 0) {
    $value = ($lines[$legacy] -replace '^\s*[^=]+=\s*', '').Trim()
    if ($trusted -lt 0) {
        $lines[$legacy] = "DISCORD_TRUSTED_AUTHORS=$value"
        Write-Output 'migrated DISCORD_AUTHOR_ALLOWLIST -> DISCORD_TRUSTED_AUTHORS'
    } else {
        $lines[$legacy] = "# deprecated, merged into DISCORD_TRUSTED_AUTHORS: DISCORD_AUTHOR_ALLOWLIST=$value"
    }
}
$wanted = [ordered]@{ HISTORY_LIMIT = @('20', '12'); HISTORY_CHAR_CAP = @('8000', '3000');
                      HISTORY_ENTRY_CHAR_CAP = @($null, '600'); MESSAGE_CHAR_CAP = @($null, '1500');
                      BATCH_CHAR_CAP = @($null, '4000'); DISCORD_CHAT_AUTHORS = @($null, '') }
foreach ($k in $wanted.Keys) {
    $old, $new = $wanted[$k]
    $i = Find-Key $k
    if ($i -lt 0) { $lines.Add("$k=$new") }
    elseif ($old -and ($lines[$i] -replace '^\s*[^=]+=\s*', '').Trim() -eq $old) { $lines[$i] = "$k=$new" }
}
Set-Content -Path $envPath -Value $lines -Encoding ASCII   # keeps the file's locked-down ACL

# 5. Check config, then restart.
if (-not (Test-BridgeConfig $Target)) {
    throw 'Config check failed - fix .env, then run restart.ps1 in the install folder.'
}
Start-Bridge $Target 10
