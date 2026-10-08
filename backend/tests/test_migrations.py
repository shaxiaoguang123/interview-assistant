from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.engine import URL

from app import create_app
from app.config import default_data_dir


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _upgrade_empty_database(database_path: Path) -> str:
    alembic_ini = BACKEND_ROOT / "alembic.ini"
    assert alembic_ini.is_file(), "missing feature: backend/alembic.ini"
    database_url = URL.create("sqlite", database=str(database_path)).render_as_string(hide_password=False)
    config = Config(str(alembic_ini))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")
    return database_url


def test_alembic_upgrades_empty_database_to_head(tmp_path):
    database_path = tmp_path / "empty.sqlite3"
    assert not database_path.exists()

    database_url = _upgrade_empty_database(database_path)
    engine = create_engine(database_url)
    try:
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()

    assert {
        "alembic_version",
        "topic",
        "tag",
        "question",
        "question_topic",
        "question_tag",
        "question_state",
        "practice_session",
        "session_item",
        "practice_review",
    } <= tables


def test_alembic_creates_default_app_data_directory(tmp_path, monkeypatch):
    app_data_dir = tmp_path / "new-user-data" / "agent-assistant"
    monkeypatch.setenv("APP_DATA_DIR", str(app_data_dir))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    alembic_ini = BACKEND_ROOT / "alembic.ini"
    config = Config(str(alembic_ini))

    try:
        command.upgrade(config, "head")
    except Exception as error:
        pytest.fail(f"Alembic must create the configured SQLite parent directory: {error}")

    assert (app_data_dir / "interview_assistant.sqlite3").is_file()


def test_alembic_explicit_test_url_overrides_environment_database_url(tmp_path, monkeypatch):
    configured_test_path = tmp_path / "configured-test" / "test.sqlite3"
    environment_path = tmp_path / "environment-db.sqlite3"
    configured_url = URL.create("sqlite", database=str(configured_test_path)).render_as_string(
        hide_password=False
    )
    environment_url = URL.create("sqlite", database=str(environment_path)).render_as_string(
        hide_password=False
    )
    monkeypatch.setenv("DATABASE_URL", environment_url)
    alembic_config = Config(str(BACKEND_ROOT / "alembic.ini"))
    alembic_config.set_main_option("sqlalchemy.url", configured_url)

    command.upgrade(alembic_config, "head")

    assert configured_test_path.is_file()
    assert not environment_path.exists()


def test_test_database_is_outside_real_data_directory(tmp_path):
    real_data_dir = default_data_dir().resolve()
    test_database_path = tmp_path / "isolated.sqlite3"
    test_database_url = URL.create("sqlite", database=str(test_database_path)).render_as_string(
        hide_password=False
    )
    app = create_app(
        {
            "TESTING": True,
            "APP_DATA_DIR": real_data_dir,
            "DATABASE_URL": test_database_url,
            "SEED_TOPICS_ON_STARTUP": False,
        }
    )

    engine = app.extensions["sqlalchemy_engine"]
    try:
        with engine.connect() as connection:
            database_list = connection.execute(text("PRAGMA database_list")).all()
        sqlite_path = Path(database_list[0][2]).resolve()
    finally:
        engine.dispose()

    assert sqlite_path == test_database_path.resolve()
    assert real_data_dir not in sqlite_path.parents


def test_sqlite_foreign_keys_are_enabled(tmp_path):
    database_url = _upgrade_empty_database(tmp_path / "foreign-keys.sqlite3")
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": database_url,
            "SEED_TOPICS_ON_STARTUP": False,
        }
    )
    engine = app.extensions["sqlalchemy_engine"]
    try:
        with engine.connect() as connection:
            assert connection.scalar(text("PRAGMA foreign_keys")) == 1
    finally:
        engine.dispose()


def test_sqlite_rejects_foreign_key_violation(tmp_path):
    database_url = _upgrade_empty_database(tmp_path / "foreign-key-violation.sqlite3")
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": database_url,
            "SEED_TOPICS_ON_STARTUP": False,
        }
    )
    engine = app.extensions["sqlalchemy_engine"]
    try:
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text("INSERT INTO question_topic (question_id, topic_id) VALUES (-1, -1)")
                )
    finally:
        engine.dispose()
