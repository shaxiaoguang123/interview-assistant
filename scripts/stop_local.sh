#!/bin/bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/local_common.sh"
aia_check_macos
aia_resolve_runtime_python
aia_resolve_data_dir

AIA_MANAGER_DIR="$AIA_DATA_DIR/.launcher"
AIA_PID_FILE="$AIA_MANAGER_DIR/launcher.pid"
AIA_TOKEN_FILE="$AIA_MANAGER_DIR/launcher.token"
AIA_PORT_FILE="$AIA_MANAGER_DIR/launcher.port"
AIA_SERVICE_LOCK="$AIA_DATA_DIR/.agent-interview-assistant.pid"

if [ ! -f "$AIA_PID_FILE" ] || [ ! -f "$AIA_TOKEN_FILE" ]; then
  printf '没有由本机启动器登记的服务进程。用户数据未修改。\n'
  exit 0
fi

AIA_PID="$(cat "$AIA_PID_FILE" 2>/dev/null || true)"
AIA_TOKEN="$(cat "$AIA_TOKEN_FILE" 2>/dev/null || true)"
case "$AIA_PID" in
  ''|*[!0-9]*) aia_fail "启动器进程标记无效，未发送停止信号。"; exit 1 ;;
esac

if ! kill -0 "$AIA_PID" 2>/dev/null; then
  rm -f "$AIA_PID_FILE" "$AIA_TOKEN_FILE" "$AIA_PORT_FILE"
  printf '服务已停止；已移除过期的启动器标记。数据、配置和日志均保留。\n'
  exit 0
fi

AIA_COMMAND="$(ps -p "$AIA_PID" -o command= 2>/dev/null || true)"
case "$AIA_COMMAND" in
  *"$AIA_BACKEND/run.py"*) ;;
  *) aia_fail "进程身份与本机应用不符；为避免误停其他程序，没有发送停止信号。"; exit 1 ;;
esac
case "$AIA_COMMAND" in
  *"--launcher-token=$AIA_TOKEN"*) ;;
  *) aia_fail "进程不是由当前启动器创建；为避免误停其他程序，没有发送停止信号。"; exit 1 ;;
esac

if [ -f "$AIA_SERVICE_LOCK" ]; then
  AIA_LOCK_PID="$(cat "$AIA_SERVICE_LOCK" 2>/dev/null || true)"
  if [ -n "$AIA_LOCK_PID" ] && [ "$AIA_LOCK_PID" != "$AIA_PID" ]; then
    aia_fail "数据目录当前由另一个进程持有；为避免影响数据，没有发送停止信号。"
    exit 1
  fi
fi

printf '正在请求服务正常关闭（PID %s）…\n' "$AIA_PID"
kill -TERM "$AIA_PID"
AIA_COUNT=0
while [ "$AIA_COUNT" -lt 30 ]; do
  if ! kill -0 "$AIA_PID" 2>/dev/null; then
    rm -f "$AIA_PID_FILE" "$AIA_TOKEN_FILE" "$AIA_PORT_FILE"
    printf '服务已正常停止。数据库、截图、资料、配置和 OCR 模型均保留。\n'
    exit 0
  fi
  sleep 1
  AIA_COUNT=$((AIA_COUNT + 1))
done

printf '服务尚未退出；没有强制终止。请稍后检查运行窗口或日志，数据未清理。\n' >&2
exit 1
