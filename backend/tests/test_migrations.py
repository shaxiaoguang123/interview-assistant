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


def _migration_config(database_path: Path) -> tuple[Config, str]:
    alembic_ini = BACKEND_ROOT / "alembic.ini"
    database_url = URL.create("sqlite", database=str(database_path)).render_as_string(
        hide_password=False
    )
    config = Config(str(alembic_ini))
    config.set_main_option("sqlalchemy.url", database_url)
    return config, database_url


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


def test_phase1b_migration_upgrades_existing_1a_database_without_data_loss(tmp_path):
    database_path = tmp_path / "existing-phase1a.sqlite3"
    config, database_url = _migration_config(database_path)
    command.upgrade(config, "0002_question_search")

    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO topic (id, track_key, slug, name) "
                    "VALUES (1, 'agent_development', 'legacy-topic', 'Legacy Topic')"
                )
            )
            connection.execute(text("INSERT INTO tag (id, name) VALUES (1, 'Legacy Tag')"))
            connection.execute(
                text(
                    "INSERT INTO question "
                    "(id, text, normalized_text, search_text, normalized_hash, status) "
                    "VALUES (1, 'Legacy Agent question', 'legacy agent question', "
                    "'legacy agent question', 'legacy-hash', 'active')"
                )
            )
            connection.execute(
                text("INSERT INTO question_topic (question_id, topic_id) VALUES (1, 1)")
            )
            connection.execute(
                text("INSERT INTO question_tag (question_id, tag_id) VALUES (1, 1)")
            )
            connection.execute(
                text(
                    "INSERT INTO question_state (question_id, is_favorite, is_wrong) "
                    "VALUES (1, 1, 0)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO practice_session (id, mode, filters_json, selector_version) "
                    "VALUES (1, 'random', '{}', 'v1')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO session_item "
                    "(id, session_id, question_id, ordinal, status) "
                    "VALUES (1, 1, 1, 1, 'completed')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO practice_review "
                    "(id, question_id, session_item_id, review_rating) "
                    "VALUES (1, 1, 1, 'basic')"
                )
            )

        command.upgrade(config, "head")

        with engine.connect() as connection:
            question = connection.execute(
                text(
                    "SELECT text, status, origin_ingestion_job_id, "
                    "ingestion_candidate_state, split_from_candidate_id, "
                    "superseded_by_candidate_id FROM question WHERE id = 1"
                )
            ).one()
            assert question == (
                "Legacy Agent question",
                "active",
                None,
                None,
                None,
                None,
            )
            assert connection.scalar(text("SELECT count(*) FROM question_topic")) == 1
            assert connection.scalar(text("SELECT count(*) FROM question_tag")) == 1
            assert connection.scalar(text("SELECT count(*) FROM question_state")) == 1
            assert connection.scalar(text("SELECT count(*) FROM session_item")) == 1
            assert connection.scalar(text("SELECT count(*) FROM practice_review")) == 1
            assert connection.scalar(
                text(
                    "SELECT count(*) FROM question_fts "
                    "WHERE question_fts MATCH 'Legacy'"
                )
            ) == 1
    finally:
        engine.dispose()
