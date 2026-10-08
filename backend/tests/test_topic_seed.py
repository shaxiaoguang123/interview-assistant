from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session

from app import create_app


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _app_after_upgrade(database_path: Path):
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
            "SEED_TOPICS_ON_STARTUP": True,
        }
    )
    return app


def test_initial_topic_seed_is_idempotent_across_app_restarts(tmp_path):
    model_path = BACKEND_ROOT / "app" / "models" / "taxonomy.py"
    assert model_path.is_file(), "missing feature: SQLAlchemy Topic model"
    from app.models.taxonomy import Topic

    database_path = tmp_path / "topic-seed.sqlite3"
    first_app = _app_after_upgrade(database_path)
    factory = first_app.extensions["sqlalchemy_session_factory"]
    with factory() as session:
        initial_count = session.scalar(select(func.count()).select_from(Topic))
        assert initial_count > 0
        prompt_topic = session.scalar(select(Topic).where(Topic.slug == "prompt"))
        assert prompt_topic is not None
        prompt_topic.name = "Prompt user edit"
        session.commit()
    first_app.extensions["sqlalchemy_engine"].dispose()

    second_app = _app_after_upgrade(database_path)
    second_factory = second_app.extensions["sqlalchemy_session_factory"]
    with second_factory() as session:
        restarted_count = session.scalar(select(func.count()).select_from(Topic))
        prompt_topic = session.scalar(select(Topic).where(Topic.slug == "prompt"))
        all_slugs = set(session.scalars(select(Topic.slug)).all())
    second_app.extensions["sqlalchemy_engine"].dispose()

    assert restarted_count == initial_count
    assert prompt_topic.name == "Prompt user edit"
    assert {
        "llm-basics",
        "prompt",
        "structured-output",
        "context-engineering",
        "function-calling-tool-use",
        "mcp",
        "rag",
        "memory",
        "langchain",
        "langgraph",
        "multi-agent",
        "agent-design-patterns",
        "agent-evaluation",
        "observability",
        "agent-security",
        "deployment",
        "python-backend",
        "project-practice",
    } <= all_slugs
