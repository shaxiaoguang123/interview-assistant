from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.models.practice import PracticeReview
from app.models.taxonomy import utc_now
from app.repositories import practice as practice_repository
from app.services.practice_session import mark_session_completed_if_terminal
from app.services.questions import get_question
from app.services.question_relations import _begin_write


REVIEW_RATINGS = {"dont_know", "vague", "basic", "proficient"}


def _validate_rating(value: object) -> str:
    if not isinstance(value, str) or value not in REVIEW_RATINGS:
        raise ApiError(
            400,
            "VALIDATION_ERROR",
            "Invalid PracticeReview rating",
            {"review_rating": "Choose dont_know, vague, basic, or proficient"},
        )
    return value


def record_practice_review(session: Session, session_item_id: int, review_rating: str, saved_answer_version_id: int | None = None) -> PracticeReview:
    rating = _validate_rating(review_rating)
    try:
        with session.begin():
            _begin_write(session)
            item = practice_repository.get_session_item(session, session_item_id)
            if item is None:
                raise ApiError(404, "NOT_FOUND", "Session item not found")
            practice_session = practice_repository.get_practice_session(session, item.session_id)
            if practice_session is None:
                raise ApiError(404, "NOT_FOUND", "Practice session not found")
            if practice_session.completed_at is not None:
                raise ApiError(409, "CONFLICT", "Practice session is already complete")
            if item.status == "skipped":
                raise ApiError(409, "CONFLICT", "Skipped SessionItem cannot be reviewed")
            if item.status == "completed":
                raise ApiError(409, "CONFLICT", "Completed SessionItem cannot be reviewed again")
            if item.status != "shown":
                raise ApiError(409, "CONFLICT", "SessionItem is not available for review")

            if saved_answer_version_id is not None:
                from app.services.saved_answers import validate_review_version
                validate_review_version(session, item.question_id, saved_answer_version_id)

            now = utc_now()
            if not practice_repository.transition_shown_session_item(
                session, item.id, status="completed", completed_at=now
            ):
                raise ApiError(409, "CONFLICT", "SessionItem has already reached a terminal state")
            item.status = "completed"
            item.completed_at = now
            review = PracticeReview(
                question_id=item.question_id,
                session_item_id=item.id,
                review_rating=rating,
                saved_answer_version_id=saved_answer_version_id,
                reviewed_at=now,
                created_at=now,
                updated_at=now,
            )
            practice_repository.add_practice_review(session, review)
            mark_session_completed_if_terminal(session, practice_session)
            session.flush()
        return review
    except IntegrityError as error:
        raise ApiError(409, "CONFLICT", "SessionItem already has a PracticeReview") from error


def update_practice_review_rating(session: Session, review_id: int, payload: dict) -> PracticeReview:
    if not isinstance(payload, dict) or set(payload) != {"review_rating"}:
        raise ApiError(
            400,
            "VALIDATION_ERROR",
            "Only review_rating can be corrected",
            {"body": "PATCH accepts exactly review_rating"},
        )
    rating = _validate_rating(payload["review_rating"])
    with session.begin():
        review = practice_repository.get_practice_review(session, review_id)
        if review is None:
            raise ApiError(404, "NOT_FOUND", "PracticeReview not found")
        if review.review_rating != rating:
            review.review_rating = rating
            review.updated_at = datetime.now(timezone.utc)
            session.flush()
    return review


def get_question_practice_reviews(session: Session, question_id: int) -> list[PracticeReview]:
    get_question(session, question_id)
    return practice_repository.list_question_practice_reviews(session, question_id)
