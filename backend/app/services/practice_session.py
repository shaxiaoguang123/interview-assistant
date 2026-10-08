from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.errors import ApiError
from app.models.practice import PracticeSession, SessionItem
from app.repositories import practice as practice_repository


TERMINAL_ITEM_STATUSES = {"completed", "skipped"}


def mark_session_completed_if_terminal(session: Session, practice_session: PracticeSession) -> None:
    if practice_session.completed_at is not None:
        return
    statuses = practice_repository.get_session_item_statuses(session, practice_session.id)
    if all(status in TERMINAL_ITEM_STATUSES for status in statuses):
        practice_session.completed_at = datetime.now(timezone.utc)


def skip_session_item(session: Session, session_item_id: int) -> tuple[SessionItem, PracticeSession]:
    with session.begin():
        item = practice_repository.get_session_item(session, session_item_id)
        if item is None:
            raise ApiError(404, "NOT_FOUND", "Session item not found")
        practice_session = practice_repository.get_practice_session(session, item.session_id)
        if practice_session is None:
            raise ApiError(404, "NOT_FOUND", "Practice session not found")
        if practice_session.completed_at is not None:
            raise ApiError(409, "CONFLICT", "Practice session is already complete")
        if item.status != "shown":
            raise ApiError(409, "CONFLICT", "Session item is already in a terminal state")

        now = datetime.now(timezone.utc)
        if not practice_repository.transition_shown_session_item(
            session, item.id, status="skipped", completed_at=now
        ):
            raise ApiError(409, "CONFLICT", "SessionItem has already reached a terminal state")
        item.status = "skipped"
        item.completed_at = now
        session.flush()
        mark_session_completed_if_terminal(session, practice_session)
        session.flush()
    return item, practice_session
