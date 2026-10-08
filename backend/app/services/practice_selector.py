from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.errors import ApiError
from app.models.practice import PracticeSession, SessionItem
from app.repositories import practice as practice_repository
from app.services.questions import list_questions


SELECTOR_VERSION = "v1"
DEFAULT_SESSION_SIZE = 10
MAX_SESSION_SIZE = 100
MAX_SELECTION_SEED = (2**32) - 1


def _valid_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _rank_random_question(question_id: int, seed: int) -> bytes:
    value = f"{SELECTOR_VERSION}:{seed}:{question_id}".encode("utf-8")
    return hashlib.sha256(value).digest()


def _validate_filters(mode: str, filters: object) -> tuple[dict, list[int], list[int]]:
    if not isinstance(mode, str) or mode not in {"random", "topic", "tag"}:
        raise ApiError(400, "VALIDATION_ERROR", "Invalid practice mode", {"mode": "Unknown mode"})
    if not isinstance(filters, dict):
        raise ApiError(400, "VALIDATION_ERROR", "Invalid practice filters", {"filters": "Must be an object"})

    allowed = {"topic_ids"} if mode == "topic" else {"tag_ids"} if mode == "tag" else set()
    unknown = set(filters) - allowed
    if unknown:
        raise ApiError(
            400,
            "VALIDATION_ERROR",
            "Invalid practice filters",
            {"filters": f"Unsupported filters for {mode}: {', '.join(sorted(unknown))}"},
        )

    topic_ids = filters.get("topic_ids", [])
    tag_ids = filters.get("tag_ids", [])
    if mode == "topic" and not topic_ids:
        raise ApiError(400, "VALIDATION_ERROR", "Topic practice needs a Topic", {"topic_ids": "Select at least one active Topic"})
    if mode == "tag" and not tag_ids:
        raise ApiError(400, "VALIDATION_ERROR", "Tag practice needs a Tag", {"tag_ids": "Select at least one active Tag"})
    if not isinstance(topic_ids, list) or not isinstance(tag_ids, list):
        raise ApiError(400, "VALIDATION_ERROR", "Invalid practice filters", {"filters": "IDs must be lists"})
    for field, values in (("topic_ids", topic_ids), ("tag_ids", tag_ids)):
        if any(not _valid_integer(value) or value <= 0 for value in values):
            raise ApiError(400, "VALIDATION_ERROR", "Invalid practice filters", {field: "IDs must be positive integers"})
    return filters, topic_ids, tag_ids


def _validate_limit(limit: object) -> int:
    if not _valid_integer(limit) or not 1 <= limit <= MAX_SESSION_SIZE:
        raise ApiError(
            400,
            "VALIDATION_ERROR",
            "Invalid practice limit",
            {"limit": f"Must be an integer from 1 to {MAX_SESSION_SIZE}"},
        )
    return limit


def _validate_seed(mode: str, selection_seed: object) -> int | None:
    if mode != "random":
        if selection_seed is not None:
            raise ApiError(400, "VALIDATION_ERROR", "Invalid selection seed", {"selection_seed": "Only random mode accepts a seed"})
        return None
    if selection_seed is None:
        return secrets.randbits(32)
    if not _valid_integer(selection_seed) or not 0 <= selection_seed <= MAX_SELECTION_SEED:
        raise ApiError(
            400,
            "VALIDATION_ERROR",
            "Invalid selection seed",
            {"selection_seed": f"Must be an integer from 0 to {MAX_SELECTION_SEED}"},
        )
    return selection_seed


def create_practice_session(
    session: Session,
    mode: str,
    filters: dict,
    limit: int = DEFAULT_SESSION_SIZE,
    selection_seed: int | None = None,
) -> PracticeSession:
    validated_limit = _validate_limit(limit)
    validated_filters, topic_ids, tag_ids = _validate_filters(mode, filters)
    seed = _validate_seed(mode, selection_seed)

    with session.begin():
        candidates = list_questions(
            session,
            topic_ids=topic_ids if mode == "topic" else None,
            tag_ids=tag_ids if mode == "tag" else None,
        )
        if mode == "random":
            candidates.sort(key=lambda question: _rank_random_question(question.id, seed))
        else:
            candidates.sort(key=lambda question: question.id)
        selected = candidates[:validated_limit]

        now = datetime.now(timezone.utc)
        practice_session = PracticeSession(
            mode=mode,
            filters_json={key: list(value) for key, value in validated_filters.items()},
            selector_version=SELECTOR_VERSION,
            selection_seed=seed,
            started_at=now,
            completed_at=now if not selected else None,
        )
        practice_repository.add_practice_session(session, practice_session)
        items = [
            SessionItem(
                session_id=practice_session.id,
                question_id=question.id,
                ordinal=ordinal,
                status="shown",
                selection_reason=mode,
                viewed_at=now if ordinal == 1 else None,
            )
            for ordinal, question in enumerate(selected, start=1)
        ]
        practice_repository.add_session_items(session, items)
    return practice_session
