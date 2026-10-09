from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from importlib import import_module
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models.ingestion import IngestionJob, SourceAsset
from app.models.question import Question, QuestionRelation
from app.services.questions import prepare_question_text


SERVICE_PATH = (
    Path(__file__).resolve().parents[2]
    / "app"
    / "services"
    / "question_similarity.py"
)
THRESHOLD = 0.25


def _service():
    assert SERVICE_PATH.is_file(), "missing feature: rule-based Question similarity service"
    return import_module("app.services.question_similarity")


def _add_question(session, text_value: str, **overrides) -> Question:
    raw_text, normalized_text, normalized_hash = prepare_question_text(text_value)
    values = {
        "text": raw_text,
        "normalized_text": normalized_text,
        "search_text": normalized_text,
        "normalized_hash": normalized_hash,
        "status": "active",
        "archived_at": None,
    }
    values.update(overrides)
    question = Question(**values)
    session.add(question)
    session.flush()
    return question


def _add_pending_ocr_candidate(session, text_value: str) -> Question:
    source = SourceAsset(
        original_filename="similarity.png",
        mime_type="image/png",
        byte_size=1,
        original_width=1,
        original_height=1,
        display_width=1,
        display_height=1,
        original_path="sources/original/similarity.bin",
        display_preview_path="sources/display/similarity.png",
        sha256="a" * 64,
    )
    session.add(source)
    session.flush()
    job = IngestionJob(
        source_asset_id=source.id,
        status="succeeded",
        stage="completed",
    )
    session.add(job)
    session.flush()
    raw_text, normalized_text, normalized_hash = prepare_question_text(text_value)
    candidate = Question(
        text=raw_text,
        normalized_text=normalized_text,
        search_text=normalized_text,
        normalized_hash=normalized_hash,
        status="pending_review",
        origin_ingestion_job_id=job.id,
        ingestion_candidate_state="pending_review",
        candidate_revision=0,
    )
    session.add(candidate)
    session.flush()
    return candidate


def _relation_for(session, first_id: int, second_id: int) -> QuestionRelation | None:
    low_id, high_id = sorted((first_id, second_id))
    return session.scalar(
        select(QuestionRelation).where(
            QuestionRelation.question_id == low_id,
            QuestionRelation.related_question_id == high_id,
        )
    )


def _text_digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def test_character_trigrams_normalize_unicode_and_ignore_spacing():
    similarity = _service()

    assert similarity.character_trigrams("ＭＣＰ　协议") == similarity.character_trigrams(
        "mcp 协议"
    )


def test_normalize_pair_stores_each_undirected_relation_in_ascending_order():
    similarity = _service()

    assert similarity.normalize_pair(12, 3) == (3, 12)
    assert similarity.normalize_pair(3, 12) == (3, 12)
    assert similarity.normalize_pair(3, 3) == (3, 3)


def test_trigram_jaccard_covers_bilingual_positive_and_negative_boundaries():
    similarity = _service()
    english_above_threshold = similarity.trigram_jaccard(
        "How does an agent call tools with MCP?",
        "How can an agent use tools through MCP?",
    )
    english_below_threshold = similarity.trigram_jaccard(
        "How does an agent call tools with MCP?",
        "How does an agent call tools with MCP? Explain distributed database "
        "transaction rollback with retries, idempotency, locks, persistence, "
        "monitoring and reconciliation across multiple nodes.",
    )
    chinese_english_positive = similarity.trigram_jaccard(
        "如何用 MCP 调用工具？",
        "如何通过 MCP 调用工具？",
    )
    related_topic_negative = similarity.trigram_jaccard(
        "MCP 通信流程是什么？",
        "如何用 MCP 调用工具？",
    )
    distinct_semantics_negative = similarity.trigram_jaccard(
        "What is MCP transport?",
        "How does an MCP server expose tools?",
    )

    assert 0.25 <= english_above_threshold < 0.27
    assert 0.18 < english_below_threshold < 0.25
    assert chinese_english_positive >= THRESHOLD
    assert related_topic_negative < THRESHOLD
    assert distinct_semantics_negative < THRESHOLD


def test_exact_normalized_hash_match_is_suggested_with_exact_text_snapshots(db_session):
    similarity = _service()
    first = _add_question(db_session, "MCP 通信协议是什么？")
    second = _add_question(db_session, "mcp 通信协议是什么?")
    assert first.normalized_hash == second.normalized_hash

    relations = similarity.refresh_rule_suggestions(db_session, second.id)

    assert len(relations) == 1
    relation = relations[0]
    assert (relation.question_id, relation.related_question_id) == tuple(
        sorted((first.id, second.id))
    )
    assert relation.relation_type == "same_question"
    assert relation.decision_status == "suggested"
    assert relation.suggested_by == "rule"
    assert relation.confidence == 1.0
    by_id = {first.id: first.text, second.id: second.text}
    assert relation.question_text_sha256_snapshot == _text_digest(
        by_id[relation.question_id]
    )
    assert relation.related_question_text_sha256_snapshot == _text_digest(
        by_id[relation.related_question_id]
    )
    assert first.status == second.status == "active"
    assert first.merged_into_question_id is None
    assert second.merged_into_question_id is None


