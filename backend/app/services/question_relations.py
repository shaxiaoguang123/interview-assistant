from __future__ import annotations

from datetime import timezone
from hashlib import sha256
import json
import re

from sqlalchemy.orm import Session

from app.errors import ApiError
from app.models.question import Question, QuestionRelation
from app.models.taxonomy import utc_now
from app.services.question_similarity import (
    MAX_SIMILAR_CANDIDATES,
    _is_active_canonical,
    _is_completed_merge_pair,
    _is_live_relation_endpoint,
    _pair_score,
    _relations_for_question,
    _text_sha256,
    refresh_rule_suggestions,
)


def _reviewable_question(session: Session, question_id: int) -> Question:
    question = session.get(Question, question_id)
    if question is None:
        raise ApiError(404, "NOT_FOUND", "Question not found")
    if not _is_live_relation_endpoint(question):
        raise ApiError(409, "CONFLICT", "This Question is no longer available for similarity review")
    return question


def _begin_write(session: Session) -> None:
    # Serialize validation and the decision write, including sqlite3's legacy
    # mode where SELECT alone would otherwise leave us outside a transaction.
    connection = session.connection()
    if connection.dialect.name == "sqlite":
        connection.exec_driver_sql("BEGIN IMMEDIATE")


def _current_pair(relation: QuestionRelation, left: Question, right: Question) -> bool:
    return (
        _is_live_relation_endpoint(left)
        and _is_live_relation_endpoint(right)
        and (_is_active_canonical(left) or _is_active_canonical(right))
        and not _is_completed_merge_pair(left, right)
        and relation.question_text_sha256_snapshot == _text_sha256(left)
        and relation.related_question_text_sha256_snapshot == _text_sha256(right)
        # Algorithm updates can invalidate old unreviewed suggestions without
        # changing either text. Human-reviewed decisions still take precedence.
        and not (
            relation.suggested_by == "rule"
            and relation.decision_status == "suggested"
            and _pair_score(left, right) is None
        )
    )


def _is_unresolved(relation: QuestionRelation) -> bool:
    return relation.relation_type == "same_question" and relation.decision_status in {
        "suggested", "accepted",
    }


