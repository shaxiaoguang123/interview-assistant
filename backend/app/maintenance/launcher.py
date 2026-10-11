"""Spawn the supported Flask runner outside the launcher's terminal session."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Start the local Flask process in a detached session.")
    parser.add_argument("--launcher-token", required=True)
    parser.add_argument("--log-file", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    backend_root = Path(__file__).resolve().parents[2]
    args.log_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    args.log_file.parent.chmod(0o700)
    descriptor = os.open(args.log_file, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "ab", buffering=0) as log:
        process = subprocess.Popen(
            [sys.executable, str(backend_root / "run.py"), f"--launcher-token={args.launcher_token}"],
            cwd=backend_root,
            env=os.environ.copy(),
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            close_fds=True,
            start_new_session=True,
        )
    print(process.pid)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
