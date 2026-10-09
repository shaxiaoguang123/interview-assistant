from io import BytesIO
from hashlib import sha256
from uuid import uuid4

from PIL import Image
import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.models.question import Question, QuestionRelation
from app.ocr.adapter import OCRDetection


def _question(client, text="What is MCP?"):
    response = client.post("/api/v1/questions", json={"text": text})
    assert response.status_code == 201
    return response.get_json()


@pytest.fixture
def duplicate_candidate(client, app):
    active = _question(client)
    stream = BytesIO()
    Image.new("RGB", (12, 8), color="white").save(stream, format="PNG")
    stream.seek(0)
    upload = client.post("/api/v1/sources", data={"files": (stream, "synthetic.png")})
    job_id = upload.get_json()["results"][0]["job"]["id"]

    class FakeAdapter:
        name = "fake-ocr"
        version = "fake-1"

        def recognize(self, image):
            return [OCRDetection(
                id=str(uuid4()), text="What is MCP?", bbox=(0.1, 0.1, 0.8, 0.2),
                confidence=0.9, reading_order=0,
            )]

    app.config["OCR_ADAPTER_FACTORY"] = FakeAdapter
    assert client.post(f"/api/v1/ingestions/{job_id}/run").status_code == 200
    candidate = client.get(f"/api/v1/ingestions/{job_id}/candidates").get_json()[0]
    return active, candidate


def _read(client, question_id, *, scan=False):
    path = f"/api/v1/questions/{question_id}/similar-candidates"
    response = client.post(path + "/scan") if scan else client.get(path)
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def _patch(client, question_id, relation, relation_type="same_question", decision="rejected"):
    return client.patch(f"/api/v1/question-relations/{relation['id']}", json={
        "question_id": question_id, "relation_type": relation_type,
        "decision_status": decision, "expected_review_token": relation["review_token"],
    })


def test_read_scan_returns_current_relation_and_preserves_question_state(client, duplicate_candidate):
    active, candidate = duplicate_candidate
    initial = _read(client, candidate["id"])
    assert initial["question_id"] == candidate["id"]
    assert initial["candidate_state"] == "pending_review"
    assert initial["unresolved_count"] == initial["total_count"] == 1
    assert initial["confirmation_blocked"] is True
    assert initial["scan_required"] is False
    relation = initial["candidates"][0]
    assert relation["match_kind"] == "exact"
    assert relation["confidence"] == 1.0
    assert relation["other_question"]["id"] == active["id"]
    assert relation["other_question"]["canonical_question_id"] == active["id"]
    assert relation["relation_type"] == "same_question"
    assert relation["decision_status"] == "suggested"
    assert len(relation["review_token"]) == 64
    assert "original_path" not in str(initial)
    assert _read(client, candidate["id"], scan=True) == initial
    assert _read(client, candidate["id"], scan=True) == initial
    assert client.get(f"/api/v1/ingestions/{candidate['origin_ingestion_job_id']}/candidates").get_json()[0] == candidate


@pytest.mark.parametrize("method,path", [
    ("get", "/api/v1/questions/999999/similar-candidates"),
    ("post", "/api/v1/questions/999999/similar-candidates/scan"),
    ("patch", "/api/v1/question-relations/999999"),
])
def test_unknown_question_or_relation_returns_404(client, method, path):
    response = getattr(client, method)(path, json={
        "question_id": 1, "relation_type": "same_question", "decision_status": "rejected",
        "expected_review_token": "a" * 64,
    })
    assert response.status_code == 404


@pytest.mark.parametrize("field,value", [
    ("relation_type", "duplicate"), ("relation_type", []),
    ("decision_status", "merged"), ("decision_status", None),
    ("question_id", True), ("expected_review_token", None),
    ("unexpected", "value"),
])
def test_relation_patch_rejects_invalid_payload(client, duplicate_candidate, field, value):
    _, candidate = duplicate_candidate
    relation = _read(client, candidate["id"])["candidates"][0]
    payload = {"question_id": candidate["id"], "relation_type": "same_question",
               "decision_status": "rejected", "expected_review_token": relation["review_token"]}
    payload[field] = value
    response = client.patch(f"/api/v1/question-relations/{relation['id']}", json=payload)
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "VALIDATION_ERROR"
    assert _read(client, candidate["id"])["candidates"][0] == relation


def test_relation_patch_requires_current_question_pair_membership(client, duplicate_candidate):
    _, candidate = duplicate_candidate
    unrelated = _question(client, "Explain database transaction rollback")
    relation = _read(client, candidate["id"])["candidates"][0]
    response = _patch(client, unrelated["id"], relation)
    assert response.status_code == 404
    assert _read(client, candidate["id"])["candidates"][0] == relation


