<#
  Runs the listener with an auto-restart loop. The scheduled task calls this;
  you can also run it by hand in a PowerShell window (Ctrl+C to stop).
  The python listener is put in a Windows Job object that is killed when this
  script ends (including Stop-ScheduledTask), and it also exits by itself if
  this script's process disappears (BRIDGE_PARENT_PID).
#>
$ErrorActionPreference = 'Continue'
Set-Location $PSScriptRoot
$env:PYTHONUNBUFFERED = '1'
$env:BRIDGE_PARENT_PID = "$PID"
$venvPy = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
New-Item -ItemType Directory -Force -Path logs | Out-Null
$sup = Join-Path $PSScriptRoot 'logs\supervisor.log'
function Note($m) { Add-Content -Path $sup -Value ("{0} {1}" -f (Get-Date -Format s), $m) }

# Job object with KILL_ON_JOB_CLOSE: when this powershell process dies, Windows
# closes the job handle and kills every process in the job.
$job = [IntPtr]::Zero
$selfInJob = $false
try {
    if (-not ('BridgeJob' -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class BridgeJob {
    [StructLayout(LayoutKind.Sequential)] struct BASIC {
        public long PerProcessUserTimeLimit; public long PerJobUserTimeLimit; public uint LimitFlags;
        public UIntPtr MinimumWorkingSetSize; public UIntPtr MaximumWorkingSetSize; public uint ActiveProcessLimit;
        public UIntPtr Affinity; public uint PriorityClass; public uint SchedulingClass; }
    [StructLayout(LayoutKind.Sequential)] struct IO {
        public ulong a; public ulong b; public ulong c; public ulong d; public ulong e; public ulong f; }
    [StructLayout(LayoutKind.Sequential)] struct EXTENDED {
        public BASIC Basic; public IO Io; public UIntPtr ProcessMemoryLimit; public UIntPtr JobMemoryLimit;
        public UIntPtr PeakProcessMemoryUsed; public UIntPtr PeakJobMemoryUsed; }
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    static extern IntPtr CreateJobObject(IntPtr attrs, string name);
    [DllImport("kernel32.dll", SetLastError = true)]
    static extern bool SetInformationJobObject(IntPtr job, int cls, IntPtr info, uint len);
    [DllImport("kernel32.dll", SetLastError = true)]
    static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);
    public static IntPtr Create() {
        IntPtr job = CreateJobObject(IntPtr.Zero, null);
        if (job == IntPtr.Zero) throw new System.ComponentModel.Win32Exception();
        EXTENDED info = new EXTENDED();
        info.Basic.LimitFlags = 0x2000; // JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        int len = Marshal.SizeOf(typeof(EXTENDED));
        IntPtr p = Marshal.AllocHGlobal(len);
        try {
            Marshal.StructureToPtr(info, p, false);
            if (!SetInformationJobObject(job, 9, p, (uint)len)) throw new System.ComponentModel.Win32Exception();
        } finally { Marshal.FreeHGlobal(p); }
        return job;
    }
    public static void Assign(IntPtr job, IntPtr process) {
        if (!AssignProcessToJobObject(job, process)) throw new System.ComponentModel.Win32Exception();
    }
}
'@
    }
    $job = [BridgeJob]::Create()
    # Put this script in the job too, so every child (venv launcher AND the base
    # python it starts) is born inside the job with no race.
    [BridgeJob]::Assign($job, [System.Diagnostics.Process]::GetCurrentProcess().Handle)
    $selfInJob = $true
} catch {
    Note "job object: $($_.Exception.Message); adding each listener to the job instead"
}

if (-not (Test-Path $venvPy)) { Note 'venv missing: run install.ps1'; exit 1 }
$delay = 10
while ($true) {
    Note "starting bridge (supervisor pid $PID)"
    $p = Start-Process -FilePath $venvPy -ArgumentList '-m', 'discord_bridge' `
        -WorkingDirectory $PSScriptRoot -NoNewWindow -PassThru
    $null = $p.Handle   # keeps ExitCode readable after exit
    if ($job -ne [IntPtr]::Zero -and -not $selfInJob) {
        try { [BridgeJob]::Assign($job, $p.Handle) }
        catch { Note "could not add listener to job: $($_.Exception.Message)" }
    }
    $p.WaitForExit()
    $rc = $p.ExitCode
    if ($rc -eq 2) { Note 'config error (see logs\bridge.log); not restarting'; exit 2 }
    if ($rc -eq 3) { Note 'another instance is already running; exiting'; exit 0 }
    Note "bridge exited rc=$rc; restarting in $delay s"
    Start-Sleep -Seconds $delay
    $delay = [Math]::Min($delay * 2, 300)
}
