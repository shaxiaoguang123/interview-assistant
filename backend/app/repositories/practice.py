from __future__ import annotations

from datetime import datetime
from typing import Literal

from sqlalchemy import select, update
from sqlalchemy.orm import Session, selectinload

from app.models.practice import PracticeReview, PracticeSession, SessionItem
from app.models.question import Question, QuestionTag, QuestionTopic


def add_practice_session(session: Session, practice_session: PracticeSession) -> PracticeSession:
    session.add(practice_session)
    session.flush()
    return practice_session


def add_session_items(session: Session, items: list[SessionItem]) -> None:
    session.add_all(items)
    session.flush()


def get_practice_session(session: Session, session_id: int) -> PracticeSession | None:
    statement = (
        select(PracticeSession)
        .options(
            selectinload(PracticeSession.items)
            .selectinload(SessionItem.question)
            .selectinload(Question.topic_links)
            .selectinload(QuestionTopic.topic),
            selectinload(PracticeSession.items)
            .selectinload(SessionItem.question)
            .selectinload(Question.tag_links)
            .selectinload(QuestionTag.tag),
            selectinload(PracticeSession.items)
            .selectinload(SessionItem.question)
            .selectinload(Question.state),
        )
        .where(PracticeSession.id == session_id)
    )
    return session.scalar(statement)


def get_session_item(session: Session, session_item_id: int) -> SessionItem | None:
    return session.get(SessionItem, session_item_id)


def transition_shown_session_item(
    session: Session,
    session_item_id: int,
    *,
    status: Literal["completed", "skipped"],
    completed_at: datetime,
) -> bool:
    result = session.execute(
        update(SessionItem)
        .where(SessionItem.id == session_item_id, SessionItem.status == "shown")
        .values(status=status, completed_at=completed_at)
        .execution_options(synchronize_session=False)
    )
    return result.rowcount == 1


def get_session_item_statuses(session: Session, session_id: int) -> list[str]:
    statement = select(SessionItem.status).where(SessionItem.session_id == session_id)
    return list(session.scalars(statement).all())


def add_practice_review(session: Session, review: PracticeReview) -> PracticeReview:
    session.add(review)
    session.flush()
    return review


def get_practice_review(session: Session, review_id: int) -> PracticeReview | None:
    return session.get(PracticeReview, review_id)


def list_question_practice_reviews(session: Session, question_id: int) -> list[PracticeReview]:
    statement = (
        select(PracticeReview)
        .where(PracticeReview.question_id == question_id)
        .order_by(PracticeReview.reviewed_at.desc(), PracticeReview.id.desc())
    )
    return list(session.scalars(statement).all())
