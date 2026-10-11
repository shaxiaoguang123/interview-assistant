#!/bin/bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/local_common.sh"
aia_check_macos
aia_resolve_setup_python

if [ -x "$AIA_VENV_PYTHON" ]; then
  existing_version=$("$AIA_VENV_PYTHON" -c 'import sys; print("%s.%s" % sys.version_info[:2])' 2>/dev/null || true)
  if [ "$existing_version" != "3.12" ]; then
    aia_fail "已存在的 backend/.venv 不是 Python 3.12。为保护现有环境，没有覆盖它；请先自行备份后处理。"
    exit 1
  fi
else
  mkdir -p "$AIA_BACKEND"
  "$AIA_SETUP_PYTHON" -m venv "$AIA_BACKEND/.venv"
fi
AIA_PYTHON="$AIA_VENV_PYTHON"

if ! aia_command_exists npm || ! aia_command_exists node; then
  aia_fail "前端首次构建需要 Node.js 与 npm。可通过 Homebrew 安装：brew install node"
  exit 1
fi

printf '正在安装 Python 依赖…\n'
"$AIA_PYTHON" -m pip install -r "$AIA_BACKEND/requirements.txt"
printf '正在安装并构建前端…\n'
npm --prefix "$AIA_FRONTEND" ci
npm --prefix "$AIA_FRONTEND" run build

aia_resolve_data_dir
printf '正在检查数据库；首次安装会创建数据库，旧数据库升级前会要求确认并生成 SQLite 快照…\n'
(cd "$AIA_BACKEND" && "$AIA_PYTHON" -m app.maintenance upgrade)

printf '\n本机准备完成。之后双击“Launch Agent Interview Assistant.command”即可启动。\n\n'
(cd "$AIA_BACKEND" && "$AIA_PYTHON" -m app.maintenance doctor)
