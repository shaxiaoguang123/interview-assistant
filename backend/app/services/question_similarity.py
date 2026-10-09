from __future__ import annotations

from hashlib import sha256
import re

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.models.question import Question, QuestionRelation
from app.models.taxonomy import utc_now


SIMILARITY_THRESHOLD = 0.25
MAX_SIMILAR_CANDIDATES = 20
_UNRESOLVED_RELATION_STATUSES = {"suggested", "accepted"}
_ENGLISH_QUESTION_FRAME = re.compile(
    r"^(?:what\s+(?:is|are)|how\s+(?:does|do|can|would)|explain|describe)\s+"
)


def character_trigrams(value: str) -> set[str]:
    from app.services.questions import normalize_question_text

    normalized = normalize_question_text(value)
    compact = "".join(normalized.split())
    if len(compact) < 3:
        return set()
    return {compact[index : index + 3] for index in range(len(compact) - 2)}


def trigram_jaccard(left: str, right: str) -> float:
    left_grams = character_trigrams(left)
    right_grams = character_trigrams(right)
    union = left_grams | right_grams
    if not union:
        return 0.0
    return len(left_grams & right_grams) / len(union)


def _text_sha256(question: Question) -> str:
    return sha256(question.text.encode("utf-8")).hexdigest()


def normalize_pair(left_id: int, right_id: int) -> tuple[int, int]:
    return (left_id, right_id) if left_id < right_id else (right_id, left_id)


def _pair_snapshot(
    left: Question, right: Question
) -> tuple[tuple[int, int], str, str]:
    pair = normalize_pair(left.id, right.id)
    if left.id == pair[0]:
        return pair, _text_sha256(left), _text_sha256(right)
    return pair, _text_sha256(right), _text_sha256(left)


def _is_active_canonical(question: Question) -> bool:
    return (
        question.status == "active"
        and question.archived_at is None
        and question.merged_into_question_id is None
        and (
            question.origin_ingestion_job_id is None
            or question.ingestion_candidate_state == "confirmed"
        )
    )


def _is_pending_ocr_candidate(question: Question) -> bool:
    return (
        question.status == "pending_review"
        and question.archived_at is None
        and question.origin_ingestion_job_id is not None
        and question.ingestion_candidate_state == "pending_review"
    )


def _is_live_relation_endpoint(question: Question) -> bool:
    return _is_active_canonical(question) or _is_pending_ocr_candidate(question)


def _is_completed_merge_pair(left: Question, right: Question) -> bool:
    left_root = left.merged_into_question_id or left.id
    right_root = right.merged_into_question_id or right.id
    return (
        left_root == right_root
        and (
            left.merged_into_question_id is not None
            or right.merged_into_question_id is not None
        )
    )


def _pair_score(left: Question, right: Question) -> float | None:
    if left.normalized_hash == right.normalized_hash:
        return 1.0
    score = trigram_jaccard(left.text, right.text)
    if score < SIMILARITY_THRESHOLD:
        return None
    left_content = _question_content(left.text)
    right_content = _question_content(right.text)
    if (
        left_content is not None
        and right_content is not None
        and trigram_jaccard(left_content, right_content) < SIMILARITY_THRESHOLD
    ):
        return None
    return score


def _question_content(value: str) -> str | None:
    """Remove generic English framing, never domain names or concepts.

    A shared prompt like 'What is ...?' is not evidence that the subjects
    are the same. Keep the full-text score, but also require content overlap
    when both questions use a recognized frame. Exact hashes bypass this.
    """
    from app.services.questions import normalize_question_text

    normalized = normalize_question_text(value).rstrip("?.!").strip()
    frame = _ENGLISH_QUESTION_FRAME.match(normalized)
    if frame is None:
        return None
    content = normalized[frame.end() :]
    if normalized.startswith("how "):
        content = re.sub(r"\s+work$", "", content)
    return content


def _relations_for_question(
    session: Session, question_id: int
) -> list[QuestionRelation]:
    return list(
        session.scalars(
            select(QuestionRelation).where(
                or_(
                    QuestionRelation.question_id == question_id,
                    QuestionRelation.related_question_id == question_id,
                )
            )
        )
    )


def invalidate_unmerged_question_relations(
    session: Session, question_id: int
) -> None:
    """Remove current relation state invalidated by a Question disposition."""
    for relation in _relations_for_question(session, question_id):
        left = session.get(Question, relation.question_id)
        right = session.get(Question, relation.related_question_id)
        if left is None or right is None or _is_completed_merge_pair(left, right):
            continue
        session.delete(relation)
    session.flush()


