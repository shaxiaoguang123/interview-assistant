"""A small PID marker prevents offline restore while the supported server runs."""
from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path


LOCK_NAME = ".agent-interview-assistant.pid"


def marker_path(data_dir: str | Path) -> Path:
    return Path(data_dir).expanduser().resolve() / LOCK_NAME


def is_pid_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def running_service_pid(data_dir: str | Path) -> int | None:
    marker = marker_path(data_dir)
    if not marker.is_file():
        return None
    try:
        pid = int(marker.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return None
    return pid if is_pid_running(pid) else None


@contextmanager
def claim_service_lock(data_dir: str | Path):
    directory = Path(data_dir).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    marker = directory / LOCK_NAME
    previous = running_service_pid(directory)
    if previous is not None:
        raise RuntimeError(f"Agent Interview Assistant is already running (PID {previous}).")
    marker.unlink(missing_ok=True)
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    descriptor = os.open(marker, flags, 0o600)
    try:
        os.write(descriptor, str(os.getpid()).encode("ascii"))
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        yield marker
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            if marker.read_text(encoding="ascii").strip() == str(os.getpid()):
                marker.unlink(missing_ok=True)
        except OSError:
            pass
