from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.practice import PracticeSession, SessionItem
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


def get_session_item_statuses(session: Session, session_id: int) -> list[str]:
    statement = select(SessionItem.status).where(SessionItem.session_id == session_id)
    return list(session.scalars(statement).all())
