from importlib import import_module
from pathlib import Path
import uuid

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, select
from sqlalchemy.engine import URL
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.question import Question


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _migrated_app(database_path: Path):
    database_url = URL.create("sqlite", database=str(database_path)).render_as_string(
        hide_password=False
    )
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")
    from app import create_app

    return create_app(
        {
            "TESTING": True,
            "DATABASE_URL": database_url,
            "SEED_TOPICS_ON_STARTUP": False,
        }
    )


def _phase1b_models():
    model_path = BACKEND_ROOT / "app" / "models" / "ingestion.py"
    assert model_path.is_file(), "missing feature: Phase 1B ingestion models"
    return import_module("app.models.ingestion")


def _new_source_job(session: Session, models):
    source = models.SourceAsset(
        original_filename="sample.png",
        mime_type="image/png",
        byte_size=1,
        original_width=1,
        original_height=1,
        display_width=1,
        display_height=1,
        original_path="sources/original/sample.bin",
        display_preview_path="sources/display/sample.png",
        sha256="a" * 64,
    )
    session.add(source)
    session.flush()
    job = models.IngestionJob(source_asset_id=source.id, status="queued", stage="queued")
    session.add(job)
    session.flush()
    return source, job


def _question(**overrides):
    fields = {
        "text": "Agent question?",
        "normalized_text": "agent question?",
        "search_text": "agent question?",
        "normalized_hash": "same-hash",
    }
    fields.update(overrides)
    return Question(**fields)


def test_phase1b_tables_and_foreign_keys_exist(tmp_path):
    app = _migrated_app(tmp_path / "phase1b-tables.sqlite3")
    engine = app.extensions["sqlalchemy_engine"]
    try:
        inspector = inspect(engine)
        assert {
            "source_asset",
            "ingestion_job",
            "ocr_block",
            "question_source",
            "question_source_ocr_block",
        } <= set(inspector.get_table_names())

        question_columns = {
            column["name"]: column for column in inspector.get_columns("question")
        }
        assert {
            "origin_ingestion_job_id",
            "ingestion_candidate_state",
            "candidate_revision",
            "split_from_candidate_id",
            "superseded_by_candidate_id",
        } <= set(question_columns)
        assert question_columns["origin_ingestion_job_id"]["nullable"] is True
        assert question_columns["split_from_candidate_id"]["nullable"] is True
        assert question_columns["superseded_by_candidate_id"]["nullable"] is True

        with engine.connect() as connection:
            question_fks = connection.exec_driver_sql(
                "PRAGMA foreign_key_list(question)"
            ).all()
        assert any(
            fk[2] == "ingestion_job"
            and fk[3] == "origin_ingestion_job_id"
            and fk[6] == "RESTRICT"
            for fk in question_fks
        )
        assert sum(
            fk[2] == "question"
            and fk[6] == "RESTRICT"
            for fk in question_fks
        ) >= 2
    finally:
        engine.dispose()


def test_manual_question_keeps_null_ingestion_provenance_and_lineage(tmp_path):
    _phase1b_models()
    app = _migrated_app(tmp_path / "manual-question.sqlite3")
    engine = app.extensions["sqlalchemy_engine"]
    try:
        with Session(engine) as session:
            question = _question()
            session.add(question)
            session.commit()
            session.refresh(question)
            assert question.status == "active"
            assert question.origin_ingestion_job_id is None
            assert question.ingestion_candidate_state is None
            assert question.split_from_candidate_id is None
            assert question.superseded_by_candidate_id is None
            assert question.candidate_revision == 0
    finally:
        engine.dispose()


def test_candidate_revision_defaults_to_zero_and_cannot_be_negative(tmp_path):
    _phase1b_models()
    app = _migrated_app(tmp_path / "candidate-revision.sqlite3")
    engine = app.extensions["sqlalchemy_engine"]
    try:
        with Session(engine) as session:
            question = _question()
            session.add(question)
            session.flush()
            assert question.candidate_revision == 0

            invalid = _question(text="Invalid revision?")
            invalid.candidate_revision = -1
            session.add(invalid)
            with pytest.raises(IntegrityError):
                session.flush()
            session.rollback()
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "lineage_field",
    ["split_from_candidate_id", "superseded_by_candidate_id"],
)
def test_candidate_lineage_rejects_self_reference(tmp_path, lineage_field):
    models = _phase1b_models()
    app = _migrated_app(tmp_path / "candidate-lineage.sqlite3")
    engine = app.extensions["sqlalchemy_engine"]
    try:
        with Session(engine) as session:
            _, job = _new_source_job(session, models)
            candidate = _question(
                status="pending_review",
                origin_ingestion_job_id=job.id,
                ingestion_candidate_state="pending_review",
            )
            session.add(candidate)
            session.flush()
            setattr(candidate, lineage_field, candidate.id)
            with pytest.raises(IntegrityError):
                session.flush()
            session.rollback()
    finally:
        engine.dispose()


def test_question_rejects_invalid_candidate_disposition(tmp_path):
    _phase1b_models()
    app = _migrated_app(tmp_path / "candidate-disposition.sqlite3")
    engine = app.extensions["sqlalchemy_engine"]
    try:
        with Session(engine) as session:
            question = _question(ingestion_candidate_state="not-a-candidate-state")
            session.add(question)
            with pytest.raises(IntegrityError):
                session.flush()
            session.rollback()
    finally:
        engine.dispose()


def test_ocr_block_uses_stable_uuid_primary_key(tmp_path):
    models = _phase1b_models()
    app = _migrated_app(tmp_path / "ocr-block-id.sqlite3")
    engine = app.extensions["sqlalchemy_engine"]
    try:
        with Session(engine) as session:
            _, job = _new_source_job(session, models)
            block = models.OCRBlock(
                ingestion_job_id=job.id,
                text="MCP?",
                bbox_json={"x": 0.1, "y": 0.2, "width": 0.5, "height": 0.1},
                reading_order=1,
            )
            session.add(block)
            session.commit()
            block_id = block.id
            assert str(uuid.UUID(block_id)) == block_id
            assert session.get(models.OCRBlock, block_id).id == block_id
            assert inspect(models.OCRBlock).primary_key[0].name == "id"
    finally:
        engine.dispose()


def test_source_sha256_and_question_normalized_hash_are_not_unique(tmp_path):
    models = _phase1b_models()
    app = _migrated_app(tmp_path / "duplicate-hashes.sqlite3")
    engine = app.extensions["sqlalchemy_engine"]
    try:
        with Session(engine) as session:
            session.add_all(
                [
                    models.SourceAsset(
                        original_filename=f"same-{index}.png",
                        mime_type="image/png",
                        byte_size=1,
                        original_width=1,
                        original_height=1,
                        display_width=1,
                        display_height=1,
                        original_path=f"sources/{index}/original.bin",
                        display_preview_path=f"sources/{index}/display.png",
                        sha256="b" * 64,
                    )
                    for index in range(2)
                ]
            )
            session.add_all([_question(), _question(text="Second duplicate?")])
            session.commit()
            assert session.scalar(
                select(models.SourceAsset.sha256).limit(1)
            ) == "b" * 64
            assert session.query(models.SourceAsset).filter_by(sha256="b" * 64).count() == 2
            assert session.query(Question).filter_by(normalized_hash="same-hash").count() == 2
    finally:
        engine.dispose()


def test_source_storage_root_is_under_configured_app_data_dir(tmp_path, monkeypatch):
    import app.config as config

    configured_root = tmp_path / "custom-local-data"
    monkeypatch.setenv("APP_DATA_DIR", str(configured_root))
    assert config.default_source_storage_dir() == configured_root / "sources"
