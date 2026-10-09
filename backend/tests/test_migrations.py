import hashlib
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


def _insert_phase1b_history(connection) -> None:
    connection.execute(
        text(
            "INSERT INTO topic (id, track_key, slug, name) "
            "VALUES (1, 'agent_development', 'legacy-topic', 'Legacy Topic')"
        )
    )
    connection.execute(text("INSERT INTO tag (id, name) VALUES (1, 'Legacy Tag')"))
    connection.execute(
        text(
            "INSERT INTO source_asset "
            "(id, source_type, original_filename, mime_type, byte_size, "
            "original_width, original_height, display_width, display_height, "
            "original_path, display_preview_path, sha256, metadata_json) "
            "VALUES (1, 'image', 'legacy.png', 'image/png', 16, 100, 200, "
            "100, 200, 'sources/original/legacy.bin', "
            "'sources/display/legacy.png', :sha, '{}')"
        ),
        {"sha": "a" * 64},
    )
    connection.execute(
        text(
            "INSERT INTO ingestion_job "
            "(id, source_asset_id, status, stage, candidate_count) "
            "VALUES (1, 1, 'succeeded', 'completed', 1)"
        )
    )
    block_id = "00000000-0000-4000-8000-000000000001"
    connection.execute(
        text(
            "INSERT INTO ocr_block "
            "(id, ingestion_job_id, text, bbox_json, reading_order, confidence) "
            "VALUES (:id, 1, 'Original OCR text', :bbox, 1, 0.98)"
        ),
        {
            "id": block_id,
            "bbox": '{"x":0.1,"y":0.2,"width":0.3,"height":0.1}',
        },
    )
    connection.execute(
        text(
            "INSERT INTO question "
            "(id, text, normalized_text, search_text, normalized_hash, status) "
            "VALUES (1, 'Legacy manual question', 'legacy manual question', "
            "'manualneedlebeforemigration', :hash1, 'active')"
        ),
        {"hash1": "1" * 64},
    )
    connection.execute(
        text(
            "INSERT INTO question "
            "(id, text, normalized_text, search_text, normalized_hash, status, "
            "origin_ingestion_job_id, ingestion_candidate_state, candidate_revision) "
            "VALUES (2, 'Corrected OCR question', 'corrected ocr question', "
            "'ocrneedlebeforemigration', :hash2, 'active', 1, 'confirmed', 1)"
        ),
        {"hash2": "2" * 64},
    )
    connection.execute(
        text(
            "INSERT INTO question_topic (question_id, topic_id) VALUES (1, 1)"
        )
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
            "INSERT INTO question_source "
            "(id, question_id, source_asset_id, locator_type, locator_json, "
            "locator_correction_json, source_text_snapshot, raw_ocr_text_snapshot) "
            "VALUES (1, 2, 1, 'image_region', :locator, :correction, "
            "'Human corrected excerpt', 'Original OCR text')"
        ),
        {
            "locator": '{"x":0.11,"y":0.22,"width":0.33,"height":0.12}',
            "correction": '{"x":0.12,"y":0.23,"width":0.31,"height":0.11}',
        },
    )
    connection.execute(
        text(
            "INSERT INTO question_source_ocr_block (question_source_id, ocr_block_id) "
            "VALUES (1, :block_id)"
        ),
        {"block_id": block_id},
    )
    connection.execute(
        text(
            "INSERT INTO practice_session "
            "(id, mode, filters_json, selector_version) "
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


def _insert_legacy_question(
    connection,
    *,
    question_id: int,
    text_value: str,
    normalized_hash: str,
    status: str = "active",
    archived_at: str | None = None,
) -> None:
    connection.execute(
        text(
            "INSERT INTO question "
            "(id, text, normalized_text, search_text, normalized_hash, status, archived_at) "
            "VALUES (:id, :text_value, :normalized_text, :search_text, :hash, :status, :archived_at)"
        ),
        {
            "id": question_id,
            "text_value": text_value,
            "normalized_text": text_value.casefold(),
            "search_text": text_value.casefold(),
            "hash": normalized_hash,
            "status": status,
            "archived_at": archived_at,
        },
    )


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
        "question_relation",
    } <= tables
    question_columns = {column["name"] for column in inspect(engine).get_columns("question")}
    assert "merged_into_question_id" in question_columns


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


def test_phase1c_migration_preserves_phase1b_history_and_fts(tmp_path):
    database_path = tmp_path / "existing-phase1b.sqlite3"
    config, database_url = _migration_config(database_path)
    command.upgrade(config, "0003_phase1b_sources")

    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            _insert_phase1b_history(connection)
            triggers_before = {
                row[0]
                for row in connection.execute(
                    text("SELECT name FROM sqlite_master WHERE type='trigger'")
                )
            }
            assert {
                "question_fts_after_insert",
                "question_fts_after_update",
                "question_fts_after_delete",
            } <= triggers_before

        command.upgrade(config, "head")

        with engine.begin() as connection:
            assert connection.execute(
                text("PRAGMA foreign_key_check")
            ).all() == []
            assert connection.scalar(text("PRAGMA integrity_check")) == "ok"

            triggers_after = {
                row[0]
                for row in connection.execute(
                    text("SELECT name FROM sqlite_master WHERE type='trigger'")
                )
            }
            assert {
                "question_fts_after_insert",
                "question_fts_after_update",
                "question_fts_after_delete",
            } <= triggers_after

            question_rows = connection.execute(
                text(
                    "SELECT id, text, status, normalized_hash, origin_ingestion_job_id, "
                    "ingestion_candidate_state, candidate_revision, merged_into_question_id "
                    "FROM question ORDER BY id"
                )
            ).all()
            assert question_rows == [
                (1, "Legacy manual question", "active", "1" * 64, None, None, 0, None),
                (
                    2,
                    "Corrected OCR question",
                    "active",
                    "2" * 64,
                    1,
                    "confirmed",
                    1,
                    None,
                ),
            ]
            assert connection.execute(
                text(
                    "SELECT id, question_id, source_asset_id, locator_json, "
                    "locator_correction_json, source_text_snapshot, raw_ocr_text_snapshot "
                    "FROM question_source"
                )
            ).one() == (
                1,
                2,
                1,
                '{"x":0.11,"y":0.22,"width":0.33,"height":0.12}',
                '{"x":0.12,"y":0.23,"width":0.31,"height":0.11}',
                "Human corrected excerpt",
                "Original OCR text",
            )
            assert connection.execute(
                text("SELECT id, text, bbox_json FROM ocr_block")
            ).one() == (
                "00000000-0000-4000-8000-000000000001",
                "Original OCR text",
                '{"x":0.1,"y":0.2,"width":0.3,"height":0.1}',
            )
            assert connection.execute(
                text("SELECT question_source_id, ocr_block_id FROM question_source_ocr_block")
            ).one() == (1, "00000000-0000-4000-8000-000000000001")
            assert connection.scalar(text("SELECT count(*) FROM question_topic")) == 1
            assert connection.scalar(text("SELECT count(*) FROM question_tag")) == 1
            assert connection.scalar(text("SELECT count(*) FROM question_state")) == 1
            assert connection.scalar(text("SELECT count(*) FROM session_item")) == 1
            assert connection.scalar(text("SELECT count(*) FROM practice_review")) == 1
            assert connection.scalar(
                text(
                    "SELECT count(*) FROM question_fts "
                    "WHERE question_fts MATCH 'manualneedlebeforemigration'"
                )
            ) == 1

            connection.execute(
                text(
                    "UPDATE question SET search_text='postmigrationneedle' WHERE id=1"
                )
            )
            assert connection.scalar(
                text(
                    "SELECT count(*) FROM question_fts "
                    "WHERE question_fts MATCH 'postmigrationneedle'"
                )
            ) == 1
            assert connection.scalar(
                text(
                    "SELECT count(*) FROM question_fts "
                    "WHERE question_fts MATCH 'manualneedlebeforemigration'"
                )
            ) == 0
    finally:
        engine.dispose()


def test_phase1c_migration_backfills_only_suggested_exact_hash_relations(tmp_path):
    database_path = tmp_path / "duplicate-hashes-at-0003.sqlite3"
    config, database_url = _migration_config(database_path)
    command.upgrade(config, "0003_phase1b_sources")
    engine = create_engine(database_url)
    duplicate_hash = "d" * 64
    first_text = "MCP 与 Function Calling 有什么区别？"
    second_text = "MCP 与 Function Calling 有什么区别?"
    try:
        with engine.begin() as connection:
            _insert_legacy_question(
                connection,
                question_id=1,
                text_value=first_text,
                normalized_hash=duplicate_hash,
            )
            _insert_legacy_question(
                connection,
                question_id=2,
                text_value=second_text,
                normalized_hash=duplicate_hash,
            )
            _insert_legacy_question(
                connection,
                question_id=3,
                text_value="Archived duplicate",
                normalized_hash=duplicate_hash,
                archived_at="2026-01-01 00:00:00",
            )
            _insert_legacy_question(
                connection,
                question_id=4,
                text_value="Pending duplicate",
                normalized_hash=duplicate_hash,
                status="pending_review",
            )

        command.upgrade(config, "head")

        with engine.connect() as connection:
            relations = connection.execute(
                text(
                    "SELECT question_id, related_question_id, relation_type, "
                    "decision_status, suggested_by, confidence, "
                    "question_text_sha256_snapshot, related_question_text_sha256_snapshot "
                    "FROM question_relation"
                )
            ).all()
            assert relations == [
                (
                    1,
                    2,
                    "same_question",
                    "suggested",
                    "rule",
                    1.0,
                    hashlib.sha256(first_text.encode("utf-8")).hexdigest(),
                    hashlib.sha256(second_text.encode("utf-8")).hexdigest(),
                )
            ]
            assert connection.execute(
                text("SELECT id, status FROM question ORDER BY id")
            ).all() == [
                (1, "active"),
                (2, "active"),
                (3, "active"),
                (4, "pending_review"),
            ]
            assert connection.execute(
                text("SELECT id, merged_into_question_id FROM question ORDER BY id")
            ).all() == [(1, None), (2, None), (3, None), (4, None)]
    finally:
        engine.dispose()


def test_phase1c_migration_rejects_legacy_merged_question_before_schema_changes(tmp_path):
    database_path = tmp_path / "legacy-merged-question.sqlite3"
    config, database_url = _migration_config(database_path)
    command.upgrade(config, "0003_phase1b_sources")
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            _insert_legacy_question(
                connection,
                question_id=1,
                text_value="Legacy merged row without target",
                normalized_hash="m" * 64,
                status="merged",
            )
            triggers_before = {
                row[0]
                for row in connection.execute(
                    text("SELECT name FROM sqlite_master WHERE type='trigger'")
                )
            }

        with pytest.raises(RuntimeError, match="status=merged"):
            command.upgrade(config, "head")

        with engine.connect() as connection:
            revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
            assert revision == "0003_phase1b_sources"
            tables = set(inspect(connection).get_table_names())
            columns = {item["name"] for item in inspect(connection).get_columns("question")}
            triggers_after = {
                row[0]
                for row in connection.execute(
                    text("SELECT name FROM sqlite_master WHERE type='trigger'")
                )
            }
            assert "question_relation" not in tables
            assert "merged_into_question_id" not in columns
            assert triggers_after == triggers_before
            assert connection.scalar(
                text("SELECT status FROM question WHERE id=1")
            ) == "merged"
    finally:
        engine.dispose()


@pytest.mark.parametrize("payload_kind", ["relation", "merge"])
def test_phase1c_downgrade_refuses_to_drop_relation_or_merge_data(tmp_path, payload_kind):
    database_path = tmp_path / f"nonempty-0004-{payload_kind}.sqlite3"
    config, database_url = _migration_config(database_path)
    command.upgrade(config, "head")
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            _insert_legacy_question(
                connection,
                question_id=1,
                text_value="Canonical root",
                normalized_hash="r" * 64,
            )
            if payload_kind == "relation":
                second_text = "Possible duplicate"
                _insert_legacy_question(
                    connection,
                    question_id=2,
                    text_value=second_text,
                    normalized_hash="s" * 64,
                )
                connection.execute(
                    text(
                        "INSERT INTO question_relation "
                        "(question_id, related_question_id, relation_type, "
                        "decision_status, suggested_by, confidence, "
                        "question_text_sha256_snapshot, related_question_text_sha256_snapshot) "
                        "VALUES (1, 2, 'same_question', 'suggested', 'rule', 0.5, :left, :right)"
                    ),
                    {
                        "left": hashlib.sha256(b"Canonical root").hexdigest(),
                        "right": hashlib.sha256(second_text.encode("utf-8")).hexdigest(),
                    },
                )
            else:
                connection.execute(
                    text(
                        "INSERT INTO question "
                        "(id, text, normalized_text, search_text, normalized_hash, "
                        "status, merged_into_question_id) "
                        "VALUES (2, 'Merged child', 'merged child', 'merged child', "
                        "'t', 'merged', 1)"
                    )
                )

        with pytest.raises(RuntimeError, match="Cannot downgrade"):
            command.downgrade(config, "0003_phase1b_sources")

        with engine.connect() as connection:
            assert "question_relation" in inspect(connection).get_table_names()
            assert "merged_into_question_id" in {
                column["name"] for column in inspect(connection).get_columns("question")
            }
            if payload_kind == "relation":
                assert connection.scalar(
                    text("SELECT count(*) FROM question_relation")
                ) == 1
            else:
                assert connection.scalar(
                    text("SELECT merged_into_question_id FROM question WHERE id=2")
                ) == 1
    finally:
        engine.dispose()


def test_phase1c_empty_database_downgrade_to_0003_is_safe(tmp_path):
    config, database_url = _migration_config(tmp_path / "empty-0004.sqlite3")
    command.upgrade(config, "head")
    command.downgrade(config, "0003_phase1b_sources")

    engine = create_engine(database_url)
    try:
        tables = set(inspect(engine).get_table_names())
        columns = {column["name"] for column in inspect(engine).get_columns("question")}
        assert "question_relation" not in tables
        assert "merged_into_question_id" not in columns
        assert "question_fts" in tables
    finally:
        engine.dispose()
