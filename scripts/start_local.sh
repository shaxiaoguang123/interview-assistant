#!/bin/bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/local_common.sh"
aia_check_macos
aia_resolve_runtime_python
aia_resolve_data_dir

AIA_PORT="${APP_PORT:-5000}"
case "$AIA_PORT" in
  ''|*[!0-9]*) aia_fail "APP_PORT 必须是数字。"; exit 1 ;;
esac
if [ "$AIA_PORT" -lt 1 ] || [ "$AIA_PORT" -gt 65535 ]; then
  aia_fail "APP_PORT 必须在 1 到 65535 之间。"
  exit 1
fi
APP_PORT="$AIA_PORT"
export APP_PORT

if [ ! -f "$AIA_FRONTEND/dist/index.html" ]; then
  aia_fail "尚未构建前端。请先双击“Set up Agent Interview Assistant.command”。"
  exit 1
fi

AIA_MANAGER_DIR="$AIA_DATA_DIR/.launcher"
if [ -L "$AIA_MANAGER_DIR" ]; then
  aia_fail "本机启动状态目录不能是符号链接。"
  exit 1
fi
mkdir -p "$AIA_MANAGER_DIR"
chmod 700 "$AIA_MANAGER_DIR" 2>/dev/null || true
AIA_PID_FILE="$AIA_MANAGER_DIR/launcher.pid"
AIA_TOKEN_FILE="$AIA_MANAGER_DIR/launcher.token"
AIA_PORT_FILE="$AIA_MANAGER_DIR/launcher.port"
AIA_LOG_FILE="$AIA_MANAGER_DIR/server.log"
AIA_SERVICE_LOCK="$AIA_DATA_DIR/.agent-interview-assistant.pid"
AIA_URL="http://127.0.0.1:$AIA_PORT/"

aia_is_this_app_at_port() {
  local body
  body=$(curl -fsS --connect-timeout 1 --max-time 3 "http://127.0.0.1:$1/api/v1/system/status" 2>/dev/null || true)
  printf '%s' "$body" | grep -Eq '"application"[[:space:]]*:[[:space:]]*"agent-interview-assistant"'
}

aia_open_app() {
  local port="$1"
  printf 'Agent Interview Assistant 已在本机运行：http://127.0.0.1:%s/\n' "$port"
  if [ "${AIA_NO_BROWSER:-0}" != "1" ]; then
    open "http://127.0.0.1:$port/" || printf '浏览器未能自动打开；请复制上方本机地址。\n'
  fi
}

aia_wait_existing() {
  local port="$1" count=0
  while [ "$count" -lt 60 ]; do
    if aia_is_this_app_at_port "$port"; then
      aia_open_app "$port"
      return 0
    fi
    sleep 1
    count=$((count + 1))
  done
  return 1
}

if aia_is_this_app_at_port "$AIA_PORT"; then
  aia_open_app "$AIA_PORT"
  exit 0
fi

if [ -f "$AIA_SERVICE_LOCK" ]; then
  AIA_SERVICE_PID="$(cat "$AIA_SERVICE_LOCK" 2>/dev/null || true)"
  case "$AIA_SERVICE_PID" in
    ''|*[!0-9]*) AIA_SERVICE_PID="" ;;
  esac
  if [ -n "$AIA_SERVICE_PID" ] && kill -0 "$AIA_SERVICE_PID" 2>/dev/null; then
    AIA_MANAGED_PID="$(cat "$AIA_PID_FILE" 2>/dev/null || true)"
    AIA_MANAGED_PORT="$(cat "$AIA_PORT_FILE" 2>/dev/null || printf '%s' "$AIA_PORT")"
    if [ "$AIA_MANAGED_PID" = "$AIA_SERVICE_PID" ]; then
      if aia_wait_existing "$AIA_MANAGED_PORT"; then exit 0; fi
      printf '服务进程仍在启动或读取数据。没有再次启动或终止进程。\n日志位置：%s\n' "$AIA_LOG_FILE" >&2
      exit 1
    fi
    printf '数据目录正被另一个 Agent Interview Assistant 进程使用（PID %s）。为避免重复服务，没有启动新进程。\n' "$AIA_SERVICE_PID" >&2
    printf '请在原启动窗口检查服务，或先停止该服务后再重试。\n' >&2
    exit 1
  fi
fi

if [ -n "$(lsof -nP -iTCP:"$AIA_PORT" -sTCP:LISTEN 2>/dev/null || true)" ]; then
  aia_fail "本机端口 $AIA_PORT 已被其他应用占用。请关闭占用程序，或用 APP_PORT 指定其他端口后重试。"
  exit 1
fi

AIA_START_LOCK="$AIA_MANAGER_DIR/start.lock"
if ! mkdir "$AIA_START_LOCK" 2>/dev/null; then
  if aia_wait_existing "$AIA_PORT"; then exit 0; fi
  aia_fail "另一个启动操作仍在进行；没有创建第二个服务进程。请稍后重试。"
  exit 1
fi
trap 'rmdir "$AIA_START_LOCK" 2>/dev/null || true' EXIT

# Recheck after acquiring the launcher lock so two clicks cannot race into startup.
if aia_is_this_app_at_port "$AIA_PORT"; then
  aia_open_app "$AIA_PORT"
  exit 0
fi

printf '正在检查并初始化数据库…\n'
(cd "$AIA_BACKEND" && "$AIA_PYTHON" -m app.maintenance upgrade)

AIA_TOKEN=$("$AIA_PYTHON" -c 'import secrets; print(secrets.token_hex(16))')
umask 077
printf '正在启动本机服务…\n'
cd "$AIA_BACKEND"
export APP_DATA_DIR APP_PORT
export PYTHONPATH="$AIA_BACKEND${PYTHONPATH:+:$PYTHONPATH}"
AIA_STARTED_PID=$("$AIA_PYTHON" -m app.maintenance.launcher --launcher-token "$AIA_TOKEN" --log-file "$AIA_LOG_FILE")
printf '%s\n' "$AIA_STARTED_PID" > "$AIA_PID_FILE.tmp"
printf '%s\n' "$AIA_TOKEN" > "$AIA_TOKEN_FILE.tmp"
printf '%s\n' "$AIA_PORT" > "$AIA_PORT_FILE.tmp"
mv "$AIA_PID_FILE.tmp" "$AIA_PID_FILE"
mv "$AIA_TOKEN_FILE.tmp" "$AIA_TOKEN_FILE"
mv "$AIA_PORT_FILE.tmp" "$AIA_PORT_FILE"
chmod 600 "$AIA_PID_FILE" "$AIA_TOKEN_FILE" "$AIA_PORT_FILE"

AIA_COUNT=0
while [ "$AIA_COUNT" -lt 90 ]; do
  if aia_is_this_app_at_port "$AIA_PORT"; then
    aia_open_app "$AIA_PORT"
    exit 0
  fi
  if ! kill -0 "$AIA_STARTED_PID" 2>/dev/null; then
    printf '服务启动失败。最近日志：\n' >&2
    tail -n 30 "$AIA_LOG_FILE" 2>/dev/null || true
    exit 1
  fi
  sleep 1
  AIA_COUNT=$((AIA_COUNT + 1))
done

printf '服务仍在启动，已保留进程与数据。稍后再次双击启动器会连接现有进程。\n' >&2
printf '本机地址：http://127.0.0.1:%s/\n日志位置：%s\n' "$AIA_PORT" "$AIA_LOG_FILE"
exit 1
