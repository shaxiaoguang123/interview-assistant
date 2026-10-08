from importlib import import_module, util
from pathlib import Path

import pytest
from sqlalchemy import event, select

from app.models.practice import PracticeReview, PracticeSession, SessionItem
from app.models.question import Question, QuestionState
from app.services.questions import prepare_question_text


def _review_service():
    service_path = Path(__file__).resolve().parents[2] / "app" / "services" / "practice_review.py"
    assert service_path.is_file(), "missing feature: PracticeReview service"
    assert util.find_spec("app.services.practice_review") is not None
    return import_module("app.services.practice_review").record_practice_review


def _create_shown_item(session):
    raw, normalized, digest = prepare_question_text("Atomic review question")
    question = Question(
        text=raw,
        normalized_text=normalized,
        search_text=normalized,
        normalized_hash=digest,
        state=QuestionState(is_favorite=False, is_wrong=False),
    )
    practice_session = PracticeSession(mode="random", filters_json={}, selector_version="v1")
    session.add_all([question, practice_session])
    session.flush()
    item = SessionItem(
        session_id=practice_session.id,
        question_id=question.id,
        ordinal=1,
        status="shown",
    )
    session.add(item)
    session.commit()
    return practice_session, item


def test_review_insert_failure_rolls_back_item_completion(db_session):
    record_review = _review_service()
    practice_session, item = _create_shown_item(db_session)

    def fail_when_review_is_added(session, _flush_context, _instances):
        if any(isinstance(row, PracticeReview) for row in session.new):
            raise RuntimeError("injected PracticeReview insert failure")

    event.listen(db_session, "before_flush", fail_when_review_is_added)
    try:
        with pytest.raises(RuntimeError, match="injected PracticeReview insert failure"):
            record_review(db_session, item.id, "basic")
    finally:
        event.remove(db_session, "before_flush", fail_when_review_is_added)
        db_session.rollback()

    db_session.expire_all()
    assert db_session.get(SessionItem, item.id).status == "shown"
    assert db_session.get(PracticeSession, practice_session.id).completed_at is None
    assert db_session.scalar(
        select(PracticeReview.id).where(PracticeReview.session_item_id == item.id)
    ) is None
