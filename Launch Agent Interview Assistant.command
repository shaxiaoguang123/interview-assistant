#!/bin/bash
AIA_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
/bin/bash "$AIA_ROOT/scripts/start_local.sh"
AIA_EXIT=$?
printf '按回车关闭此窗口。'
read -r _
exit "$AIA_EXIT"
