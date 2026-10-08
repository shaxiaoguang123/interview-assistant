from importlib import import_module, util
from pathlib import Path

import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import sessionmaker

from app.errors import ApiError
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


@pytest.mark.parametrize("first_action", ["review", "skip"])
def test_stale_competing_terminal_transition_is_rejected(db_session, first_action):
    from app.services.practice_review import record_practice_review
    from app.services.practice_session import skip_session_item

    practice_session, item = _create_shown_item(db_session)
    raw, normalized, digest = prepare_question_text("Keep the parent session open")
    other_question = Question(
        text=raw,
        normalized_text=normalized,
        search_text=normalized,
        normalized_hash=digest,
        state=QuestionState(is_favorite=False, is_wrong=False),
    )
    db_session.add(other_question)
    db_session.flush()
    db_session.add(
        SessionItem(
            session_id=practice_session.id,
            question_id=other_question.id,
            ordinal=2,
            status="shown",
        )
    )
    db_session.commit()

    session_factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    first_session = session_factory()
    stale_session = session_factory()
    try:
        first_item = first_session.get(SessionItem, item.id)
        stale_item = stale_session.get(SessionItem, item.id)
        first_session.commit()
        stale_session.commit()
        assert first_item.status == "shown"
        assert stale_item.status == "shown"

        if first_action == "review":
            record_practice_review(first_session, item.id, "basic")
            competing_transition = lambda: skip_session_item(stale_session, item.id)
            expected_status = "completed"
            expected_review_count = 1
        else:
            skip_session_item(first_session, item.id)
            competing_transition = lambda: record_practice_review(stale_session, item.id, "basic")
            expected_status = "skipped"
            expected_review_count = 0

        with pytest.raises(ApiError) as error:
            competing_transition()
        assert error.value.status_code == 409

        with session_factory() as verification_session:
            stored_item = verification_session.get(SessionItem, item.id)
            review_count = verification_session.scalar(
                select(PracticeReview.id).where(PracticeReview.session_item_id == item.id)
            )
        assert stored_item.status == expected_status
        assert (review_count is not None) is (expected_review_count == 1)
    finally:
        first_session.close()
        stale_session.close()