def test_trigram_refresh_suggests_near_duplicate_but_not_topic_neighbor(db_session):
    similarity = _service()
    source = _add_question(db_session, "如何用 MCP 调用工具？")
    near = _add_question(db_session, "如何通过 MCP 调用工具？")
    related = _add_question(db_session, "MCP 通信流程是什么？")

    relations = similarity.refresh_rule_suggestions(db_session, source.id)

    related_ids = {
        relation.related_question_id
        if relation.question_id == source.id
        else relation.question_id
        for relation in relations
    }
    assert near.id in related_ids
    assert related.id not in related_ids
    near_relation = _relation_for(db_session, source.id, near.id)
    assert near_relation is not None
    assert near_relation.decision_status == "suggested"
    assert near_relation.confidence == pytest.approx(
        similarity.trigram_jaccard(source.text, near.text)
    )


def test_rule_candidates_are_sorted_deterministically_and_capped_at_twenty(db_session):
    similarity = _service()
    source = _add_question(db_session, "How can agents call tools using MCP protocol?")
    targets = [
        _add_question(
            db_session,
            "How can agents call tools using MCP protocol version "
            + str(index),
        )
        for index in range(25)
    ]

    relations = similarity.refresh_rule_suggestions(db_session, source.id)

    assert len(relations) == 20
    confidences = [relation.confidence for relation in relations]
    assert confidences == sorted(confidences, reverse=True)
    for left, right in zip(relations, relations[1:]):
        if left.confidence == right.confidence:
            left_other = (
                left.related_question_id
                if left.question_id == source.id
                else left.question_id
            )
            right_other = (
                right.related_question_id
                if right.question_id == source.id
                else right.question_id
            )
            assert left_other < right_other
    returned_ids = {
        relation.related_question_id
        if relation.question_id == source.id
        else relation.question_id
        for relation in relations
    }
    expected_ids = {
        question.id
        for question in targets
        if similarity.trigram_jaccard(source.text, question.text) >= THRESHOLD
    }
    assert returned_ids == set(
        sorted(
            expected_ids,
            key=lambda question_id: (
                -similarity.trigram_jaccard(
                    source.text,
                    next(q.text for q in targets if q.id == question_id),
                ),
                question_id,
            ),
        )[:20]
    )


def test_repeated_refresh_preserves_user_decision_when_text_is_unchanged(db_session):
    similarity = _service()
    first = _add_question(db_session, "What is MCP?")
    second = _add_question(db_session, "What is MCP?")
    similarity.refresh_rule_suggestions(db_session, first.id)
    relation = _relation_for(db_session, first.id, second.id)
    relation.relation_type = "related_question"
    relation.decision_status = "accepted"
    relation.suggested_by = "user"
    db_session.flush()

    refreshed = similarity.refresh_rule_suggestions(db_session, second.id)

    assert len(refreshed) == 1
    assert refreshed[0].relation_type == "related_question"
    assert refreshed[0].decision_status == "accepted"
    assert refreshed[0].suggested_by == "user"
    assert _relation_for(db_session, first.id, second.id).id == relation.id


def test_text_change_with_same_normalized_hash_requeues_unmerged_relation(db_session):
    similarity = _service()
    first = _add_question(db_session, "MCP 通信协议?")
    second = _add_question(db_session, "ＭＣＰ 通信协议?")
    assert first.normalized_hash == second.normalized_hash
    similarity.refresh_rule_suggestions(db_session, second.id)
    relation = _relation_for(db_session, first.id, second.id)
    relation.decision_status = "accepted"
    db_session.flush()

    raw_text, normalized_text, digest = prepare_question_text("  MCP   通信协议?  ")
    second.text = raw_text
    second.normalized_text = normalized_text
    second.search_text = normalized_text
    second.normalized_hash = digest
    db_session.flush()
    assert second.normalized_hash == first.normalized_hash

    similarity.refresh_rule_suggestions(db_session, second.id)

    refreshed = _relation_for(db_session, first.id, second.id)
    assert refreshed.decision_status == "suggested"
    assert refreshed.suggested_by == "rule"
    assert refreshed.question_text_sha256_snapshot == _text_digest(first.text)
    assert refreshed.related_question_text_sha256_snapshot == _text_digest(second.text)


