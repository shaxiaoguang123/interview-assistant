from __future__ import annotations

import os
from pathlib import Path
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, event, pool
from sqlalchemy.engine import make_url

from app.config import default_database_url
from app.db import Base
import app.models  # noqa: F401 - register all model metadata with Base


config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

configured_url = config.get_main_option("sqlalchemy.url")
database_url = configured_url or os.environ.get("DATABASE_URL") or default_database_url()
config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
target_metadata = Base.metadata


def ensure_sqlite_parent_directory(url: str) -> None:
    parsed_url = make_url(url)
    database_path = parsed_url.database
    if parsed_url.get_backend_name() != "sqlite" or database_path in (None, ":memory:"):
        return
    Path(database_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)


def run_migrations_offline() -> None:
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    ensure_sqlite_parent_directory(database_url)
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    if connectable.dialect.name == "sqlite":

        @event.listens_for(connectable, "connect")
        def enable_sqlite_foreign_keys_and_explicit_transactions(
            dbapi_connection, _connection_record
        ) -> None:
            # Disable sqlite3 legacy transaction control. Alembic's SQLite
            # dialect otherwise treats DDL as non-transactional, so a failed
            # revision can leave part of its schema behind.
            dbapi_connection.isolation_level = None
            cursor = dbapi_connection.cursor()
            # FK checks must be deferred across SQLite parent-table copies.
            # This connection is migration-only (NullPool), never an app connection.
            cursor.execute("PRAGMA foreign_keys=OFF")
            cursor.close()

        @event.listens_for(connectable, "begin")
        def begin_sqlite_migration_transaction(connection) -> None:
            connection.exec_driver_sql("BEGIN")

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            transactional_ddl=connection.dialect.name == "sqlite",
        )
        with context.begin_transaction():
            context.run_migrations()
            if connection.dialect.name == "sqlite":
                violations = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
                if violations:
                    raise RuntimeError(f"Migration foreign key validation failed: {violations[:5]}")


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
