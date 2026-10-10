"""Derived canonical review state. Only real mastery events drive scheduling."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.practice import PracticeReview
from app.models.question import Question, QuestionState
from app.repositories.questions import canonical_member_ids

REVIEW_INTERVAL_DAYS = {"dont_know": 1, "vague": 2, "basic": 7, "proficient": 14}


def as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def next_review_time(reviewed_at: datetime, rating: str) -> datetime:
    return as_utc(reviewed_at) + timedelta(days=REVIEW_INTERVAL_DAYS[rating])


def recompute_review_schedule(session: Session, question_id: int) -> QuestionState:
    question = session.get(Question, question_id)
    root_id = question.merged_into_question_id or question.id
    members = canonical_member_ids(session, root_id)
    latest = session.scalar(select(PracticeReview).where(PracticeReview.question_id.in_(members))
        .order_by(PracticeReview.reviewed_at.desc(), PracticeReview.id.desc()).limit(1))
    state = session.get(QuestionState, root_id)
    if state is None:
        state = QuestionState(question_id=root_id)
        session.add(state)
    state.last_reviewed_at = as_utc(latest.reviewed_at) if latest else None
    state.last_review_rating = latest.review_rating if latest else None
    state.next_review_at = next_review_time(latest.reviewed_at, latest.review_rating) if latest else None
    # Original flags and notes stay with each historical question; children have no schedule.
    for child in session.scalars(select(QuestionState).where(
        QuestionState.question_id.in_([qid for qid in members if qid != root_id]))):
        child.last_reviewed_at = child.last_review_rating = child.next_review_at = None
    session.flush()
    return state


def schedule_json(state: QuestionState | None, *, now: datetime | None = None) -> dict:
    now = as_utc(now or datetime.now(timezone.utc))
    def stamp(value):
        return as_utc(value).isoformat() if value is not None else None
    due = state.next_review_at if state else None
    return {
        "last_reviewed_at": stamp(state.last_reviewed_at) if state else None,
        "last_review_rating": state.last_review_rating if state else None,
        "next_review_at": stamp(due),
        "is_due": due is not None and as_utc(due) <= now,
    }
