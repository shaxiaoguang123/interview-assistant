from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from app.services.backups import BackupError, inspect_backup, restore_backup


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.maintenance",
        description="离线检查或恢复 Agent Interview Assistant 本地备份。",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("inspect", help="校验备份 ZIP 与数据库引用")
    inspect.add_argument("--backup", required=True, type=Path)
    restore = commands.add_parser("restore", help="将备份恢复到一个 APP_DATA_DIR")
    restore.add_argument("--backup", required=True, type=Path)
    restore.add_argument("--target", required=True, type=Path)
    restore.add_argument("--replace-existing", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "inspect":
            result = inspect_backup(args.backup)
        else:
            confirmed = False
            if args.replace_existing:
                expected = f"RESTORE {args.target.expanduser()}"
                print(f"现有目录会先保留为可恢复副本。若确认替换，请输入：{expected}")
                try:
                    confirmed = input("> ").strip() == expected
                except EOFError:
                    confirmed = False
                if not confirmed:
                    print("已取消恢复；现有数据未修改。", file=sys.stderr)
                    return 2
            result = restore_backup(
                args.backup,
                args.target,
                replace_existing=args.replace_existing,
                confirmed=confirmed,
            )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except BackupError as error:
        print(f"恢复未执行：{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