def unresolved_same_question_relations(
    session: Session, question_id: int
) -> list[QuestionRelation]:
    unresolved = []
    for relation in _relations_for_question(session, question_id):
        if (
            relation.relation_type != "same_question"
            or relation.decision_status not in _UNRESOLVED_RELATION_STATUSES
        ):
            continue
        left = session.get(Question, relation.question_id)
        right = session.get(Question, relation.related_question_id)
        if (
            left is not None
            and right is not None
            and not _is_completed_merge_pair(left, right)
            and _is_live_relation_endpoint(left)
            and _is_live_relation_endpoint(right)
        ):
            unresolved.append(relation)
    return unresolved


def refresh_rule_suggestions(
    session: Session, question_id: int
) -> list[QuestionRelation]:
    """Refresh one Question's rule suggestions inside the caller's transaction."""
    question = session.get(Question, question_id)
    if question is None:
        raise ApiError(404, "NOT_FOUND", "Question not found")
    if not (_is_active_canonical(question) or _is_pending_ocr_candidate(question)):
        invalidate_unmerged_question_relations(session, question_id)
        return []

    targets = list(
        session.scalars(
            select(Question)
            .where(
                Question.id != question_id,
                Question.status == "active",
                Question.archived_at.is_(None),
                Question.merged_into_question_id.is_(None),
            )
            .order_by(Question.id)
        )
    )
    ranked: list[tuple[float, int, tuple[int, int], str, str]] = []
    for target in targets:
        if not _is_active_canonical(target):
            continue
        score = _pair_score(question, target)
        if score is None:
            continue
        pair, left_snapshot, right_snapshot = _pair_snapshot(question, target)
        ranked.append((score, target.id, pair, left_snapshot, right_snapshot))
    ranked.sort(key=lambda row: (-row[0], row[1]))
    # Detection and persistence must be complete: the limit belongs only to
    # the review display, otherwise the 21st duplicate could bypass confirmation.
    matches = ranked

    existing = _relations_for_question(session, question_id)
    existing_by_pair = {
        (relation.question_id, relation.related_question_id): relation
        for relation in existing
    }
    for pair, relation in list(existing_by_pair.items()):
        left = session.get(Question, relation.question_id)
        right = session.get(Question, relation.related_question_id)
        if left is None or right is None:
            session.delete(relation)
            existing_by_pair.pop(pair, None)
            continue
        if _is_completed_merge_pair(left, right):
            continue
        if not (
            _is_live_relation_endpoint(left)
            and _is_live_relation_endpoint(right)
        ):
            session.delete(relation)
            existing_by_pair.pop(pair, None)
            continue

        current_score = _pair_score(left, right)
        _current_pair, left_snapshot, right_snapshot = _pair_snapshot(left, right)
        snapshots_match = (
            relation.question_text_sha256_snapshot == left_snapshot
            and relation.related_question_text_sha256_snapshot == right_snapshot
        )
        if not snapshots_match:
            if current_score is None:
                session.delete(relation)
                existing_by_pair.pop(pair, None)
                continue
            relation.relation_type = "same_question"
            relation.decision_status = "suggested"
            relation.suggested_by = "rule"
            relation.confidence = current_score
            relation.question_text_sha256_snapshot = left_snapshot
            relation.related_question_text_sha256_snapshot = right_snapshot
            relation.updated_at = utc_now()
            continue

        if (
            current_score is None
            and relation.decision_status == "suggested"
            and relation.suggested_by == "rule"
        ):
            session.delete(relation)
            existing_by_pair.pop(pair, None)

    for score, _target_id, pair, left_snapshot, right_snapshot in matches:
        if pair in existing_by_pair:
            continue
        relation = QuestionRelation(
            question_id=pair[0],
            related_question_id=pair[1],
            relation_type="same_question",
            decision_status="suggested",
            suggested_by="rule",
            confidence=score,
            question_text_sha256_snapshot=left_snapshot,
            related_question_text_sha256_snapshot=right_snapshot,
        )
        session.add(relation)
        existing_by_pair[pair] = relation

    session.flush()
    display_relations = [
        existing_by_pair[pair]
        for _score, _target_id, pair, _left_snapshot, _right_snapshot in matches
    ]
    display_relations.sort(
        key=lambda relation: (
            not (
                relation.relation_type == "same_question"
                and relation.decision_status in _UNRESOLVED_RELATION_STATUSES
            ),
            -(relation.confidence or 0.0),
            relation.related_question_id
            if relation.question_id == question_id
            else relation.question_id,
        )
    )
    return display_relations[:MAX_SIMILAR_CANDIDATES]
