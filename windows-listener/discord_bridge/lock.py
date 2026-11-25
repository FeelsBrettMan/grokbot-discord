"""Single-instance lock (Windows msvcrt / POSIX fcntl)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import IO


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
