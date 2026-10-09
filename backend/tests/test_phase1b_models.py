from importlib import import_module
from pathlib import Path
import uuid

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, select, text
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


def test_phase1c_question_and_relation_models_are_registered(tmp_path):
    question_models = import_module("app.models.question")
    from app import models as model_package

    assert hasattr(question_models.Question, "merged_into_question_id")
    assert hasattr(question_models, "QuestionRelation")
    assert "QuestionRelation" in model_package.__all__

    app = _migrated_app(tmp_path / "phase1c-schema.sqlite3")
    engine = app.extensions["sqlalchemy_engine"]
    try:
        inspector = inspect(engine)
        question_columns = {
            column["name"] for column in inspector.get_columns("question")
        }
        assert "merged_into_question_id" in question_columns
        assert "question_relation" in inspector.get_table_names()

        with engine.connect() as connection:
            question_fks = connection.exec_driver_sql(
                "PRAGMA foreign_key_list(question)"
            ).all()
            relation_fks = connection.exec_driver_sql(
                "PRAGMA foreign_key_list(question_relation)"
            ).all()
        assert any(
            fk[2] == "question"
            and fk[3] == "merged_into_question_id"
            and fk[6] == "RESTRICT"
            for fk in question_fks
        )
        assert {
            (fk[3], fk[2], fk[6])
            for fk in relation_fks
        } == {
            ("question_id", "question", "RESTRICT"),
            ("related_question_id", "question", "RESTRICT"),
        }

        question_indexes = inspect(engine).get_indexes("question")
        hash_indexes = [
            index for index in question_indexes
            if index["column_names"] == ["normalized_hash"]
        ]
        assert hash_indexes and all(not index.get("unique", False) for index in hash_indexes)
        relation_indexes = inspect(engine).get_indexes("question_relation")
        assert any(
            index["name"] == "ix_question_merged_into_question_id"
            for index in question_indexes
        )
        assert any(
            index["name"] == "ix_question_relation_related_question_id"
            for index in relation_indexes
        )
        assert any(
            constraint["column_names"] == ["question_id", "related_question_id"]
            for constraint in inspect(engine).get_unique_constraints("question_relation")
        )
    finally:
        engine.dispose()


def test_question_merge_pointer_constraints_reject_invalid_states_and_targets(tmp_path):
    _phase1b_models()
    question_model = import_module("app.models.question").Question
    app = _migrated_app(tmp_path / "question-merge-pointer.sqlite3")
    engine = app.extensions["sqlalchemy_engine"]
    try:
        with Session(engine) as session:
            root = _question(id=1, text="Canonical root")
            pending_target = _question(id=2, text="Pending target", status="pending_review")
            archived_target = _question(id=3, text="Archived target")
            archived_target.archived_at = utc_now_for_test()
            merged_target = _question(
                id=4,
                text="Already merged target",
                status="merged",
                merged_into_question_id=1,
            )
            session.add_all([root, pending_target, archived_target, merged_target])
            session.commit()

        invalid_rows = [
            _question(
                id=10,
                text="Active row with pointer",
                status="active",
                merged_into_question_id=1,
            ),
            _question(id=11, text="Merged row without pointer", status="merged"),
            _question(
                id=12,
                text="Self pointer",
                status="merged",
                merged_into_question_id=12,
            ),
            _question(
                id=13,
                text="Missing target",
                status="merged",
                merged_into_question_id=999,
            ),
            _question(
                id=14,
                text="Pending target pointer",
                status="merged",
                merged_into_question_id=2,
            ),
            _question(
                id=15,
                text="Pending target pointer",
                status="merged",
                merged_into_question_id=3,
            ),
            _question(
                id=16,
                text="Merged target pointer",
                status="merged",
                merged_into_question_id=4,
            ),
        ]
        for invalid in invalid_rows:
            with Session(engine) as session:
                session.add(invalid)
                with pytest.raises(IntegrityError):
                    session.flush()
                session.rollback()

        with Session(engine) as session:
            valid_child = _question(
                id=20,
                text="Valid merged child",
                status="merged",
                merged_into_question_id=1,
            )
            session.add(valid_child)
            session.commit()
            assert session.get(question_model, 20).merged_into_question_id == 1

            replacement_root = _question(id=21, text="Replacement root")
            session.add(replacement_root)
            session.commit()
            replacement_root_id = replacement_root.id

            current_root = session.get(question_model, 1)
            current_root.status = "merged"
            current_root.merged_into_question_id = replacement_root_id
            with pytest.raises(IntegrityError):
                session.flush()
            session.rollback()
    finally:
        engine.dispose()


def utc_now_for_test():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)


def test_question_relation_sqlite_constraints_and_bidirectional_relationships(tmp_path):
    question_models = import_module("app.models.question")
    relation_model = getattr(question_models, "QuestionRelation")
    app = _migrated_app(tmp_path / "question-relation-constraints.sqlite3")
    engine = app.extensions["sqlalchemy_engine"]
    try:
        with Session(engine) as session:
            first = _question(id=1, text="First question")
            second = _question(id=2, text="Second question")
            session.add_all([first, second])
            session.commit()

        def insert_relation(
            question_id=1,
            related_question_id=2,
            relation_type="same_question",
            decision_status="suggested",
            suggested_by="rule",
            confidence=1.0,
            left_snapshot="a" * 64,
            right_snapshot="b" * 64,
        ):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO question_relation "
                        "(question_id, related_question_id, relation_type, "
                        "decision_status, suggested_by, confidence, "
                        "question_text_sha256_snapshot, "
                        "related_question_text_sha256_snapshot) "
                        "VALUES (:question_id, :related_question_id, :relation_type, "
                        ":decision_status, :suggested_by, :confidence, "
                        ":left_snapshot, :right_snapshot)"
                    ),
                    {
                        "question_id": question_id,
                        "related_question_id": related_question_id,
                        "relation_type": relation_type,
                        "decision_status": decision_status,
                        "suggested_by": suggested_by,
                        "confidence": confidence,
                        "left_snapshot": left_snapshot,
                        "right_snapshot": right_snapshot,
                    },
                )

        invalid_rows = [
            {"question_id": 1, "related_question_id": 1},
            {"question_id": 2, "related_question_id": 1},
            {"question_id": 999},
            {"related_question_id": 999},
            {"relation_type": "duplicate"},
            {"decision_status": "merged"},
            {"suggested_by": "automatic"},
            {"confidence": -0.01},
            {"confidence": 1.01},
            {"left_snapshot": "not-a-sha256"},
        ]
        for overrides in invalid_rows:
            with pytest.raises(IntegrityError):
                insert_relation(**overrides)

        insert_relation(confidence=None)
        with pytest.raises(IntegrityError):
            insert_relation()

        with Session(engine) as session:
            stored_relation = session.scalar(select(relation_model))
            first = session.get(question_models.Question, 1)
            second = session.get(question_models.Question, 2)
            assert first.relations_as_question == [stored_relation]
            assert second.relations_as_related_question == [stored_relation]
            assert stored_relation.question.id == first.id
            assert stored_relation.related_question.id == second.id
            assert stored_relation.created_at is not None
            assert stored_relation.updated_at is not None
    finally:
        engine.dispose()
