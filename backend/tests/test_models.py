from importlib import import_module, util
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, inspect, select
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session

from app import create_app


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _model_module():
    model_path = BACKEND_ROOT / "app" / "models" / "question.py"
    assert model_path.is_file(), "missing feature: SQLAlchemy Question model"
    assert util.find_spec("app.models.question") is not None, "Question model is not importable"
    return import_module("app.models.question")


def _migrated_app(database_path: Path):
    alembic_ini = BACKEND_ROOT / "alembic.ini"
    assert alembic_ini.is_file(), "missing feature: backend/alembic.ini"
    database_url = URL.create("sqlite", database=str(database_path)).render_as_string(hide_password=False)
    config = Config(str(alembic_ini))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": database_url,
            "SEED_TOPICS_ON_STARTUP": False,
        }
    )
    return app


def test_duplicate_normalized_hash_is_allowed(tmp_path):
    question_module = _model_module()
    app = _migrated_app(tmp_path / "duplicate-hash.sqlite3")
    engine = app.extensions["sqlalchemy_engine"]
    try:
        with Session(engine) as session:
            session.add_all(
                [
                    question_module.Question(
                        text="MCP 通信协议是什么？",
                        normalized_text="mcp 通信协议是什么?",
                        search_text="mcp 通信协议是什么?",
                        normalized_hash="same-normalized-hash",
                    ),
                    question_module.Question(
                        text="MCP 通信协议是什么？",
                        normalized_text="mcp 通信协议是什么?",
                        search_text="mcp 通信协议是什么?",
                        normalized_hash="same-normalized-hash",
                    ),
                ]
            )
            session.commit()
            count = session.scalar(
                select(func.count()).select_from(question_module.Question).where(
                    question_module.Question.normalized_hash == "same-normalized-hash"
                )
            )
        assert count == 2
    finally:
        engine.dispose()


def test_normalized_hash_index_is_not_unique(tmp_path):
    _model_module()
    app = _migrated_app(tmp_path / "hash-index.sqlite3")
    engine = app.extensions["sqlalchemy_engine"]
    try:
        indexes = inspect(engine).get_indexes("question")
    finally:
        engine.dispose()

    hash_indexes = [index for index in indexes if index["column_names"] == ["normalized_hash"]]
    assert hash_indexes
    assert all(not index.get("unique", False) for index in hash_indexes)