def _review_token(relation: QuestionRelation, left: Question, right: Question) -> str:
    updated_at = relation.updated_at
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    state = {
        "id": relation.id,
        "relation_type": relation.relation_type,
        "decision_status": relation.decision_status,
        "suggested_by": relation.suggested_by,
        "confidence": relation.confidence,
        "updated_at": updated_at.astimezone(timezone.utc).isoformat(),
        "endpoints": [
            {
                "id": item.id,
                "text_sha256": _text_sha256(item),
                "normalized_hash": item.normalized_hash,
                "status": item.status,
                "archived": item.archived_at is not None,
                "merged_into_question_id": item.merged_into_question_id,
                "candidate_state": item.ingestion_candidate_state,
                "candidate_revision": item.candidate_revision,
            }
            for item in (left, right)
        ],
        "snapshots": [
            relation.question_text_sha256_snapshot,
            relation.related_question_text_sha256_snapshot,
        ],
    }
    return sha256(json.dumps(state, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _relation_json(
    relation: QuestionRelation, left: Question, right: Question, question_id: int
) -> dict:
    other = right if left.id == question_id else left
    return {
        "id": relation.id,
        "question_id": relation.question_id,
        "related_question_id": relation.related_question_id,
        "relation_type": relation.relation_type,
        "decision_status": relation.decision_status,
        "suggested_by": relation.suggested_by,
        "confidence": relation.confidence,
        "match_kind": "exact" if left.normalized_hash == right.normalized_hash else "trigram",
        "review_token": _review_token(relation, left, right),
        "other_question": {
            "id": other.id,
            "text": other.text,
            "status": other.status,
            "canonical_question_id": other.id if _is_active_canonical(other) else None,
            "candidate_state": other.ingestion_candidate_state,
        },
    }


def get_similar_candidates(session: Session, question_id: int) -> dict:
    question = _reviewable_question(session, question_id)
    current = []
    scan_required = False
    for relation in _relations_for_question(session, question_id):
        left = session.get(Question, relation.question_id)
        right = session.get(Question, relation.related_question_id)
        if left is not None and right is not None and _is_completed_merge_pair(left, right):
            continue
        if left is None or right is None or not _current_pair(relation, left, right):
            scan_required = True
            continue
        current.append((relation, left, right))
    current.sort(key=lambda row: (
        not _is_unresolved(row[0]),
        -(row[0].confidence or 0.0),
        row[2].id if row[1].id == question_id else row[1].id,
    ))
    unresolved_count = sum(_is_unresolved(row[0]) for row in current)
    return {
        "question_id": question_id,
        "canonical_question_id": question.id if _is_active_canonical(question) else None,
        "candidate_state": question.ingestion_candidate_state,
        "total_count": len(current),
        "unresolved_count": unresolved_count,
        "confirmation_blocked": scan_required or unresolved_count > 0,
        "scan_required": scan_required,
        "candidates": [
            _relation_json(relation, left, right, question_id)
            for relation, left, right in current[:MAX_SIMILAR_CANDIDATES]
        ],
    }


def scan_similar_candidates(session: Session, question_id: int) -> dict:
    with session.begin():
        _begin_write(session)
        _reviewable_question(session, question_id)
        refresh_rule_suggestions(session, question_id)
        return get_similar_candidates(session, question_id)


def _validate_decision(payload: object) -> dict:
    fields = {"question_id", "relation_type", "decision_status", "expected_review_token"}
    if not isinstance(payload, dict) or set(payload) != fields:
        raise ApiError(400, "VALIDATION_ERROR", "Expected question_id, relation_type, decision_status and expected_review_token")
    if type(payload["question_id"]) is not int or payload["question_id"] <= 0:
        raise ApiError(400, "VALIDATION_ERROR", "question_id must be a positive integer")
    relation_type = payload["relation_type"]
    decision = payload["decision_status"]
    if not isinstance(relation_type, str) or relation_type not in {
        "same_question", "related_question", "different_question",
    }:
        raise ApiError(400, "VALIDATION_ERROR", "Invalid relation_type")
    if not isinstance(decision, str) or decision not in {"suggested", "accepted", "rejected"}:
        raise ApiError(400, "VALIDATION_ERROR", "Invalid decision_status")
    if decision == "accepted" and relation_type == "same_question":
        raise ApiError(400, "VALIDATION_ERROR", "Same-question acceptance requires the future canonical merge workflow")
    if decision == "suggested" and relation_type != "same_question":
        raise ApiError(400, "VALIDATION_ERROR", "Related/different classification requires an explicit decision")
    token = payload["expected_review_token"]
    if not isinstance(token, str) or re.fullmatch(r"[0-9a-f]{64}", token) is None:
        raise ApiError(400, "VALIDATION_ERROR", "expected_review_token is required; reload the review")
    return payload


def review_question_relation(session: Session, relation_id: int, payload: object) -> dict:
    decision = _validate_decision(payload)
    with session.begin():
        _begin_write(session)
        relation = session.get(QuestionRelation, relation_id)
        if relation is None or decision["question_id"] not in {
            relation.question_id, relation.related_question_id,
        }:
            raise ApiError(404, "NOT_FOUND", "Relation not found for this Question")
        left = session.get(Question, relation.question_id)
        right = session.get(Question, relation.related_question_id)
        if left is None or right is None or not _current_pair(relation, left, right):
            raise ApiError(409, "RELATION_STALE", "Question text or eligibility changed; rescan and review again")
        if _review_token(relation, left, right) != decision["expected_review_token"]:
            raise ApiError(409, "REVIEW_CONFLICT", "This review changed; reload before choosing again")
        if (relation.relation_type, relation.decision_status) != (
            decision["relation_type"], decision["decision_status"],
        ):
            relation.relation_type = decision["relation_type"]
            relation.decision_status = decision["decision_status"]
            relation.suggested_by = "user"
            relation.updated_at = utc_now()
            session.flush()
        return _relation_json(relation, left, right, decision["question_id"])
