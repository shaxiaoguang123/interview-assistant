"""Validated, portable backups for the local SQLite database and evidence files."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import stat
import tempfile
from typing import Callable
import zipfile

from alembic import command
from alembic.config import Config
from flask import Flask
from sqlalchemy.engine import URL

from app.maintenance.service_lock import running_service_pid


APP_NAME = "Agent Interview Assistant"
APP_VERSION = "0.1.0"
BACKUP_FORMAT_VERSION = 1
MAX_ARCHIVE_BYTES = 8 * 1024 * 1024 * 1024
MAX_EXPANDED_BYTES = 12 * 1024 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 500_000
MAX_MANIFEST_BYTES = 8 * 1024 * 1024
CHUNK_SIZE = 1024 * 1024


class BackupError(ValueError):
    """The selected backup is invalid or cannot be restored safely."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _relative(value: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise BackupError("备份包含无效的文件路径。")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise BackupError("备份包含越界文件路径，已拒绝操作。")
    if any(":" in part for part in path.parts):
        raise BackupError("备份包含不支持的磁盘路径。")
    return path


def _contained_file(root: Path, relative: str) -> Path:
    rel = _relative(relative)
    base = root.expanduser().resolve()
    candidate = (base / Path(*rel.parts)).resolve(strict=False)
    if not candidate.is_relative_to(base):
        raise BackupError("应用资料文件引用超出资料目录，备份已停止。")
    return candidate


def _schema_revision(connection: sqlite3.Connection) -> str | None:
    exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='alembic_version'"
    ).fetchone()
    if not exists:
        return None
    rows = [row[0] for row in connection.execute("SELECT version_num FROM alembic_version")]
    if len(rows) != 1:
        raise BackupError("数据库迁移版本不明确，无法创建安全备份。")
    return rows[0]


def _migration_revisions() -> set[str]:
    versions_dir = Path(__file__).resolve().parents[2] / "migrations" / "versions"
    revisions: set[str] = set()
    for migration in versions_dir.glob("*.py"):
        for line in migration.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("revision ="):
                value = line.split("=", 1)[1].strip().strip("'\"")
                if value:
                    revisions.add(value)
                break
    return revisions


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def _referenced_files(connection: sqlite3.Connection, source_root: Path, material_root: Path):
    refs: dict[str, tuple[Path, str | None]] = {}
    if _table_exists(connection, "source_asset"):
        for original, preview, digest in connection.execute(
            "SELECT original_path, display_preview_path, sha256 FROM source_asset"
        ):
            for kind, relative, expected in (
                ("sources", original, digest),
                ("sources", preview, None),
            ):
                path = _contained_file(source_root, relative)
                archive_name = f"files/{kind}/{_relative(relative).as_posix()}"
                if archive_name in refs:
                    raise BackupError("数据库中存在重复来源文件路径。")
                refs[archive_name] = (path, expected)
    if _table_exists(connection, "material_version"):
        for relative, digest in connection.execute("SELECT path, sha256 FROM material_version"):
            path = _contained_file(material_root, relative)
            archive_name = f"files/materials/{_relative(relative).as_posix()}"
            if archive_name in refs:
                raise BackupError("数据库中存在重复资料文件路径。")
            refs[archive_name] = (path, digest)
    return refs