def test_text_change_that_loses_similarity_removes_unmerged_relation(db_session):
    similarity = _service()
    first = _add_question(db_session, "What is MCP?")
    second = _add_question(db_session, "What is MCP?")
    similarity.refresh_rule_suggestions(db_session, second.id)
    relation = _relation_for(db_session, first.id, second.id)
    relation.decision_status = "accepted"
    db_session.flush()

    raw_text, normalized_text, digest = prepare_question_text(
        "Explain database transaction rollback and indexing."
    )
    second.text = raw_text
    second.normalized_text = normalized_text
    second.search_text = normalized_text
    second.normalized_hash = digest
    db_session.flush()

    similarity.refresh_rule_suggestions(db_session, second.id)

    assert _relation_for(db_session, first.id, second.id) is None


def test_refresh_does_not_rewrite_completed_merge_relation(db_session):
    similarity = _service()
    root = _add_question(db_session, "What is MCP?")
    child = _add_question(
        db_session,
        "What is MCP?",
        status="merged",
        merged_into_question_id=root.id,
    )
    relation = QuestionRelation(
        question_id=root.id,
        related_question_id=child.id,
        relation_type="same_question",
        decision_status="accepted",
        suggested_by="user",
        confidence=1.0,
        question_text_sha256_snapshot=_text_digest(root.text),
        related_question_text_sha256_snapshot=_text_digest(child.text),
    )
    db_session.add(relation)
    db_session.flush()

    raw_text, normalized_text, digest = prepare_question_text(
        "What is MCP and how does it route tools?"
    )
    root.text = raw_text
    root.normalized_text = normalized_text
    root.search_text = normalized_text
    root.normalized_hash = digest
    db_session.flush()

    similarity.refresh_rule_suggestions(db_session, root.id)

    stored = _relation_for(db_session, root.id, child.id)
    assert stored.id == relation.id
    assert stored.decision_status == "accepted"
    assert stored.suggested_by == "user"
    assert stored.question_text_sha256_snapshot == _text_digest("What is MCP?")


def test_refresh_removes_relation_when_previous_target_is_archived(db_session):
    similarity = _service()
    candidate = _add_pending_ocr_candidate(db_session, "What is MCP?")
    target = _add_question(db_session, "What is MCP?")
    similarity.refresh_rule_suggestions(db_session, candidate.id)
    assert _relation_for(db_session, candidate.id, target.id) is not None

    target.archived_at = target.created_at
    db_session.flush()
    similarity.refresh_rule_suggestions(db_session, candidate.id)

    assert _relation_for(db_session, candidate.id, target.id) is None


def test_refresh_ignores_archived_and_merged_children_as_targets(db_session):
    similarity = _service()
    source = _add_question(db_session, "What is MCP?")
    archived = _add_question(
        db_session,
        "What is MCP?",
        archived_at=datetime.now(timezone.utc),
    )
    root = _add_question(db_session, "What is MCP?")
    child = _add_question(
        db_session,
        "What is MCP?",
        status="merged",
        merged_into_question_id=root.id,
    )

    relations = similarity.refresh_rule_suggestions(db_session, source.id)
    other_ids = {
        relation.related_question_id
        if relation.question_id == source.id
        else relation.question_id
        for relation in relations
    }

    assert archived.id not in other_ids
    assert child.id not in other_ids
    assert root.id in other_ids


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("What is RAG?", "What is MCP?"),
        ("How does RAG work?", "How does MCP work?"),
        ("What is LangChain?", "What is LangGraph?"),
        ("Explain RAG", "Explain MCP"),
    ],
)
def test_question_framing_alone_is_not_same_question_evidence(db_session, left, right):
    similarity = _service()
    source = _add_question(db_session, left)
    _add_question(db_session, right)

    assert similarity.refresh_rule_suggestions(db_session, source.id) == []


def test_display_limit_does_not_limit_exact_duplicate_detection(db_session):
    similarity = _service()
    targets = [_add_question(db_session, "What is MCP?") for _ in range(21)]
    candidate = _add_pending_ocr_candidate(db_session, "What is MCP?")

    first_page = similarity.refresh_rule_suggestions(db_session, candidate.id)

    assert len(first_page) == 20
    assert len(similarity.unresolved_same_question_relations(db_session, candidate.id)) == 21
    for relation in first_page:
        relation.decision_status = "rejected"
        relation.suggested_by = "user"
    db_session.flush()

    next_page = similarity.refresh_rule_suggestions(db_session, candidate.id)
    remaining = similarity.unresolved_same_question_relations(db_session, candidate.id)
    assert len(next_page) == 20
    assert len(remaining) == 1
    assert remaining[0].id == next_page[0].id
    assert targets[-1].id in (remaining[0].question_id, remaining[0].related_question_id)
    assert all(relation.decision_status == "rejected" for relation in first_page)
    remaining[0].relation_type = "different_question"
    remaining[0].decision_status = "accepted"
    remaining[0].suggested_by = "user"
    db_session.flush()
    similarity.refresh_rule_suggestions(db_session, candidate.id)
    assert similarity.unresolved_same_question_relations(db_session, candidate.id) == []
