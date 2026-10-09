from __future__ import annotations

import hashlib
import unicodedata
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.models.question import Question, QuestionState
from app.repositories import questions as question_repository
from app.services.question_similarity import (
    invalidate_unmerged_question_relations,
    refresh_rule_suggestions,
)
from app.services.taxonomy import validate_active_tag_ids, validate_active_topic_ids
from app.services.question_relations import _begin_write


MAX_QUESTION_TEXT_LENGTH = 10_000
_PUNCTUATION_TRANSLATION = str.maketrans(
    {
        "。": ".",
        "，": ",",
        "、": ",",
        "；": ";",
        "：": ":",
        "？": "?",
        "！": "!",
        "“": '"',
        "”": '"',
        "‘": "'",
        "’": "'",
    }
)


def normalize_question_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold().translate(_PUNCTUATION_TRANSLATION)
    return " ".join(normalized.split())


def prepare_question_text(value: object) -> tuple[str, str, str]:
    if not isinstance(value, str):
        raise ApiError(400, "VALIDATION_ERROR", "Invalid question", {"text": "Question text is required"})
    text = value.strip()
    if not text:
        raise ApiError(400, "VALIDATION_ERROR", "Invalid question", {"text": "Question text is required"})
    if len(text) > MAX_QUESTION_TEXT_LENGTH:
        raise ApiError(
            400,
            "VALIDATION_ERROR",
            "Invalid question",
            {"text": f"Question text must be at most {MAX_QUESTION_TEXT_LENGTH} characters"},
        )
    normalized = normalize_question_text(text)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return text, normalized, digest


def _optional_text(payload: dict, field: str) -> str | None:
    if field not in payload or payload[field] is None:
        return None
    value = payload[field]
    if not isinstance(value, str):
        raise ApiError(400, "VALIDATION_ERROR", f"Invalid {field}", {field: "Must be text"})
    value = value.strip()
    return value or None


def create_question(session: Session, payload: dict) -> Question:
    if not isinstance(payload, dict):
        raise ApiError(400, "VALIDATION_ERROR", "Invalid question", {"body": "Expected a JSON object"})
    allowed = {"text", "answer_type", "difficulty", "topic_ids", "tag_ids"}
    unknown = set(payload) - allowed
    if unknown:
        raise ApiError(400, "VALIDATION_ERROR", "Invalid question", {"body": f"Unsupported fields: {', '.join(sorted(unknown))}"})

    text, normalized, digest = prepare_question_text(payload.get("text"))
    answer_type = _optional_text(payload, "answer_type")
    difficulty = _optional_text(payload, "difficulty")
    try:
        with session.begin():
            topics = validate_active_topic_ids(session, payload.get("topic_ids", []))
            tags = validate_active_tag_ids(session, payload.get("tag_ids", []))
            question = Question(
                text=text,
                normalized_text=normalized,
                search_text=normalized,
                normalized_hash=digest,
                answer_type=answer_type,
                difficulty=difficulty,
                status="active",
                archived_at=None,
                state=QuestionState(is_favorite=False, is_wrong=False),
            )
            question_repository.add_question(
                session,
                question,
                [topic.id for topic in topics],
                [tag.id for tag in tags],
            )
            refresh_rule_suggestions(session, question.id)
        return question
    except IntegrityError as error:
        raise ApiError(409, "CONFLICT", "Question could not be saved") from error


def _reject_generic_ocr_candidate_operation(question: Question) -> None:
    if question.status == "merged" or question.merged_into_question_id is not None:
        raise ApiError(
            409, "CONFLICT", "Merged child is read-only; open the canonical Question",
            {"canonical_question_id": str(question.merged_into_question_id)},
        )
    if question.status == "pending_review" or (
        question.origin_ingestion_job_id is not None
        and question.ingestion_candidate_state != "confirmed"
    ):
        raise ApiError(
            409,
            "CONFLICT",
            "Unconfirmed OCR candidates must be changed through the candidate review API",
        )


