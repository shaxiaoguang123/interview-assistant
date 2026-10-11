#!/bin/bash

AIA_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AIA_ROOT="$(cd "$AIA_SCRIPT_DIR/.." && pwd)"
AIA_BACKEND="$AIA_ROOT/backend"
AIA_FRONTEND="$AIA_ROOT/frontend"
AIA_VENV_PYTHON="$AIA_BACKEND/.venv/bin/python"

aia_fail() {
  printf 'Agent Interview Assistant：%s\n' "$1" >&2
  return 1
}

aia_resolve_setup_python() {
  local candidate version
  for candidate in python3.12 python3; do
    if ! command -v "$candidate" >/dev/null 2>&1; then
      continue
    fi
    version=$("$candidate" -c 'import sys; print("%s.%s" % sys.version_info[:2])' 2>/dev/null || true)
    if [ "$version" = "3.12" ]; then
      AIA_SETUP_PYTHON="$(command -v "$candidate")"
      return 0
    fi
  done
  aia_fail "首次安装需要 Python 3.12。可通过 Homebrew 安装：brew install python@3.12"
}

aia_resolve_runtime_python() {
  if [ ! -x "$AIA_VENV_PYTHON" ]; then
    aia_fail "尚未准备本机环境。请先双击“Set up Agent Interview Assistant.command”。"
    return 1
  fi
  local version
  version=$("$AIA_VENV_PYTHON" -c 'import sys; print("%s.%s" % sys.version_info[:2])' 2>/dev/null || true)
  if [ "$version" != "3.12" ]; then
    aia_fail "本机虚拟环境不是 Python 3.12；请检查 backend/.venv，未自动删除或重建环境。"
    return 1
  fi
  AIA_PYTHON="$AIA_VENV_PYTHON"
}

aia_resolve_data_dir() {
  local resolved
  if [ -n "${APP_DATA_DIR:-}" ]; then
    resolved=$("$AIA_PYTHON" -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).expanduser().resolve())' "$APP_DATA_DIR")
  else
    resolved=$(cd "$AIA_BACKEND" && "$AIA_PYTHON" -c 'from app.config import default_data_dir; print(default_data_dir().expanduser().resolve())')
  fi
  APP_DATA_DIR="$resolved"
  export APP_DATA_DIR
  AIA_DATA_DIR="$resolved"
}

aia_check_macos() {
  if [ "$(uname -s)" != "Darwin" ]; then
    aia_fail "此启动器面向 macOS；后端仍可按 README 中的本机开发方式运行。"
    return 1
  fi
}

aia_command_exists() {
  command -v "$1" >/dev/null 2>&1
}