@pytest.mark.parametrize("relation_type,decision", [
    ("same_question", "rejected"), ("related_question", "accepted"),
    ("different_question", "accepted"),
])
def test_explicit_review_allows_confirmation_without_changing_evidence_or_history(
    client, duplicate_candidate, relation_type, decision
):
    active, candidate = duplicate_candidate
    practice = client.post("/api/v1/practice-sessions", json={"mode": "random", "limit": 1}).get_json()
    item = practice["items"][0]
    history = client.post(f"/api/v1/session-items/{item['id']}/review", json={"review_rating": "basic"}).get_json()
    sources_before = client.get(f"/api/v1/questions/{candidate['id']}/sources").get_json()
    confirm_url = f"/api/v1/ingestion-candidates/{candidate['id']}/confirm"
    assert client.post(confirm_url, json={"expected_revision": candidate["candidate_revision"]}).status_code == 409
    relation = _read(client, candidate["id"])["candidates"][0]
    response = _patch(client, candidate["id"], relation, relation_type, decision)
    assert response.status_code == 200
    assert response.get_json()["relation_type"] == relation_type
    assert response.get_json()["decision_status"] == decision
    assert _read(client, candidate["id"], scan=True)["candidates"][0] == response.get_json()
    assert _read(client, candidate["id"])["confirmation_blocked"] is False
    unchanged = client.get(f"/api/v1/ingestions/{candidate['origin_ingestion_job_id']}/candidates").get_json()[0]
    assert unchanged == candidate
    assert client.get(f"/api/v1/questions/{candidate['id']}/sources").get_json() == sources_before
    assert client.get(f"/api/v1/questions/{active['id']}/practice-reviews").get_json() == [history]
    confirmed = client.post(confirm_url, json={"expected_revision": candidate["candidate_revision"]})
    assert confirmed.status_code == 200
    assert confirmed.get_json()["status"] == "active"
    assert client.get(f"/api/v1/questions/{candidate['id']}/sources").get_json() == sources_before


def test_same_question_acceptance_is_unavailable_until_merge_support(client, duplicate_candidate):
    _, candidate = duplicate_candidate
    relation = _read(client, candidate["id"])["candidates"][0]
    assert _patch(client, candidate["id"], relation, "same_question", "accepted").status_code == 400
    assert _read(client, candidate["id"])["candidates"][0] == relation
    assert _patch(client, candidate["id"], relation, "related_question", "suggested").status_code == 400
    # Keeping a suggestion for later is legal and does not generate a new token.
    kept = _patch(client, candidate["id"], relation, "same_question", "suggested")
    assert kept.status_code == 200
    assert kept.get_json() == relation


def test_old_browser_decision_cannot_overwrite_a_new_review(client, duplicate_candidate):
    _, candidate = duplicate_candidate
    relation = _read(client, candidate["id"])["candidates"][0]
    newer = _patch(client, candidate["id"], relation, "related_question", "accepted")
    assert newer.status_code == 200
    assert newer.get_json()["review_token"] != relation["review_token"]
    old = _patch(client, candidate["id"], relation, "different_question", "accepted")
    assert old.status_code == 409
    assert _read(client, candidate["id"])["candidates"][0] == newer.get_json()


def test_stale_exact_text_snapshot_is_not_readable_or_reviewable(client, app, duplicate_candidate):
    _, candidate = duplicate_candidate
    relation = _read(client, candidate["id"])["candidates"][0]
    with app.extensions["sqlalchemy_session_factory"].begin() as session:
        session.get(Question, candidate["id"]).text = "Ｗhat is MCP?"
    stale = _read(client, candidate["id"])
    assert stale["candidates"] == []
    assert stale["scan_required"] is True
    assert stale["confirmation_blocked"] is True
    assert _patch(client, candidate["id"], relation).status_code == 409
    rescanned = _read(client, candidate["id"], scan=True)["candidates"][0]
    assert rescanned["decision_status"] == "suggested"
    assert rescanned["review_token"] != relation["review_token"]
    assert _patch(client, candidate["id"], rescanned).status_code == 200


def test_text_edit_invalidates_review_token_even_when_normalized_hash_is_unchanged(client, duplicate_candidate):
    _, candidate = duplicate_candidate
    relation = _read(client, candidate["id"])["candidates"][0]
    assert _patch(client, candidate["id"], relation).status_code == 200
    reviewed = _read(client, candidate["id"])["candidates"][0]
    assert client.patch(f"/api/v1/ingestion-candidates/{candidate['id']}", json={
        "text": "Ｗhat is MCP?", "expected_revision": candidate["candidate_revision"],
    }).status_code == 200
    assert _patch(client, candidate["id"], reviewed).status_code == 409
    assert _read(client, candidate["id"])["unresolved_count"] == 1


