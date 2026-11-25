"""Single-instance guards and parent watchdog.

- acquire(): per-folder lock file (Windows msvcrt / POSIX fcntl).
- acquire_mutex(): machine-wide named mutex on Windows, so two copies of the
  listener in *different* folders can't both run and double-forward.
- watch_parent(): exit when run.ps1 (the supervisor) dies, so stopping the
  scheduled task never leaves an orphaned listener behind.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path
from typing import IO, Any

log = logging.getLogger("discord_bridge")

MUTEX_NAME = "Global\\DiscordGrokBridgeListener"
_ERROR_ALREADY_EXISTS = 183
_SYNCHRONIZE = 0x00100000
_INFINITE = 0xFFFFFFFF


def acquire(path: Path) -> IO[str] | None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(path, "a+", encoding="utf-8")  # noqa: SIM115 - held for process lifetime
    try:
        if os.name == "nt":
            import msvcrt

            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return None
    return fh


def acquire_mutex(name: str = MUTEX_NAME) -> Any:
    """Return a handle (keep it alive), True on non-Windows, or None if taken."""
    if os.name != "nt":
        return True
    import ctypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateMutexW.restype = ctypes.c_void_p
    k32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    handle = k32.CreateMutexW(None, True, name)
    err = ctypes.get_last_error()
    if not handle:
        log.warning("could not create instance mutex (error %s); relying on lock file", err)
        return True
    if err == _ERROR_ALREADY_EXISTS:
        k32.CloseHandle(ctypes.c_void_p(handle))
        return None
    return handle


def _pid_alive_posix(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def watch_parent(pid: int | None, on_exit=None, poll_s: float = 2.0) -> threading.Thread | None:
    """Start a daemon thread that calls on_exit (default os._exit(0)) when pid dies."""
    if not pid or pid <= 0:
        return None
    on_exit = on_exit or (lambda: os._exit(0))

    if os.name == "nt":
        import ctypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = ctypes.c_void_p
        k32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_bool, ctypes.c_uint32]
        k32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        handle = k32.OpenProcess(_SYNCHRONIZE, False, pid)
        if not handle:
            log.warning("supervisor pid %s not found; exiting", pid)
            on_exit()
            return None

        def wait() -> None:
            k32.WaitForSingleObject(ctypes.c_void_p(handle), _INFINITE)
            log.warning("supervisor (run.ps1, pid %s) exited; stopping listener", pid)
            on_exit()
    else:

        def wait() -> None:
            while _pid_alive_posix(pid):
                time.sleep(poll_s)
            log.warning("supervisor pid %s exited; stopping listener", pid)
            on_exit()

    t = threading.Thread(target=wait, name="parent-watch", daemon=True)
    t.start()
    return t
