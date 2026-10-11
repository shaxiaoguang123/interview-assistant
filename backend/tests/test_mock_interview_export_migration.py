from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.engine import URL

from app import create_app
from app.models.mock_interview import MockInterviewAnswerExport, MockInterviewSession, MockInterviewTurn
from app.models.practice import PracticeReview, PracticeSession, SessionItem
from app.models.question import QuestionState
from app.models.saved_answer import SavedAnswer, SavedAnswerVersion


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _migration_config(database_path: Path) -> Config:
    database_url = URL.create("sqlite", database=str(database_path)).render_as_string(hide_password=False)
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def test_0008_to_0009_preserves_interview_answers_and_practice_history(tmp_path):
    database_path = tmp_path / "phase8.sqlite3"
    config = _migration_config(database_path)
    command.upgrade(config, "0008_mock_interview")
    database_url = URL.create("sqlite", database=str(database_path)).render_as_string(hide_password=False)
    app = create_app({
        "TESTING": True,
        "APP_DATA_DIR": tmp_path / "app-data",
        "DATABASE_URL": database_url,
        "SEED_TOPICS_ON_STARTUP": False,
    })
    client = app.test_client()
    question = client.post("/api/v1/questions", json={"text": "Synthetic migration question"}).get_json()
    saved_answer = client.post(
        f"/api/v1/questions/{question['id']}/saved-answers",
        json={"content": "Existing answer before migration", "self_rating": 4},
    ).get_json()
    practice = client.post("/api/v1/practice-sessions", json={"mode": "random", "limit": 1}).get_json()
    item = practice["items"][0]
    review = client.post(
        f"/api/v1/session-items/{item['id']}/review",
        json={"review_rating": "basic"},
    ).get_json()
    mock = client.post("/api/v1/mock-interviews", json={
        "topic_id": None,
        "question_count": 1,
        "context": {"project_ids": [], "material_ids": [], "exclude_material_ids": []},
    }).get_json()
    ended = client.post(
        f"/api/v1/mock-interviews/{mock['id']}/finish",
        json={"answer": "A pre-migration user answer.", "expected_revision": mock["revision"]},
    )
    assert ended.status_code == 200
    record = client.post(f"/api/v1/mock-interviews/{mock['id']}/save", json={"title": "Before migration"}).get_json()["record"]
    session_factory = app.extensions["sqlalchemy_session_factory"]
    with session_factory() as session:
        record_row = session.get(MockInterviewSession, record["id"])
        turn_ids = list(session.scalars(select(MockInterviewTurn.id).where(MockInterviewTurn.session_id == record["id"])))
        review_before = session.get(PracticeReview, review["id"])
        schedule_before = session.get(QuestionState, question["id"])
        history_ids = {
            "session": record_row.id,
            "turns": turn_ids,
            "answer": saved_answer["id"],
            "answer_version": saved_answer["current_version"]["id"],
            "practice_session": session.get(PracticeSession, practice["id"]).id,
            "session_item": session.get(SessionItem, item["id"]).id,
            "review": review_before.id,
            "review_rating": review_before.review_rating,
            "reviewed_at": review_before.reviewed_at,
            "next_review_at": schedule_before.next_review_at,
        }

    command.upgrade(config, "head")
    turn_id = next(turn["id"] for turn in record["turns"] if turn["kind"] == "answer")
    exported = client.post(
        f"/api/v1/mock-interviews/saved/{record['id']}/answers/{turn_id}/export",
        json={"save_mode": "append_version", "saved_answer_id": saved_answer["id"], "content": "Post-migration improved answer", "self_rating": None},
    )
    assert exported.status_code == 201, exported.get_json()
    assert exported.get_json()["version"]["version_no"] == 2

    with session_factory() as session:
        assert session.get(MockInterviewSession, history_ids["session"]).id == history_ids["session"]
        assert list(session.scalars(select(MockInterviewTurn.id).where(MockInterviewTurn.session_id == history_ids["session"]))) == history_ids["turns"]
        assert session.get(SavedAnswer, history_ids["answer"]).id == history_ids["answer"]
        assert session.get(SavedAnswerVersion, history_ids["answer_version"]).id == history_ids["answer_version"]
        assert session.get(PracticeSession, history_ids["practice_session"]).id == history_ids["practice_session"]
        assert session.get(SessionItem, history_ids["session_item"]).id == history_ids["session_item"]
        review_after = session.get(PracticeReview, history_ids["review"])
        schedule_after = session.get(QuestionState, question["id"])
        assert review_after.review_rating == history_ids["review_rating"]
        assert review_after.reviewed_at == history_ids["reviewed_at"]
        assert schedule_after.next_review_at == history_ids["next_review_at"]
        assert session.query(MockInterviewAnswerExport).count() == 1
        assert session.query(PracticeReview).count() == 1
        assert session.query(SessionItem).count() == 1

    with app.extensions["sqlalchemy_engine"].begin() as connection:
        with pytest.raises(IntegrityError):
            connection.exec_driver_sql(
                "UPDATE saved_answer_version SET content='must remain immutable' WHERE id=?",
                (history_ids["answer_version"],),
            )
    app.extensions["sqlalchemy_engine"].dispose()