def test_archived_target_relation_cannot_be_reviewed_and_does_not_block_confirmation(client, duplicate_candidate):
    active, candidate = duplicate_candidate
    relation = _read(client, candidate["id"])["candidates"][0]
    assert client.post(f"/api/v1/questions/{active['id']}/archive").status_code == 200
    assert _patch(client, candidate["id"], relation).status_code in (404, 409)
    assert _read(client, candidate["id"])["candidates"] == []
    assert client.post(f"/api/v1/ingestion-candidates/{candidate['id']}/confirm", json={
        "expected_revision": candidate["candidate_revision"],
    }).status_code == 200


def test_relation_write_rolls_back_on_failure(client, app, duplicate_candidate):
    _, candidate = duplicate_candidate
    relation = _read(client, candidate["id"])["candidates"][0]

    def fail_after_flush(session, context):
        raise RuntimeError("injected review persistence failure")

    event.listen(Session, "after_flush", fail_after_flush)
    try:
        assert _patch(client, candidate["id"], relation).status_code == 500
    finally:
        event.remove(Session, "after_flush", fail_after_flush)
    assert _read(client, candidate["id"])["candidates"][0] == relation


def test_review_display_has_twenty_rows_but_reports_all_unresolved_matches(client, duplicate_candidate):
    _, candidate = duplicate_candidate
    for _ in range(20):
        _question(client)
    page = _read(client, candidate["id"], scan=True)
    assert len(page["candidates"]) == 20
    assert page["total_count"] == page["unresolved_count"] == 21
    for relation in page["candidates"]:
        assert _patch(client, candidate["id"], relation).status_code == 200
    next_page = _read(client, candidate["id"])
    assert len(next_page["candidates"]) == 20
    assert next_page["unresolved_count"] == 1
    assert next_page["candidates"][0]["id"] not in {row["id"] for row in page["candidates"]}
    assert _patch(client, candidate["id"], next_page["candidates"][0]).status_code == 200
    assert _read(client, candidate["id"])["confirmation_blocked"] is False


def _legacy_template_relation(client, app, relation_type="same_question", decision="suggested"):
    left = _question(client, "What is RAG?")
    right = _question(client, "What is MCP?")
    with app.extensions["sqlalchemy_session_factory"].begin() as session:
        relation = QuestionRelation(
            question_id=left["id"], related_question_id=right["id"],
            relation_type=relation_type, decision_status=decision, suggested_by="rule",
            confidence=1 / 3,
            question_text_sha256_snapshot=sha256(left["text"].encode()).hexdigest(),
            related_question_text_sha256_snapshot=sha256(right["text"].encode()).hexdigest(),
        )
        session.add(relation)
        session.flush()
        relation_id = relation.id
    # Compare persisted GET representations before/after scanning; the legacy
    # create response has timezone-aware ORM defaults before SQLite reloads.
    return (
        client.get(f"/api/v1/questions/{left['id']}").get_json(),
        client.get(f"/api/v1/questions/{right['id']}").get_json(),
        relation_id,
    )


def test_old_rule_template_suggestion_is_stale_until_rescan(client, app):
    left, right, relation_id = _legacy_template_relation(client, app)

    current = _read(client, left["id"])
    assert current["candidates"] == []
    assert current["scan_required"] is True
    response = _patch(client, left["id"], {"id": relation_id, "review_token": "a" * 64})
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "RELATION_STALE"
    scanned = _read(client, left["id"], scan=True)
    assert scanned["total_count"] == scanned["unresolved_count"] == 0
    assert scanned["scan_required"] is False
    assert scanned["confirmation_blocked"] is False
    assert _read(client, left["id"], scan=True) == scanned
    assert client.get(f"/api/v1/questions/{left['id']}").get_json() == left
    assert client.get(f"/api/v1/questions/{right['id']}").get_json() == right


@pytest.mark.parametrize("relation_type,decision", [
    ("same_question", "rejected"), ("related_question", "accepted"),
    ("different_question", "accepted"),
])
def test_rule_change_does_not_invalidate_existing_human_review(client, app, relation_type, decision):
    left, _, _ = _legacy_template_relation(client, app, relation_type, decision)
    reviewed = _read(client, left["id"])
    assert reviewed["total_count"] == 1
    assert reviewed["scan_required"] is False
    assert reviewed["confirmation_blocked"] is False
    assert _read(client, left["id"], scan=True) == reviewed
