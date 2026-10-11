"""Private local identity used to distinguish launcher-managed data directories."""
from __future__ import annotations

import hmac
import json
import os
from pathlib import Path
import re
import secrets
from typing import Any


_INSTANCE_ID_RE = re.compile(r"^[0-9a-f]{64}$")


def _read_instance_id(path: Path) -> str:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "r", encoding="ascii") as stream:
        value = stream.read(128).strip()
    if not _INSTANCE_ID_RE.fullmatch(value):
        raise RuntimeError("本机启动实例标识无效；未启动服务。")
    return value


def ensure_instance_id(data_dir: str | Path) -> str:
    """Read or safely create a stable, private identifier inside one APP_DATA_DIR."""
    root = Path(data_dir).expanduser().resolve()
    launcher_dir = root / ".launcher"
    if launcher_dir.is_symlink():
        raise RuntimeError("本机启动状态目录不能是符号链接。")
    launcher_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        launcher_dir.chmod(0o700)
    except OSError:
        pass

    path = launcher_dir / "instance-id"
    if path.is_symlink():
        raise RuntimeError("本机启动实例标识不能是符号链接。")
    if path.exists():
        return _read_instance_id(path)

    value = secrets.token_hex(32)
    temporary = launcher_dir / f".instance-id-{secrets.token_hex(8)}.tmp"
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="ascii") as stream:
            stream.write(value + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        try:
            # Publish only after the complete ID is durable. Competing launchers
            # link their own temp file; exactly one wins and all others read it.
            os.link(temporary, path, follow_symlinks=False)
        except FileExistsError:
            pass
    finally:
        temporary.unlink(missing_ok=True)
    return _read_instance_id(path)


def status_matches_instance(payload: str | dict[str, Any], expected_id: str) -> bool:
    """Return true only for this application's exact launcher identity."""
    if not isinstance(expected_id, str) or not _INSTANCE_ID_RE.fullmatch(expected_id):
        return False
    try:
        status = json.loads(payload) if isinstance(payload, str) else payload
    except (json.JSONDecodeError, TypeError):
        return False
    if not isinstance(status, dict) or status.get("application") != "agent-interview-assistant":
        return False
    launcher = status.get("launcher")
    actual_id = launcher.get("instance_id") if isinstance(launcher, dict) else None
    return isinstance(actual_id, str) and hmac.compare_digest(actual_id, expected_id)
