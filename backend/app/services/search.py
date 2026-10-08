from __future__ import annotations

import re

from sqlalchemy.orm import Session

from app.errors import ApiError
from app.repositories import questions as question_repository
from app.services.questions import normalize_question_text
from app.services.taxonomy import validate_active_tag_ids, validate_active_topic_ids


_QUERY_TOKEN = re.compile(r"[a-z0-9]+(?:[+#.-][a-z0-9+#.-]*)*|[\u3400-\u9fff]+")


def split_search_terms(query: str) -> tuple[list[str], list[str]]:
    normalized = normalize_question_text(query)
    tokens = list(dict.fromkeys(_QUERY_TOKEN.findall(normalized)))
    if not tokens and normalized:
        return [], [normalized]

    fts_terms: list[str] = []
    substring_terms: list[str] = []
    for token in tokens:
        if token.isascii() and token.isalnum() and len(token) >= 4:
            fts_terms.append(token)
        else:
            substring_terms.append(token)
    return fts_terms, substring_terms


def search_questions(session: Session, query: str, filters: dict) -> list:
    if not isinstance(query, str):
        raise ApiError(400, "VALIDATION_ERROR", "Invalid search query", {"q": "Must be text"})
    normalized_query = normalize_question_text(query)

    topic_ids = filters.get("topic_ids")
    tag_ids = filters.get("tag_ids")
    if topic_ids is not None:
        topic_ids = [topic.id for topic in validate_active_topic_ids(session, topic_ids)]
    if tag_ids is not None:
        tag_ids = [tag.id for tag in validate_active_tag_ids(session, tag_ids)]

    include_archived = filters.get("include_archived", False)
    is_favorite = filters.get("is_favorite")
    is_wrong = filters.get("is_wrong")
    if not isinstance(include_archived, bool):
        raise ApiError(400, "VALIDATION_ERROR", "Invalid question filter", {"include_archived": "Must be a boolean"})
    for field, value in (("is_favorite", is_favorite), ("is_wrong", is_wrong)):
        if value is not None and not isinstance(value, bool):
            raise ApiError(400, "VALIDATION_ERROR", "Invalid question filter", {field: "Must be a boolean"})

    if not normalized_query:
        return question_repository.list_questions(
            session,
            include_archived=include_archived,
            topic_ids=topic_ids,
            tag_ids=tag_ids,
            is_favorite=is_favorite,
            is_wrong=is_wrong,
        )

    fts_terms, substring_terms = split_search_terms(normalized_query)
    fts_query = " AND ".join(f'"{term}"' for term in fts_terms) or None
    return question_repository.search_question_rows(
        session,
        fts_query=fts_query,
        substring_terms=substring_terms,
        include_archived=include_archived,
        topic_ids=topic_ids,
        tag_ids=tag_ids,
        is_favorite=is_favorite,
        is_wrong=is_wrong,
    )
