from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys
from uuid import uuid4

from alembic import command
from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from sqlalchemy.engine import make_url

from app import create_app
from app.config import Config, default_data_dir
from app.maintenance.service_lock import claim_service_lock
from app.services.backups import BackupError, inspect_backup, restore_backup
from app.services.system_status import get_system_status


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
    doctor = commands.add_parser("doctor", help="检查运行环境、数据库、OCR 和模型配置")
    doctor.add_argument("--json", action="store_true", help="以 JSON 输出诊断结果")
    commands.add_parser("upgrade", help="安全初始化或升级本机数据库")
    return parser


def _backend_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _alembic_config(database_url: str) -> AlembicConfig:
    backend_root = _backend_root()
    config = AlembicConfig(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def _migration_state(database_url: str) -> tuple[Path | None, list[str], list[str], list[str]]:
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite" or url.database in (None, ":memory:"):
        raise RuntimeError("本地启动器只支持文件型 SQLite 数据库升级。")
    database_path = Path(url.database).expanduser().resolve()
    config = _alembic_config(database_url)
    script = ScriptDirectory.from_config(config)
    heads = script.get_heads()
    if not database_path.exists():
        return database_path, [], [], heads
    try:
        with sqlite3.connect(database_path) as connection:
            tables = [
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
            ]
            has_version_table = "alembic_version" in tables
            current = (
                sorted(row[0] for row in connection.execute("SELECT version_num FROM alembic_version"))
                if has_version_table
                else []
            )
    except sqlite3.DatabaseError as error:
        raise RuntimeError("SQLite 文件无法读取；为避免覆盖数据，未执行数据库升级。") from error
    return database_path, tables, current, heads


def _snapshot_sqlite(database_path: Path, data_dir: Path) -> Path:
    backup_dir = data_dir / "migration-backups"
    backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        backup_dir.chmod(0o700)
    except OSError:
        pass
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = backup_dir / f"interview-assistant-before-upgrade-{stamp}-{uuid4().hex[:8]}.sqlite3"
    source_connection = destination_connection = None
    try:
        source_connection = sqlite3.connect(database_path, timeout=30)
        destination_connection = sqlite3.connect(destination, timeout=30)
        source_connection.backup(destination_connection)
        integrity = destination_connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError("升级前 SQLite 快照完整性检查失败。")
        destination_connection.close()
        destination_connection = None
        destination.chmod(0o600)
        return destination
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    finally:
        if source_connection is not None:
            source_connection.close()
        if destination_connection is not None:
            destination_connection.close()


def _run_doctor(as_json: bool) -> int:
    app = create_app({"SEED_TOPICS_ON_STARTUP": False})
    try:
        with app.app_context():
            result = {
                "runtime": get_system_status(app),
                "frontend": {
                    "ready": (Path(app.config["FRONTEND_DIST_DIR"]) / "index.html").is_file(),
                },
            }
        if as_json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            status = result["runtime"]
            print("Agent Interview Assistant 本机运行诊断")
            print(f"Python：{status['python']['version']}（{'支持' if status['python']['supported'] else '需要 Python 3.12'}）")
            database = status["database"]
            print(f"数据库：{database['state']}；当前 {database['current_revision'] or '未初始化'}；目标 {database['latest_revision']}")
            print(f"前端构建：{'就绪' if result['frontend']['ready'] else '缺少 frontend/dist，请运行本机安装脚本'}")
            print(f"OCR：{status['ocr']['message']}")
            print(f"LLM Provider：{'已配置' if status['llm']['configured'] else '未配置（可跳过）'}")
            print(f"数据目录：{'默认位置' if status['storage']['location'] == 'default' else '自定义位置'}")
        return 0 if (
            result["runtime"]["python"]["supported"]
            and result["frontend"]["ready"]
            and result["runtime"]["database"]["ready"]
        ) else 1
    finally:
        app.extensions["sqlalchemy_engine"].dispose()


def _run_upgrade() -> int:
    data_dir = Path(default_data_dir()).expanduser().resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    database_url = Config.DATABASE_URL
    database_path, tables, current, heads = _migration_state(database_url)
    assert database_path is not None
    if current and set(current) == set(heads):
        print(f"数据库已是最新版本（{current[0] if len(current) == 1 else ', '.join(current)}）。")
        return 0
    if not current and tables:
        raise RuntimeError("数据库包含未标记版本的表。为避免改写历史数据，请先检查数据库；未执行升级。")
    existing_database = bool(current and tables)
    if existing_database:
        current_label = ", ".join(current)
        target_label = ", ".join(heads)
        expected = f"UPGRADE {current_label} TO {target_label}"
        print(f"现有数据库需要从 {current_label} 升级到 {target_label}。")
        print("继续前会使用 SQLite Online Backup API 创建数据库快照；资料和截图文件不会被修改。")
        print(f"若确认，请输入：{expected}")
        try:
            confirmed = input("> ").strip() == expected
        except EOFError:
            confirmed = False
        if not confirmed:
            print("已取消升级；现有数据未修改。", file=sys.stderr)
            return 2

    config = _alembic_config(database_url)
    with claim_service_lock(data_dir):
        if existing_database:
            snapshot = _snapshot_sqlite(database_path, data_dir)
            print(f"已创建升级前数据库快照：{snapshot}")
        command.upgrade(config, "head")
    print("数据库初始化/升级完成。")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "inspect":
            result = inspect_backup(args.backup)
        elif args.command == "doctor":
            return _run_doctor(args.json)
        elif args.command == "upgrade":
            return _run_upgrade()
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
    except Exception as error:
        print(f"本机维护操作未完成：{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