def update_question(session: Session, question_id: int, payload: dict) -> Question:
    if not isinstance(payload, dict) or not payload:
        raise ApiError(400, "VALIDATION_ERROR", "Invalid question update", {"body": "Expected a non-empty JSON object"})
    allowed = {"text", "answer_type", "difficulty", "topic_ids", "tag_ids"}
    unknown = set(payload) - allowed
    if unknown:
        raise ApiError(400, "VALIDATION_ERROR", "Invalid question update", {"body": f"Unsupported fields: {', '.join(sorted(unknown))}"})

    try:
        with session.begin():
            _begin_write(session)
            question = question_repository.get_question(session, question_id)
            if question is None:
                raise ApiError(404, "NOT_FOUND", "Question not found")
            _reject_generic_ocr_candidate_operation(question)
            text_changed = False
            if "text" in payload:
                text, normalized, digest = prepare_question_text(payload["text"])
                text_changed = question.text != text
                question.text = text
                question.normalized_text = normalized
                question.search_text = normalized
                question.normalized_hash = digest
            if "answer_type" in payload:
                question.answer_type = _optional_text(payload, "answer_type")
            if "difficulty" in payload:
                question.difficulty = _optional_text(payload, "difficulty")
            if "topic_ids" in payload:
                topics = validate_active_topic_ids(session, payload["topic_ids"])
                question_repository.replace_question_topics(
                    session, question_id, [topic.id for topic in topics]
                )
            if "tag_ids" in payload:
                tags = validate_active_tag_ids(session, payload["tag_ids"])
                question_repository.replace_question_tags(session, question_id, [tag.id for tag in tags])
            session.flush()
            if text_changed:
                refresh_rule_suggestions(session, question.id)
            if "topic_ids" in payload:
                session.expire(question, ["topic_links"])
            if "tag_ids" in payload:
                session.expire(question, ["tag_links"])
        return question_repository.get_question(session, question_id) or question
    except IntegrityError as error:
        raise ApiError(409, "CONFLICT", "Question could not be updated") from error


def get_question(session: Session, question_id: int) -> Question:
    question = question_repository.get_question(session, question_id)
    if question is None:
        raise ApiError(404, "NOT_FOUND", "Question not found")
    return question


def list_questions(
    session: Session,
    *,
    include_archived: bool = False,
    topic_ids: list[int] | None = None,
    tag_ids: list[int] | None = None,
    is_favorite: bool | None = None,
    is_wrong: bool | None = None,
) -> list[Question]:
    topics = validate_active_topic_ids(session, topic_ids) if topic_ids is not None else []
    tags = validate_active_tag_ids(session, tag_ids) if tag_ids is not None else []
    return question_repository.list_questions(
        session,
        include_archived=include_archived,
        topic_ids=[topic.id for topic in topics],
        tag_ids=[tag.id for tag in tags],
        is_favorite=is_favorite,
        is_wrong=is_wrong,
    )


def archive_question(session: Session, question_id: int) -> Question:
    try:
        with session.begin():
            _begin_write(session)
            question = question_repository.get_question(session, question_id)
            if question is None:
                raise ApiError(404, "NOT_FOUND", "Question not found")
            _reject_generic_ocr_candidate_operation(question)
            if question.archived_at is None:
                question.archived_at = datetime.now(timezone.utc)
            session.flush()
            invalidate_unmerged_question_relations(session, question.id)
        return question_repository.get_question(session, question_id) or question
    except IntegrityError as error:
        raise ApiError(409, "CONFLICT", "Question could not be archived") from error


def update_question_state(session: Session, question_id: int, payload: dict) -> QuestionState:
    if not isinstance(payload, dict) or not payload:
        raise ApiError(400, "VALIDATION_ERROR", "Invalid question state", {"body": "Expected a non-empty JSON object"})
    allowed = {"is_favorite", "is_wrong"}
    unknown = set(payload) - allowed
    if unknown:
        raise ApiError(400, "VALIDATION_ERROR", "Invalid question state", {"body": f"Unsupported fields: {', '.join(sorted(unknown))}"})
    for field, value in payload.items():
        if not isinstance(value, bool):
            raise ApiError(400, "VALIDATION_ERROR", "Invalid question state", {field: "Must be a boolean"})

    with session.begin():
        _begin_write(session)
        question = question_repository.get_question(session, question_id)
        if question is None:
            raise ApiError(404, "NOT_FOUND", "Question not found")
        _reject_generic_ocr_candidate_operation(question)
        if question.state is None:
            question.state = QuestionState(is_favorite=False, is_wrong=False)
        for field, value in payload.items():
            setattr(question.state, field, value)
        session.flush()
    return question.state