def _counts(connection: sqlite3.Connection) -> dict[str, int]:
    tables = {
        "questions": "question",
        "practice_reviews": "practice_review",
        "saved_answers": "saved_answer",
        "projects": "project",
        "materials": "material",
        "source_assets": "source_asset",
        "assistant_outputs": "assistant_output",
    }
    return {
        name: int(connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
        if _table_exists(connection, table) else 0
        for name, table in tables.items()
    }


def _snapshot_database(app: Flask, path: Path):
    engine = app.extensions["sqlalchemy_engine"]
    if engine.dialect.name != "sqlite":
        raise BackupError("当前应用数据库不是 SQLite，无法生成此格式的备份。")
    raw = engine.raw_connection()
    destination = sqlite3.connect(path)
    try:
        data_version = raw.driver_connection.execute("PRAGMA data_version").fetchone()[0]
        raw.driver_connection.backup(destination, pages=256, sleep=0.05)
        destination.commit()
        return raw, data_version
    except BaseException:
        raw.close()
        raise
    finally:
        destination.close()


def _hash_copy_to_zip(path: Path, archive: zipfile.ZipFile, name: str, expected: str | None) -> dict:
    before = path.stat()
    if not stat.S_ISREG(before.st_mode):
        raise BackupError("备份引用的资料不是普通文件。")
    digest = hashlib.sha256()
    size = 0
    info = zipfile.ZipInfo(name)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o600 << 16
    try:
        with path.open("rb") as source, archive.open(info, "w") as target:
            while chunk := source.read(CHUNK_SIZE):
                digest.update(chunk)
                size += len(chunk)
                target.write(chunk)
    except OSError as error:
        raise BackupError("备份期间有引用文件无法读取，请重试。") from error
    after = path.stat()
    if (before.st_ino, before.st_size, before.st_mtime_ns) != (
        after.st_ino, after.st_size, after.st_mtime_ns
    ):
        raise BackupError("备份期间有文件发生变化，请重试。")
    value = digest.hexdigest()
    if expected and value != expected:
        raise BackupError("来源或资料文件哈希与数据库不一致，备份已停止。")
    return {"path": name, "size": size, "sha256": value}


def create_backup(app: Flask) -> tuple[str, Callable[[], None]]:
    """Create an SQLite Online Backup snapshot plus all database-referenced files."""
    data_dir = Path(app.config["APP_DATA_DIR"]).expanduser().resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(tempfile.mkdtemp(prefix="backup-", dir=data_dir))
    archive_path = temp_dir / "agent-interview-assistant-backup.zip"
    source_connection = None
    try:
        snapshot_path = temp_dir / "snapshot.sqlite3"
        source_connection, data_version = _snapshot_database(app, snapshot_path)
        with sqlite3.connect(snapshot_path) as snapshot:
            integrity = snapshot.execute("PRAGMA integrity_check").fetchone()[0]
            foreign_keys = snapshot.execute("PRAGMA foreign_key_check").fetchall()
            if integrity != "ok" or foreign_keys:
                raise BackupError("当前数据库未通过完整性检查，无法生成备份。")
            revision = _schema_revision(snapshot)
            if revision is None or revision not in _migration_revisions():
                raise BackupError("当前数据库版本无法识别，无法生成可迁移备份。")
            refs = _referenced_files(
                snapshot,
                Path(app.config["SOURCE_STORAGE_DIR"]),
                data_dir / "materials",
            )
            counts = _counts(snapshot)

        file_records = []
        try:
            with zipfile.ZipFile(archive_path, "w", allowZip64=True) as archive:
                file_records.append(_hash_copy_to_zip(snapshot_path, archive, "database/interview_assistant.sqlite3", None))
                for name, (path, expected) in sorted(refs.items()):
                    file_records.append(_hash_copy_to_zip(path, archive, name, expected))
                manifest = {
                    "backup_format_version": BACKUP_FORMAT_VERSION,
                    "app_name": APP_NAME,
                    "app_version": APP_VERSION,
                    "created_at": _utc_now(),
                    "schema_revision": revision,
                    "data_counts": counts,
                    "files": file_records,
                }
                archive.writestr(
                    "manifest.json",
                    json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
                    compress_type=zipfile.ZIP_DEFLATED,
                )
            current_version = source_connection.driver_connection.execute("PRAGMA data_version").fetchone()[0]
            if current_version != data_version:
                raise BackupError("备份期间数据库发生变化，请在本机空闲时重试。")
        except BackupError:
            raise
        except (OSError, zipfile.BadZipFile, RuntimeError) as error:
            raise BackupError("写入备份时发生错误，现有数据未改变。") from error
        return str(archive_path), lambda: shutil.rmtree(temp_dir, ignore_errors=True)
    except BaseException:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise
    finally:
        if source_connection is not None:
            source_connection.close()


def _safe_archive_name(name: str) -> str:
    path = _relative(name)
    normalized = path.as_posix()
    if normalized == "manifest.json":
        return normalized
    if not (
        normalized == "database/interview_assistant.sqlite3"
        or normalized.startswith("files/sources/")
        or normalized.startswith("files/materials/")
    ):
        raise BackupError("备份包含不支持的文件，已拒绝恢复。")
    return normalized


def _validate_sqlite(path: Path, file_names: set[str]) -> dict:
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise BackupError("备份数据库未通过 SQLite 完整性检查。")
            if connection.execute("PRAGMA foreign_key_check").fetchall():
                raise BackupError("备份数据库包含无效的历史引用。")
            revision = _schema_revision(connection)
            if revision is None or revision not in _migration_revisions():
                raise BackupError("备份数据库版本与当前应用不兼容。")
            refs = _referenced_files(connection, Path("/backup/files/sources"), Path("/backup/files/materials"))
            expected_names = set(refs)
            # Build the expected set from DB-relative references; validation of
            # actual extracted contents happens after staging.
            missing = expected_names - file_names
            if missing:
                raise BackupError("备份缺少数据库引用的来源或资料文件。")
            return {
                "schema_revision": revision,
                "data_counts": _counts(connection),
                "referenced_files": expected_names,
                "expected_hashes": {
                    name: expected for name, (_path, expected) in refs.items() if expected
                },
            }
        finally:
            connection.close()
    except sqlite3.DatabaseError as error:
        raise BackupError("备份中的 SQLite 数据库无法读取。") from error


def inspect_backup(archive_path: str | Path) -> dict:
    """Validate structure, all hashes, SQLite integrity, foreign keys and file references."""
    path = Path(archive_path).expanduser()
    if not path.is_file() or path.stat().st_size > MAX_ARCHIVE_BYTES:
        raise BackupError("请选择有效且不超过 8 GB 的备份 ZIP。")
    with tempfile.TemporaryDirectory(prefix="backup-inspect-") as temporary:
        db_path = Path(temporary) / "snapshot.sqlite3"
        try:
            with zipfile.ZipFile(path, "r") as archive:
                infos = archive.infolist()
                if len(infos) > MAX_ARCHIVE_ENTRIES:
                    raise BackupError("备份包含过多文件。")
                names: set[str] = set()
                infos_by_name = {}
                expanded_size = 0
                for info in infos:
                    name = _safe_archive_name(info.filename.rstrip("/"))
                    if info.is_dir() or name in names or info.flag_bits & 0x1:
                        raise BackupError("备份包含重复、目录或加密条目。")
                    mode = info.external_attr >> 16
                    if stat.S_ISLNK(mode):
                        raise BackupError("备份包含符号链接，已拒绝恢复。")
                    if info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                        raise BackupError("备份使用了不支持的压缩方式。")
                    names.add(name)
                    infos_by_name[name] = info
                    expanded_size += info.file_size
                    if expanded_size > MAX_EXPANDED_BYTES:
                        raise BackupError("备份解压后超过允许大小。")
                if "manifest.json" not in names or "database/interview_assistant.sqlite3" not in names:
                    raise BackupError("备份缺少清单或 SQLite 数据库。")
                manifest_info = infos_by_name["manifest.json"]
                if manifest_info.file_size > MAX_MANIFEST_BYTES:
                    raise BackupError("备份清单过大。")
                try:
                    manifest = json.loads(archive.read(manifest_info))
                except (UnicodeDecodeError, json.JSONDecodeError, zipfile.BadZipFile) as error:
                    raise BackupError("备份清单损坏。") from error
                if not isinstance(manifest, dict) or manifest.get("backup_format_version") != BACKUP_FORMAT_VERSION:
                    raise BackupError("备份格式版本与当前应用不兼容。")
                if manifest.get("app_name") != APP_NAME or not isinstance(manifest.get("app_version"), str) or not isinstance(manifest.get("files"), list):
                    raise BackupError("备份清单格式无效。")
                records = {}
                for record in manifest["files"]:
                    if not isinstance(record, dict) or set(record) != {"path", "size", "sha256"}:
                        raise BackupError("备份清单包含无效文件记录。")
                    name = _safe_archive_name(record["path"])
                    if name == "manifest.json" or name in records:
                        raise BackupError("备份清单包含重复文件记录。")
                    if type(record["size"]) is not int or record["size"] < 0:
                        raise BackupError("备份文件大小记录无效。")
                    digest = record["sha256"]
                    if not isinstance(digest, str) or len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
                        raise BackupError("备份文件哈希记录无效。")
                    records[name] = record
                if set(records) != names - {"manifest.json"}:
                    raise BackupError("备份文件与清单记录不一致。")
                for name, record in records.items():
                    info = infos_by_name[name]
                    if info.file_size != record["size"]:
                        raise BackupError("备份文件大小与清单不一致。")
                    digest = hashlib.sha256()
                    if name == "database/interview_assistant.sqlite3":
                        target = db_path.open("xb")
                    else:
                        target = None
                    try:
                        with archive.open(info, "r") as source:
                            while chunk := source.read(CHUNK_SIZE):
                                digest.update(chunk)
                                if target is not None:
                                    target.write(chunk)
                    finally:
                        if target is not None:
                            target.close()
                    if digest.hexdigest() != record["sha256"]:
                        raise BackupError("备份文件哈希校验失败。")
                file_names = set(records) - {"database/interview_assistant.sqlite3"}
                database = _validate_sqlite(db_path, file_names)
                if database["referenced_files"] != file_names:
                    raise BackupError("备份包含未被数据库引用的资料文件。")
                for name, expected in database["expected_hashes"].items():
                    if records[name]["sha256"] != expected:
                        raise BackupError("备份文件哈希与数据库记录不一致。")
                if manifest.get("schema_revision") != database["schema_revision"]:
                    raise BackupError("备份清单与数据库迁移版本不一致。")
                if manifest.get("data_counts") != database["data_counts"]:
                    raise BackupError("备份清单中的数据规模与数据库不一致。")
                return {
                    "valid": True,
                    "backup_format_version": BACKUP_FORMAT_VERSION,
                    "app_version": manifest["app_version"],
                    "created_at": manifest.get("created_at"),
                    "schema_revision": database["schema_revision"],
                    "data_counts": database["data_counts"],
                    "file_count": len(records) - 1,
                    "total_bytes": sum(info.file_size for info in infos),
                }
        except zipfile.BadZipFile as error:
            raise BackupError("文件不是有效的 ZIP 备份。") from error


def _upgrade_database(path: Path) -> None:
    backend_root = Path(__file__).resolve().parents[2]
    alembic_config = Config(str(backend_root / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(backend_root / "migrations"))
    database_url = URL.create("sqlite", database=str(path)).render_as_string(hide_password=False)
    alembic_config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(alembic_config, "head")


def _validate_staged_files(data_dir: Path) -> None:
    database_path = data_dir / "interview_assistant.sqlite3"
    with sqlite3.connect(database_path) as connection:
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise BackupError("恢复暂存数据库未通过完整性检查。")
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise BackupError("恢复暂存数据库包含无效历史引用。")
        if _schema_revision(connection) not in _migration_revisions():
            raise BackupError("恢复后的数据库版本无法识别。")
        refs = _referenced_files(connection, data_dir / "sources", data_dir / "materials")
        for path, expected in refs.values():
            if not path.is_file():
                raise BackupError("恢复暂存目录缺少数据库引用的文件。")
            if expected:
                hasher = hashlib.sha256()
                with path.open("rb") as stream:
                    while chunk := stream.read(CHUNK_SIZE):
                        hasher.update(chunk)
                if hasher.hexdigest() != expected:
                    raise BackupError("恢复后的资料文件哈希与数据库不一致。")


def restore_backup(
    archive_path: str | Path,
    data_dir: str | Path,
    *,
    replace_existing: bool = False,
    confirmed: bool = False,
) -> dict:
    """Restore into a stopped application's data directory via validated staging."""
    source = Path(archive_path).expanduser().resolve()
    if not source.is_file():
        raise BackupError("请选择存在的备份 ZIP 文件。")
    target_input = Path(data_dir).expanduser()
    if target_input.exists() and target_input.is_symlink():
        raise BackupError("恢复目标不能是符号链接。")
    target = target_input.resolve()
    if not target.is_absolute() or target == Path("/") or target == source.parent:
        raise BackupError("恢复目标目录无效。")
    if target.exists() and not target.is_dir():
        raise BackupError("恢复目标必须是普通目录。")
    active_pid = running_service_pid(target)
    if active_pid is not None:
        raise BackupError(f"检测到应用服务仍在运行（PID {active_pid}）；请先关闭 Flask 后再恢复。")
    if target.exists() and any(target.iterdir()):
        if not (replace_existing and confirmed):
            raise BackupError("目标目录已有数据；需要明确指定替换并二次确认。")
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.restore-", dir=target.parent))
    previous: Path | None = None
    try:
        archive_copy = staging / "restore-input.zip"
        source_before = source.stat()
        if source_before.st_size > MAX_ARCHIVE_BYTES:
            raise BackupError("备份文件超过 8 GB。")
        with source.open("rb") as source_stream, archive_copy.open("xb") as archive_stream:
            shutil.copyfileobj(source_stream, archive_stream, CHUNK_SIZE)
        source_after = source.stat()
        if (source_before.st_ino, source_before.st_size, source_before.st_mtime_ns) != (
            source_after.st_ino, source_after.st_size, source_after.st_mtime_ns
        ):
            raise BackupError("备份文件在读取期间发生变化，请重新选择后恢复。")
        info = inspect_backup(archive_copy)
        with zipfile.ZipFile(archive_copy, "r") as archive:
            for info_item in archive.infolist():
                name = _safe_archive_name(info_item.filename.rstrip("/"))
                if name == "manifest.json":
                    continue
                relative = _relative(name)
                output = staging.joinpath(*relative.parts)
                if not output.resolve(strict=False).is_relative_to(staging.resolve()):
                    raise BackupError("备份路径超出恢复暂存目录。")
                output.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info_item, "r") as input_stream, output.open("xb") as output_stream:
                    shutil.copyfileobj(input_stream, output_stream, CHUNK_SIZE)
        archive_copy.unlink()
        database_path = staging / "database" / "interview_assistant.sqlite3"
        if not database_path.is_file():
            raise BackupError("恢复暂存目录缺少数据库。")
        (staging / "database").rename(staging / "database-tmp")
        (staging / "database-tmp" / "interview_assistant.sqlite3").replace(staging / "interview_assistant.sqlite3")
        shutil.rmtree(staging / "database-tmp")
        file_root = staging / "files"
        (file_root / "sources").mkdir(parents=True, exist_ok=True)
        (file_root / "materials").mkdir(parents=True, exist_ok=True)
        (file_root / "sources").rename(staging / "sources")
        (file_root / "materials").rename(staging / "materials")
        shutil.rmtree(file_root)
        _upgrade_database(staging / "interview_assistant.sqlite3")
        _validate_staged_files(staging)

        if target.exists() and any(target.iterdir()):
            if not (replace_existing and confirmed):
                raise BackupError("目标目录在恢复期间出现了数据，已保留原目录。")
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            previous = target.with_name(f"{target.name}.pre-restore-{stamp}")
            suffix = 1
            while previous.exists():
                previous = target.with_name(f"{target.name}.pre-restore-{stamp}-{suffix}")
                suffix += 1
            target.rename(previous)
        elif target.exists():
            target.rmdir()
        try:
            staging.rename(target)
        except BaseException:
            if previous is not None and previous.exists() and not target.exists():
                previous.rename(target)
            raise
        return {
            "restored_to": str(target),
            "previous_data_preserved_at": str(previous) if previous else None,
            "data_counts": info["data_counts"],
            "file_count": info["file_count"],
            "schema_revision": _schema_revision_sqlite(target / "interview_assistant.sqlite3"),
        }
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _schema_revision_sqlite(path: Path) -> str | None:
    with sqlite3.connect(path) as connection:
        return _schema_revision(connection)
