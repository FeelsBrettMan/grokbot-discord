import os
import subprocess
import sys
import threading
from pathlib import Path

from discord_bridge.lock import acquire, acquire_mutex, watch_parent

ROOT = str(Path(__file__).resolve().parents[1])
ENV = {**os.environ, "PYTHONPATH": ROOT}


def test_lock_file_single_instance(tmp_path):
    first = acquire(tmp_path / "bridge.lock")
    assert first is not None
    # a second process must not get the lock while the first holds it
    code = (
        "import sys; from pathlib import Path; from discord_bridge.lock import acquire; "
        f"sys.exit(0 if acquire(Path(r'{tmp_path / 'bridge.lock'}')) is None else 1)"
    )
    assert subprocess.run([sys.executable, "-c", code], env=ENV).returncode == 0
    first.close()
    assert subprocess.run([sys.executable, "-c", code], env=ENV).returncode == 1


def test_mutex_noop_off_windows():
    assert acquire_mutex() is True


def test_watch_parent_fires_when_parent_dies():
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(0.3)"])
    fired = threading.Event()
    t = watch_parent(child.pid, on_exit=fired.set, poll_s=0.05)
    assert t is not None
    child.wait()
    assert fired.wait(3)


def test_watch_parent_ignores_missing_pid():
    assert watch_parent(None) is None
    assert watch_parent(0) is None
