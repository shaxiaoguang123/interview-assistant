from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
from importlib import import_module
from pathlib import Path
from queue import Queue
import threading
from uuid import uuid4

from PIL import Image
import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.models.ingestion import (
    IngestionJob,
    OCRBlock,
    QuestionSource,
    QuestionSourceOCRBlock,
)
from app.models.question import Question, QuestionRelation, QuestionState
from app.models.question import QuestionTag, QuestionTopic
from app.ocr.adapter import OCRDetection
from app.services.candidate_builder import build_candidate_groups
from app.services.questions import prepare_question_text


def _png_bytes():
    image = Image.new("RGB", (30, 20), color=(45, 80, 120))
    stream = BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


def _create_job(client):
    response = client.post(
        "/api/v1/sources",
        data={"files": (BytesIO(_png_bytes()), "candidate.png")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    result = response.get_json()["results"][0]
    assert result["status"] == "stored"
    return result["source"]["id"], result["job"]["id"]


def _add_candidate(
    session,
    *,
    source_asset_id,
    job_id,
    text,
    block_texts=None,
    locator_x=0.1,
):
    block_texts = block_texts or [text]
    blocks = []
    for index, block_text in enumerate(block_texts):
        block = OCRBlock(
            id=str(uuid4()),
            ingestion_job_id=job_id,
            text=block_text,
            bbox_json={
                "x": locator_x,
                "y": 0.1 + index * 0.12,
                "width": 0.6,
                "height": 0.08,
            },
            reading_order=index,
            confidence=0.9,
        )
        session.add(block)
        blocks.append(block)
    question_text, normalized_text, normalized_hash = prepare_question_text(text)
    candidate = Question(
        text=question_text,
        normalized_text=normalized_text,
        search_text=normalized_text,
        normalized_hash=normalized_hash,
        status="pending_review",
        origin_ingestion_job_id=job_id,
        ingestion_candidate_state="pending_review",
        candidate_revision=0,
    )
    session.add(candidate)
    session.flush()
    source = QuestionSource(
        question_id=candidate.id,
        source_asset_id=source_asset_id,
        locator_type="image_region",
        locator_json={
            "x": locator_x,
            "y": 0.1,
            "width": 0.6,
            "height": 0.08 * len(blocks) + 0.12 * (len(blocks) - 1),
        },
        source_text_snapshot="\n".join(block_texts),
        raw_ocr_text_snapshot="\n".join(block_texts),
        confidence=0.9,
    )
    session.add(source)
    session.flush()
    session.add_all(
        [
            QuestionSourceOCRBlock(
                question_source_id=source.id,
                ocr_block_id=block.id,
            )
            for block in blocks
        ]
    )
    session.flush()
    return candidate, source, blocks


def _candidate_fixture(client, app, *, text="What is MCP?", block_texts=None):
    source_asset_id, job_id = _create_job(client)
    with app.extensions["sqlalchemy_session_factory"].begin() as session:
        job = session.get(IngestionJob, job_id)
        job.status = "succeeded"
        job.stage = "completed"
        job.candidate_count = 1
        candidate, source, blocks = _add_candidate(
            session,
            source_asset_id=source_asset_id,
            job_id=job_id,
            text=text,
            block_texts=block_texts,
        )
        result = {
            "source_asset_id": source_asset_id,
            "job_id": job_id,
            "candidate_id": candidate.id,
            "source_id": source.id,
            "revision": candidate.candidate_revision,
            "block_ids": [block.id for block in blocks],
        }
    return result


def _create_topic(client):
    response = client.post(
        "/api/v1/topics",
        json={"slug": "candidate-agent-topic", "name": "Candidate Agent Topic"},
    )
    assert response.status_code in {201, 409}
    if response.status_code == 201:
        return response.get_json()["id"]
    return client.get("/api/v1/topics").get_json()[0]["id"]


def _similarity_service():
    service_path = (
        Path(__file__).resolve().parents[2]
        / "app"
        / "services"
        / "question_similarity.py"
    )
    assert service_path.is_file(), "missing feature: rule-based Question similarity service"
    return import_module("app.services.question_similarity")


def test_generic_question_patch_rejects_pending_ocr_candidate_without_mutation(client, app):
    fixture = _candidate_fixture(client, app)

    response = client.patch(
        "/api/v1/questions/" + str(fixture["candidate_id"]),
        json={"text": "Changed through generic API"},
    )

    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "CONFLICT"
    with app.extensions["sqlalchemy_session_factory"]() as session:
        candidate = session.get(Question, fixture["candidate_id"])
        assert candidate.text == "What is MCP?"
        assert candidate.candidate_revision == fixture["revision"]


def test_generic_archive_preserves_pending_candidate_disposition(client, app):
    fixture = _candidate_fixture(client, app)

    response = client.post(
        "/api/v1/questions/" + str(fixture["candidate_id"]) + "/archive"
    )

    assert response.status_code == 409
    with app.extensions["sqlalchemy_session_factory"]() as session:
        candidate = session.get(Question, fixture["candidate_id"])
        assert candidate.archived_at is None
        assert candidate.ingestion_candidate_state == "pending_review"


def test_generic_question_state_does_not_create_pending_candidate_state(client, app):
    fixture = _candidate_fixture(client, app)

    response = client.patch(
        "/api/v1/questions/" + str(fixture["candidate_id"]) + "/state",
        json={"is_favorite": True},
    )

    assert response.status_code == 409
    with app.extensions["sqlalchemy_session_factory"]() as session:
        assert session.get(QuestionState, fixture["candidate_id"]) is None


def test_manual_active_and_confirmed_active_questions_keep_phase1a_api_behavior(client, app):
    manual = client.post(
        "/api/v1/questions",
        json={"text": "Manual question stays editable"},
    ).get_json()
    fixture = _candidate_fixture(client, app, text="Confirmed candidate")
    with app.extensions["sqlalchemy_session_factory"].begin() as session:
        candidate = session.get(Question, fixture["candidate_id"])
        candidate.status = "active"
        candidate.ingestion_candidate_state = "confirmed"

    manual_update = client.patch(
        "/api/v1/questions/" + str(manual["id"]),
        json={"text": "Manual question edited"},
    )
    confirmed_update = client.patch(
        "/api/v1/questions/" + str(fixture["candidate_id"]),
        json={"text": "Confirmed candidate edited"},
    )
    manual_state = client.patch(
        "/api/v1/questions/" + str(manual["id"]) + "/state",
        json={"is_favorite": True},
    )
    confirmed_archive = client.post(
        "/api/v1/questions/" + str(fixture["candidate_id"]) + "/archive"
    )

    assert manual_update.status_code == 200
    assert manual_update.get_json()["text"] == "Manual question edited"
    assert confirmed_update.status_code == 200
    assert confirmed_update.get_json()["text"] == "Confirmed candidate edited"
    assert manual_state.status_code == 200
    assert confirmed_archive.status_code == 200


def test_candidate_patch_uses_expected_revision_and_increments_it(client, app):
    fixture = _candidate_fixture(client, app)
    response = client.patch(
        "/api/v1/ingestion-candidates/" + str(fixture["candidate_id"]),
        json={"expected_revision": fixture["revision"], "text": "Candidate edited"},
    )
    stale = client.patch(
        "/api/v1/ingestion-candidates/" + str(fixture["candidate_id"]),
        json={"expected_revision": fixture["revision"], "text": "Stale edit"},
    )

    assert response.status_code == 200
    assert response.get_json()["candidate_revision"] == fixture["revision"] + 1
    assert stale.status_code == 409
    assert stale.get_json()["error"]["code"] == "CONFLICT"


def test_candidate_patch_can_edit_text_without_revalidating_unchanged_inactive_taxonomy(
    client, app
):
    fixture = _candidate_fixture(client, app)
    topic_id = _create_topic(client)
    tag_id = client.post("/api/v1/tags", json={"name": "Inactive Candidate Tag"}).get_json()["id"]
    with app.extensions["sqlalchemy_session_factory"].begin() as session:
        session.add(QuestionTopic(question_id=fixture["candidate_id"], topic_id=topic_id))
        session.add(QuestionTag(question_id=fixture["candidate_id"], tag_id=tag_id))
    assert client.patch(f"/api/v1/topics/{topic_id}", json={"is_active": False}).status_code == 200
    assert client.patch(f"/api/v1/tags/{tag_id}", json={"is_active": False}).status_code == 200

    response = client.patch(
        f"/api/v1/ingestion-candidates/{fixture['candidate_id']}",
        json={
            "expected_revision": 0,
            "text": "Updated body only",
            "topic_ids": [topic_id],
            "tag_ids": [tag_id],
        },
    )

    assert response.status_code == 200
    assert response.get_json()["candidate_revision"] == 1
    with app.extensions["sqlalchemy_session_factory"]() as session:
        candidate = session.get(Question, fixture["candidate_id"])
        assert candidate.text == "Updated body only"
        assert [link.topic_id for link in candidate.topic_links] == [topic_id]
        assert [link.tag_id for link in candidate.tag_links] == [tag_id]


def test_candidate_noop_patch_does_not_increment_revision(client, app):
    fixture = _candidate_fixture(client, app)
    with app.extensions["sqlalchemy_session_factory"]() as session:
        source = session.get(QuestionSource, fixture["source_id"])
        locator = dict(source.locator_json)

    response = client.patch(
        f"/api/v1/ingestion-candidates/{fixture['candidate_id']}",
        json={
            "expected_revision": 0,
            "topic_ids": [],
            "tag_ids": [],
            "source_locator_corrections": [
                {
                    "question_source_id": fixture["source_id"],
                    "locator_correction_json": locator,
                }
            ],
        },
    )

    assert response.status_code == 200
    assert response.get_json()["candidate_revision"] == 0


def test_candidate_patch_rejects_new_inactive_topic_and_tag(client, app):
    fixture = _candidate_fixture(client, app)
    topic_id = _create_topic(client)
    tag_id = client.post("/api/v1/tags", json={"name": "New Inactive Tag"}).get_json()["id"]
    client.patch(f"/api/v1/topics/{topic_id}", json={"is_active": False})
    client.patch(f"/api/v1/tags/{tag_id}", json={"is_active": False})

    topic_response = client.patch(
        f"/api/v1/ingestion-candidates/{fixture['candidate_id']}",
        json={"expected_revision": 0, "topic_ids": [topic_id]},
    )
    tag_response = client.patch(
        f"/api/v1/ingestion-candidates/{fixture['candidate_id']}",
        json={"expected_revision": 0, "tag_ids": [tag_id]},
    )

    assert topic_response.status_code == 400
    assert "topic_ids" in topic_response.get_json()["error"]["fields"]
    assert tag_response.status_code == 400
    assert "tag_ids" in tag_response.get_json()["error"]["fields"]
    with app.extensions["sqlalchemy_session_factory"]() as session:
        candidate = session.get(Question, fixture["candidate_id"])
        assert candidate.candidate_revision == 0
        assert candidate.topic_links == []
        assert candidate.tag_links == []


def test_split_creates_parent_child_lineage(client, app):
    fixture = _candidate_fixture(
        client,
        app,
        text="MCP question\nFunction Calling question",
        block_texts=["MCP question", "Function Calling question"],
    )
    response = client.post(
        f"/api/v1/ingestions/{fixture['job_id']}/candidates/"
        f"{fixture['candidate_id']}/split",
        json={
            "expected_revision": 0,
            "parts": [
                {
                    "text": "MCP question",
                    "ocr_block_ids": [fixture["block_ids"][0]],
                    "source_text_snapshot": "MCP question",
                },
                {
                    "text": "Function Calling question",
                    "ocr_block_ids": [fixture["block_ids"][1]],
                    "source_text_snapshot": "Function Calling question",
                },
            ],
        },
    )

    assert response.status_code == 200
    result = response.get_json()
    assert len(result["children"]) == 2
    assert all(
        child["split_from_candidate_id"] == fixture["candidate_id"]
        and child["candidate_state"] == "pending_review"
        for child in result["children"]
    )
    with app.extensions["sqlalchemy_session_factory"]() as session:
        parent = session.get(Question, fixture["candidate_id"])
        assert parent.status == "pending_review"
        assert parent.archived_at is not None
        assert parent.ingestion_candidate_state == "superseded"
        assert parent.candidate_revision == 1


def test_split_and_merge_keep_question_status_pending_review(client, app):
    fixture = _candidate_fixture(
        client,
        app,
        text="First split\nSecond split",
        block_texts=["First split", "Second split"],
    )
    split = client.post(
        f"/api/v1/ingestions/{fixture['job_id']}/candidates/"
        f"{fixture['candidate_id']}/split",
        json={
            "expected_revision": 0,
            "parts": [
                {
                    "text": "First split",
                    "ocr_block_ids": [fixture["block_ids"][0]],
                    "source_text_snapshot": "First split",
                },
                {
                    "text": "Second split",
                    "ocr_block_ids": [fixture["block_ids"][1]],
                    "source_text_snapshot": "Second split",
                },
            ],
        },
    )
    children = split.get_json()["children"]
    merge = client.post(
        f"/api/v1/ingestions/{fixture['job_id']}/candidates/merge",
        json={
            "survivor_id": children[0]["id"],
            "candidates": [
                {"id": children[0]["id"], "expected_revision": 0},
                {"id": children[1]["id"], "expected_revision": 0},
            ],
            "final_text": "Combined split",
        },
    )

    assert merge.status_code == 200
    with app.extensions["sqlalchemy_session_factory"]() as session:
        assert session.get(Question, fixture["candidate_id"]).status == "pending_review"
        assert session.get(Question, children[0]["id"]).status == "pending_review"
        assert session.get(Question, children[1]["id"]).status == "pending_review"


def test_split_preserves_parent_question_sources_and_ocr_blocks(client, app):
    fixture = _candidate_fixture(
        client,
        app,
        text="MCP protocol\nMCP transport",
        block_texts=["MCP protocol", "MCP transport"],
    )
    split = client.post(
        f"/api/v1/ingestions/{fixture['job_id']}/candidates/"
        f"{fixture['candidate_id']}/split",
        json={
            "expected_revision": 0,
            "parts": [
                {
                    "text": "MCP protocol",
                    "ocr_block_ids": [fixture["block_ids"][0]],
                    "source_text_snapshot": "MCP protocol",
                },
                {
                    "text": "MCP transport",
                    "ocr_block_ids": [fixture["block_ids"][1]],
                    "source_text_snapshot": "MCP transport",
                },
            ],
        },
    )

    assert split.status_code == 200
    with app.extensions["sqlalchemy_session_factory"]() as session:
        parent_source = session.get(QuestionSource, fixture["source_id"])
        assert parent_source.question_id == fixture["candidate_id"]
        assert parent_source.raw_ocr_text_snapshot == "MCP protocol\nMCP transport"
        assert session.scalar(
            select(QuestionSourceOCRBlock.ocr_block_id).where(
                QuestionSourceOCRBlock.question_source_id == fixture["source_id"]
            )
        ) in fixture["block_ids"]
        assert set(
            session.scalars(
                select(OCRBlock.id).where(OCRBlock.ingestion_job_id == fixture["job_id"])
            )
        ) == set(fixture["block_ids"])


def test_split_child_has_independent_excerpt_and_source_rows(client, app):
    fixture = _candidate_fixture(
        client,
        app,
        text="Part one\nPart two",
        block_texts=["Part one", "Part two"],
    )
    response = client.post(
        f"/api/v1/ingestions/{fixture['job_id']}/candidates/"
        f"{fixture['candidate_id']}/split",
        json={
            "expected_revision": 0,
            "parts": [
                {"text": "Part one", "ocr_block_ids": [fixture["block_ids"][0]], "source_text_snapshot": "Part one"},
                {"text": "Part two", "ocr_block_ids": [fixture["block_ids"][1]], "source_text_snapshot": "Part two"},
            ],
        },
    )
    children = response.get_json()["children"]
    with app.extensions["sqlalchemy_session_factory"]() as session:
        child_sources = list(
            session.scalars(
                select(QuestionSource).where(
                    QuestionSource.question_id.in_([child["id"] for child in children])
                )
            )
        )
        assert {item.source_text_snapshot for item in child_sources} == {"Part one", "Part two"}
        assert all(item.id != fixture["source_id"] for item in child_sources)


def test_split_children_may_share_one_ocr_block_with_distinct_excerpts(client, app):
    full_text = "MCP question? Function Calling question?"
    fixture = _candidate_fixture(
        client,
        app,
        text=full_text,
        block_texts=[full_text],
    )
    response = client.post(
        f"/api/v1/ingestions/{fixture['job_id']}/candidates/"
        f"{fixture['candidate_id']}/split",
        json={
            "expected_revision": 0,
            "parts": [
                {
                    "text": "MCP question?",
                    "ocr_block_ids": fixture["block_ids"],
                    "source_text_snapshot": "MCP question?",
                },
                {
                    "text": "Function Calling question?",
                    "ocr_block_ids": fixture["block_ids"],
                    "source_text_snapshot": "Function Calling question?",
                },
            ],
        },
    )

    assert response.status_code == 200
    children = response.get_json()["children"]
    assert {child["sources"][0]["source_text_snapshot"] for child in children} == {
        "MCP question?",
        "Function Calling question?",
    }
    assert {
        child["sources"][0]["ocr_blocks"][0]["id"] for child in children
    } == {fixture["block_ids"][0]}
    assert {
        child["sources"][0]["raw_ocr_text_snapshot"] for child in children
    } == {full_text}


def test_split_rejects_block_from_another_ingestion_job(client, app):
    fixture_a = _candidate_fixture(client, app, text="Candidate A")
    fixture_b = _candidate_fixture(client, app, text="Candidate B")
    response = client.post(
        f"/api/v1/ingestions/{fixture_a['job_id']}/candidates/"
        f"{fixture_a['candidate_id']}/split",
        json={
            "expected_revision": 0,
            "parts": [
                {
                    "text": "Candidate A",
                    "ocr_block_ids": [fixture_b["block_ids"][0]],
                    "source_text_snapshot": "Candidate A",
                },
                {
                    "text": "Part two",
                    "ocr_block_ids": [fixture_a["block_ids"][0]],
                    "source_text_snapshot": "Part two",
                },
            ],
        },
    )
    assert response.status_code == 400
    with app.extensions["sqlalchemy_session_factory"]() as session:
        assert session.query(Question).filter_by(origin_ingestion_job_id=fixture_a["job_id"]).count() == 1
        assert session.get(Question, fixture_a["candidate_id"]).candidate_revision == 0


def test_split_rejects_excerpt_not_present_in_selected_ocr_blocks(client, app):
    fixture = _candidate_fixture(
        client,
        app,
        text="Original question text",
        block_texts=["Original question text"],
    )
    response = client.post(
        f"/api/v1/ingestions/{fixture['job_id']}/candidates/"
        f"{fixture['candidate_id']}/split",
        json={
            "expected_revision": 0,
            "parts": [
                {
                    "text": "Invented excerpt",
                    "ocr_block_ids": fixture["block_ids"],
                    "source_text_snapshot": "Not in OCR",
                },
                {
                    "text": "Original question text",
                    "ocr_block_ids": fixture["block_ids"],
                    "source_text_snapshot": "Original question text",
                },
            ],
        },
    )
    assert response.status_code == 400
    with app.extensions["sqlalchemy_session_factory"]() as session:
        assert session.get(Question, fixture["candidate_id"]).candidate_revision == 0


def test_candidate_merge_rejects_cross_job_rows(client, app):
    fixture_a = _candidate_fixture(client, app, text="Candidate A")
    fixture_b = _candidate_fixture(client, app, text="Candidate B")
    response = client.post(
        f"/api/v1/ingestions/{fixture_a['job_id']}/candidates/merge",
        json={
            "survivor_id": fixture_a["candidate_id"],
            "candidates": [
                {"id": fixture_a["candidate_id"], "expected_revision": 0},
                {"id": fixture_b["candidate_id"], "expected_revision": 0},
            ],
            "final_text": "Combined question",
        },
    )
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "VALIDATION_ERROR"


def test_repeated_confirm_conflicts_without_second_state_change(client, app):
    fixture = _candidate_fixture(client, app)
    path = f"/api/v1/ingestion-candidates/{fixture['candidate_id']}/confirm"
    first = client.post(path, json={"expected_revision": 0})
    repeated = client.post(path, json={"expected_revision": 0})
    assert first.status_code == 200
    assert repeated.status_code == 409
    with app.extensions["sqlalchemy_session_factory"]() as session:
        candidate = session.get(Question, fixture["candidate_id"])
        assert candidate.candidate_revision == 1
        assert candidate.ingestion_candidate_state == "confirmed"
        assert session.query(QuestionState).filter_by(question_id=candidate.id).count() == 1


def test_confirm_rejects_taxonomy_that_was_deactivated_after_candidate_edit(client, app):
    fixture = _candidate_fixture(client, app)
    topic_id = _create_topic(client)
    tag_response = client.post("/api/v1/tags", json={"name": "Candidate Confirm Tag"})
    assert tag_response.status_code == 201
    tag_id = tag_response.get_json()["id"]
    with app.extensions["sqlalchemy_session_factory"].begin() as session:
        session.add(QuestionTopic(question_id=fixture["candidate_id"], topic_id=topic_id))
        session.add(QuestionTag(question_id=fixture["candidate_id"], tag_id=tag_id))
    client.patch(f"/api/v1/topics/{topic_id}", json={"is_active": False})
    client.patch(f"/api/v1/tags/{tag_id}", json={"is_active": False})

    response = client.post(
        f"/api/v1/ingestion-candidates/{fixture['candidate_id']}/confirm",
        json={"expected_revision": 0},
    )

    assert response.status_code == 400
    with app.extensions["sqlalchemy_session_factory"]() as session:
        candidate = session.get(Question, fixture["candidate_id"])
        assert candidate.status == "pending_review"
        assert candidate.ingestion_candidate_state == "pending_review"
        assert candidate.candidate_revision == 0


def test_repeat_split_on_superseded_parent_conflicts(client, app):
    fixture = _candidate_fixture(
        client,
        app,
        text="Question A\nQuestion B",
        block_texts=["Question A", "Question B"],
    )
    body = {
        "expected_revision": 0,
        "parts": [
            {"text": "Question A", "ocr_block_ids": [fixture["block_ids"][0]], "source_text_snapshot": "Question A"},
            {"text": "Question B", "ocr_block_ids": [fixture["block_ids"][1]], "source_text_snapshot": "Question B"},
        ],
    }
    path = (
        f"/api/v1/ingestions/{fixture['job_id']}/candidates/"
        f"{fixture['candidate_id']}/split"
    )
    assert client.post(path, json=body).status_code == 200
    repeated = client.post(path, json=body)
    assert repeated.status_code == 409


def test_split_and_confirm_race_has_one_winner(client, app, monkeypatch):
    fixture = _candidate_fixture(
        client,
        app,
        text="Question A\nQuestion B",
        block_texts=["Question A", "Question B"],
    )
    split_body = {
        "expected_revision": 0,
        "parts": [
            {"text": "Question A", "ocr_block_ids": [fixture["block_ids"][0]], "source_text_snapshot": "Question A"},
            {"text": "Question B", "ocr_block_ids": [fixture["block_ids"][1]], "source_text_snapshot": "Question B"},
        ],
    }
    import app.services.ingestion_candidates as candidate_service

    barrier = threading.Barrier(2)
    original_load = candidate_service._load_candidate

    def load_and_wait(session, candidate_id, *, job_id=None):
        candidate = original_load(session, candidate_id, job_id=job_id)
        if candidate_id == fixture["candidate_id"]:
            barrier.wait(timeout=3)
        return candidate

    monkeypatch.setattr(candidate_service, "_load_candidate", load_and_wait)
    responses: Queue = Queue()
    split_client = app.test_client()
    confirm_client = app.test_client()

    def split_request():
        responses.put(
            split_client.post(
                f"/api/v1/ingestions/{fixture['job_id']}/candidates/"
                f"{fixture['candidate_id']}/split",
                json=split_body,
            )
        )

    def confirm_request():
        responses.put(
            confirm_client.post(
                f"/api/v1/ingestion-candidates/{fixture['candidate_id']}/confirm",
                json={"expected_revision": 0},
            )
        )

    split_thread = threading.Thread(target=split_request)
    confirm_thread = threading.Thread(target=confirm_request)
    split_thread.start()
    confirm_thread.start()
    split_thread.join(timeout=5)
    confirm_thread.join(timeout=5)

    assert not split_thread.is_alive()
    assert not confirm_thread.is_alive()
    statuses = sorted([responses.get_nowait().status_code, responses.get_nowait().status_code])
    assert statuses == [200, 409]


def test_concurrent_duplicate_confirmations_are_serialized_before_similarity_gate(
    client, app, monkeypatch
):
    first = _candidate_fixture(client, app, text="Explain SQLite transactions.")
    second = _candidate_fixture(client, app, text="Explain SQLite transactions.")
    import app.services.ingestion_candidates as candidate_service

    original_unresolved = candidate_service.unresolved_same_question_relations
    first_gate_reached = threading.Event()
    release_first_gate = threading.Event()
    progress = threading.Event()
    gate_lock = threading.Lock()
    gate_count = 0
    transaction_owner: int | None = None
    responses: Queue = Queue()
    progressed = False

    def pause_first_gate(session, question_id):
        nonlocal gate_count
        result = original_unresolved(session, question_id)
        with gate_lock:
            gate_count += 1
            current_count = gate_count
        if current_count == 1:
            first_gate_reached.set()
            if not release_first_gate.wait(timeout=5):
                raise AssertionError("first confirmation gate was never released")
        else:
            progress.set()
        return result

    def observe_competing_immediate_lock(
        connection, _cursor, statement, _parameters, _context, _executemany
    ):
        nonlocal transaction_owner
        if statement.strip().upper() != "BEGIN IMMEDIATE":
            return
        connection_id = id(connection.connection.driver_connection)
        with gate_lock:
            if transaction_owner is None:
                transaction_owner = connection_id
            elif connection_id != transaction_owner:
                progress.set()

    monkeypatch.setattr(
        candidate_service,
        "unresolved_same_question_relations",
        pause_first_gate,
    )
    engine = app.extensions["sqlalchemy_engine"]
    event.listen(engine, "before_cursor_execute", observe_competing_immediate_lock)
    start = threading.Barrier(3)
    clients = [app.test_client(), app.test_client()]
    fixtures = [first, second]

    def confirm_request(request_client, fixture):
        start.wait(timeout=5)
        response = request_client.post(
            f"/api/v1/ingestion-candidates/{fixture['candidate_id']}/confirm",
            json={"expected_revision": 0},
        )
        responses.put(response)

    workers = [
        threading.Thread(
            target=confirm_request,
            args=(request_client, fixture),
            name=f"confirm-{index}",
        )
        for index, (request_client, fixture) in enumerate(
            zip(clients, fixtures), start=1
        )
    ]
    try:
        for worker in workers:
            worker.start()
        start.wait(timeout=5)
        assert first_gate_reached.wait(timeout=5)
        # The second request either reaches the unsafe gate in the legacy flow,
        # or attempts BEGIN IMMEDIATE and waits for the first transaction.
        progressed = progress.wait(timeout=2)
    finally:
        release_first_gate.set()
        for worker in workers:
            worker.join(timeout=8)
        event.remove(engine, "before_cursor_execute", observe_competing_immediate_lock)

    assert all(not worker.is_alive() for worker in workers)
    assert progressed
    statuses = sorted(
        [responses.get_nowait().status_code, responses.get_nowait().status_code]
    )
    assert statuses == [200, 409]

    candidate_ids = {first["candidate_id"], second["candidate_id"]}
    with app.extensions["sqlalchemy_session_factory"]() as session:
        candidates = [
            session.get(Question, question_id) for question_id in candidate_ids
        ]
        assert sorted(candidate.status for candidate in candidates) == [
            "active",
            "pending_review",
        ]
        active_candidate = next(
            candidate for candidate in candidates if candidate.status == "active"
        )
        pending_candidate = next(
            candidate
            for candidate in candidates
            if candidate.status == "pending_review"
        )
        assert active_candidate.ingestion_candidate_state == "confirmed"
        assert active_candidate.candidate_revision == 1
        assert pending_candidate.ingestion_candidate_state == "pending_review"
        assert pending_candidate.candidate_revision == 0
        relation = session.scalar(
            select(QuestionRelation).where(
                QuestionRelation.question_id == min(candidate_ids),
                QuestionRelation.related_question_id == max(candidate_ids),
            )
        )
        assert relation is not None
        assert relation.relation_type == "same_question"
        assert relation.decision_status == "suggested"


def test_split_failure_rolls_back_parent_children_and_sources(client, app):
    fixture = _candidate_fixture(
        client,
        app,
        text="First source\nSecond source",
        block_texts=["First source", "Second source"],
    )
    failed = False

    def fail_child_source(session, _flush_context, _instances):
        nonlocal failed
        new_sources = [
            obj
            for obj in session.new
            if isinstance(obj, QuestionSource)
            and obj.question_id != fixture["candidate_id"]
        ]
        if not failed and new_sources:
            failed = True
            raise RuntimeError("simulated child source failure")

    event.listen(Session, "before_flush", fail_child_source)
    try:
        response = client.post(
            f"/api/v1/ingestions/{fixture['job_id']}/candidates/"
            f"{fixture['candidate_id']}/split",
            json={
                "expected_revision": 0,
                "parts": [
                    {"text": "First source", "ocr_block_ids": [fixture["block_ids"][0]], "source_text_snapshot": "First source"},
                    {"text": "Second source", "ocr_block_ids": [fixture["block_ids"][1]], "source_text_snapshot": "Second source"},
                ],
            },
        )
    finally:
        event.remove(Session, "before_flush", fail_child_source)

    assert response.status_code == 500
    with app.extensions["sqlalchemy_session_factory"]() as session:
        parent = session.get(Question, fixture["candidate_id"])
        assert parent.archived_at is None
        assert parent.candidate_revision == 0
        assert session.query(Question).filter_by(origin_ingestion_job_id=fixture["job_id"]).count() == 1
        assert session.query(QuestionSource).count() == 1


def test_merge_copies_sources_without_repointing_loser_evidence(client, app):
    source_asset_id, job_id = _create_job(client)
    with app.extensions["sqlalchemy_session_factory"].begin() as session:
        job = session.get(IngestionJob, job_id)
        job.status = "succeeded"
        job.stage = "completed"
        survivor, survivor_source, survivor_blocks = _add_candidate(
            session,
            source_asset_id=source_asset_id,
            job_id=job_id,
            text="Survivor source",
        )
        loser, loser_source, loser_blocks = _add_candidate(
            session,
            source_asset_id=source_asset_id,
            job_id=job_id,
            text="Loser source",
            locator_x=0.2,
        )
        survivor_id, loser_id = survivor.id, loser.id
        survivor_source_id, loser_source_id = survivor_source.id, loser_source.id
        survivor_block_id, loser_block_id = survivor_blocks[0].id, loser_blocks[0].id

    response = client.post(
        f"/api/v1/ingestions/{job_id}/candidates/merge",
        json={
            "survivor_id": survivor_id,
            "candidates": [
                {"id": survivor_id, "expected_revision": 0},
                {"id": loser_id, "expected_revision": 0},
            ],
            "final_text": "Combined source text",
        },
    )

    assert response.status_code == 200
    with app.extensions["sqlalchemy_session_factory"]() as session:
        loser_source_row = session.get(QuestionSource, loser_source_id)
        survivor_source_rows = list(
            session.scalars(
                select(QuestionSource).where(QuestionSource.question_id == survivor_id)
            )
        )
        assert loser_source_row.question_id == loser_id
        assert loser_source_row.raw_ocr_text_snapshot == "Loser source"
        assert len(survivor_source_rows) == 2
        assert all(row.id != loser_source_id for row in survivor_source_rows)
        copied = next(row for row in survivor_source_rows if row.source_text_snapshot == "Loser source")
        copied_block_ids = set(
            session.scalars(
                select(QuestionSourceOCRBlock.ocr_block_id).where(
                    QuestionSourceOCRBlock.question_source_id == copied.id
                )
            )
        )
        assert copied_block_ids == {loser_block_id}
        assert survivor_source_id in {row.id for row in survivor_source_rows}
        assert survivor_block_id in set(
            session.scalars(
                select(QuestionSourceOCRBlock.ocr_block_id).where(
                    QuestionSourceOCRBlock.question_source_id == survivor_source_id
                )
            )
        )
        loser = session.get(Question, loser_id)
        assert loser.superseded_by_candidate_id == survivor_id
        assert loser.ingestion_candidate_state == "superseded"
        assert loser.status == "pending_review"
        assert loser.archived_at is not None


def test_merge_loser_points_to_survivor_and_remains_queryable(client, app):
    fixture = _candidate_fixture(client, app, text="Survivor")
    with app.extensions["sqlalchemy_session_factory"].begin() as session:
        loser, _, _ = _add_candidate(
            session,
            source_asset_id=fixture["source_asset_id"],
            job_id=fixture["job_id"],
            text="Loser",
            locator_x=0.2,
        )
        loser_id = loser.id
    response = client.post(
        f"/api/v1/ingestions/{fixture['job_id']}/candidates/merge",
        json={
            "survivor_id": fixture["candidate_id"],
            "candidates": [
                {"id": fixture["candidate_id"], "expected_revision": 0},
                {"id": loser_id, "expected_revision": 0},
            ],
            "final_text": "Merged pending candidate",
        },
    )
    assert response.status_code == 200
    history = client.get(f"/api/v1/ingestions/{fixture['job_id']}/candidates")
    rows = {row["id"]: row for row in history.get_json()}
    assert rows[loser_id]["superseded_by_candidate_id"] == fixture["candidate_id"]
    assert rows[loser_id]["candidate_state"] == "superseded"


def test_repeat_merge_with_stale_revision_conflicts(client, app):
    fixture = _candidate_fixture(client, app, text="Survivor")
    with app.extensions["sqlalchemy_session_factory"].begin() as session:
        loser, _, _ = _add_candidate(
            session,
            source_asset_id=fixture["source_asset_id"],
            job_id=fixture["job_id"],
            text="Loser",
            locator_x=0.2,
        )
        loser_id = loser.id
    path = f"/api/v1/ingestions/{fixture['job_id']}/candidates/merge"
    body = {
        "survivor_id": fixture["candidate_id"],
        "candidates": [
            {"id": fixture["candidate_id"], "expected_revision": 0},
            {"id": loser_id, "expected_revision": 0},
        ],
        "final_text": "First merge",
    }
    assert client.post(path, json=body).status_code == 200
    repeated = client.post(path, json=body)
    assert repeated.status_code == 409


def test_locator_correction_changes_only_named_question_source(client, app):
    fixture = _candidate_fixture(client, app, text="Multiple source candidate")
    with app.extensions["sqlalchemy_session_factory"].begin() as session:
        second_source = QuestionSource(
            question_id=fixture["candidate_id"],
            source_asset_id=fixture["source_asset_id"],
            locator_type="image_region",
            locator_json={"x": 0.3, "y": 0.2, "width": 0.2, "height": 0.1},
            source_text_snapshot="Second region",
            raw_ocr_text_snapshot="Second region",
        )
        session.add(second_source)
        session.flush()
        second_source_id = second_source.id
    correction = {"x": 0.5, "y": 0.4, "width": 0.2, "height": 0.1}
    response = client.patch(
        f"/api/v1/ingestion-candidates/{fixture['candidate_id']}",
        json={
            "expected_revision": 0,
            "source_locator_corrections": [
                {
                    "question_source_id": second_source_id,
                    "locator_correction_json": correction,
                }
            ],
        },
    )

    assert response.status_code == 200
    with app.extensions["sqlalchemy_session_factory"]() as session:
        first = session.get(QuestionSource, fixture["source_id"])
        second = session.get(QuestionSource, second_source_id)
        assert first.locator_correction_json is None
        assert first.locator_json["x"] == 0.1
        assert second.locator_correction_json == correction
        assert second.locator_json["x"] == 0.3


def test_locator_correction_rejects_source_not_owned_by_candidate(client, app):
    fixture_a = _candidate_fixture(client, app, text="Candidate A")
    fixture_b = _candidate_fixture(client, app, text="Candidate B")
    response = client.patch(
        f"/api/v1/ingestion-candidates/{fixture_a['candidate_id']}",
        json={
            "expected_revision": 0,
            "source_locator_corrections": [
                {
                    "question_source_id": fixture_b["source_id"],
                    "locator_correction_json": {
                        "x": 0.1,
                        "y": 0.1,
                        "width": 0.1,
                        "height": 0.1,
                    },
                }
            ],
        },
    )
    assert response.status_code == 400
    with app.extensions["sqlalchemy_session_factory"]() as session:
        assert session.get(QuestionSource, fixture_b["source_id"]).locator_correction_json is None


def test_invalid_locator_or_stale_revision_rolls_back_all_corrections(client, app):
    fixture = _candidate_fixture(client, app, text="Multiple source candidate")
    with app.extensions["sqlalchemy_session_factory"].begin() as session:
        second_source = QuestionSource(
            question_id=fixture["candidate_id"],
            source_asset_id=fixture["source_asset_id"],
            locator_type="image_region",
            locator_json={"x": 0.3, "y": 0.2, "width": 0.2, "height": 0.1},
            source_text_snapshot="Second region",
            raw_ocr_text_snapshot="Second region",
        )
        session.add(second_source)
        session.flush()
        second_source_id = second_source.id
    response = client.patch(
        f"/api/v1/ingestion-candidates/{fixture['candidate_id']}",
        json={
            "expected_revision": 0,
            "source_locator_corrections": [
                {
                    "question_source_id": fixture["source_id"],
                    "locator_correction_json": {
                        "x": 0.1,
                        "y": 0.1,
                        "width": 0.1,
                        "height": 0.1,
                    },
                },
                {
                    "question_source_id": second_source_id,
                    "locator_correction_json": {
                        "x": 0.9,
                        "y": 0.1,
                        "width": 0.2,
                        "height": 0.1,
                    },
                },
            ],
        },
    )

    assert response.status_code == 400
    with app.extensions["sqlalchemy_session_factory"]() as session:
        assert session.get(QuestionSource, fixture["source_id"]).locator_correction_json is None
        assert session.get(QuestionSource, second_source_id).locator_correction_json is None

    stale = client.patch(
        f"/api/v1/ingestion-candidates/{fixture['candidate_id']}",
        json={
            "expected_revision": 99,
            "source_locator_corrections": [
                {
                    "question_source_id": fixture["source_id"],
                    "locator_correction_json": {
                        "x": 0.1,
                        "y": 0.1,
                        "width": 0.1,
                        "height": 0.1,
                    },
                }
            ],
        },
    )
    assert stale.status_code == 409


def test_confirm_uses_existing_search_and_practice(client, app):
    fixture = _candidate_fixture(client, app, text="What is MCP?")
    confirm = client.post(
        f"/api/v1/ingestion-candidates/{fixture['candidate_id']}/confirm",
        json={"expected_revision": 0},
    )
    assert confirm.status_code == 200
    assert confirm.get_json()["candidate_state"] == "confirmed"
    assert len(client.get("/api/v1/questions?q=MCP").get_json()) == 1
    practice = client.post(
        "/api/v1/practice-sessions",
        json={"mode": "random", "filters": {}, "limit": 5},
    )
    assert practice.status_code == 201
    assert len(practice.get_json()["items"]) == 1


def test_manual_candidate_create_reuses_job_ocr_blocks_without_changing_existing_evidence(
    client, app
):
    fixture = _candidate_fixture(
        client,
        app,
        text="Existing candidate",
        block_texts=["Unnumbered Agent question", "Continuation text"],
    )
    with app.extensions["sqlalchemy_session_factory"]() as session:
        original_source = session.get(QuestionSource, fixture["source_id"])
        original_snapshot = (
            original_source.source_text_snapshot,
            original_source.raw_ocr_text_snapshot,
            dict(original_source.locator_json),
            original_source.question_id,
        )

    response = client.post(
        f"/api/v1/ingestions/{fixture['job_id']}/candidates",
        json={
            "ocr_block_ids": fixture["block_ids"],
            "text": "Corrected manually created candidate",
        },
    )

    assert response.status_code == 201
    candidate = response.get_json()
    assert candidate["id"] != fixture["candidate_id"]
    assert candidate["text"] == "Corrected manually created candidate"
    assert candidate["origin_ingestion_job_id"] == fixture["job_id"]
    assert candidate["status"] == "pending_review"
    assert candidate["candidate_state"] == "pending_review"
    assert candidate["candidate_revision"] == 0
    source = candidate["sources"][0]
    assert source["source_asset_id"] == fixture["source_asset_id"]
    assert source["source_text_snapshot"] == "Unnumbered Agent question\nContinuation text"
    assert source["raw_ocr_text_snapshot"] == source["source_text_snapshot"]
    assert source["ocr_blocks"] and [block["id"] for block in source["ocr_blocks"]] == fixture["block_ids"]
    assert source["locator_json"] == pytest.approx({
        "x": 0.1,
        "y": 0.1,
        "width": 0.6,
        "height": 0.2,
    })

    with app.extensions["sqlalchemy_session_factory"]() as session:
        original_source = session.get(QuestionSource, fixture["source_id"])
        assert (
            original_source.source_text_snapshot,
            original_source.raw_ocr_text_snapshot,
            dict(original_source.locator_json),
            original_source.question_id,
        ) == original_snapshot
        manual_source_id = source["question_source_id"]
        assert manual_source_id != fixture["source_id"]
        linked_block_ids = set(
            session.scalars(
                select(QuestionSourceOCRBlock.ocr_block_id).where(
                    QuestionSourceOCRBlock.question_source_id == manual_source_id
                )
            )
        )
        assert linked_block_ids == set(fixture["block_ids"])

    assert client.get("/api/v1/questions?q=Corrected+manually+created").get_json() == []
    practice = client.post(
        "/api/v1/practice-sessions",
        json={"mode": "random", "filters": {}, "limit": 5},
    )
    assert practice.status_code == 201
    assert practice.get_json()["items"] == []
    confirmed = client.post(
        f"/api/v1/ingestion-candidates/{candidate['id']}/confirm",
        json={"expected_revision": 0},
    )
    assert confirmed.status_code == 200
    assert [item["id"] for item in client.get(
        "/api/v1/questions?q=Corrected+manually+created"
    ).get_json()] == [candidate["id"]]


def test_manual_candidate_create_requires_succeeded_job(client, app):
    _, job_id = _create_job(client)

    response = client.post(
        f"/api/v1/ingestions/{job_id}/candidates",
        json={"ocr_block_ids": [str(uuid4())]},
    )

    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "CONFLICT"
    with app.extensions["sqlalchemy_session_factory"]() as session:
        assert session.query(Question).filter_by(origin_ingestion_job_id=job_id).count() == 0


def test_manual_candidate_recovers_unlinked_leading_unnumbered_ocr_text(client, app):
    source_id, job_id = _create_job(client)
    leading_block_id = str(uuid4())
    numbered_block_id = str(uuid4())
    automatic_drafts = build_candidate_groups(
        [
            OCRDetection(
                id=leading_block_id,
                text="介绍一下你实际开发过的 Agent 项目。",
                bbox=(0.1, 0.15, 0.8, 0.06),
                confidence=0.9,
                reading_order=0,
            ),
            OCRDetection(
                id=numbered_block_id,
                text="1. 什么是 ReAct？",
                bbox=(0.1, 0.28, 0.5, 0.06),
                confidence=0.9,
                reading_order=1,
            ),
        ]
    )
    assert len(automatic_drafts) == 1
    assert leading_block_id not in automatic_drafts[0].ocr_block_ids
    with app.extensions["sqlalchemy_session_factory"].begin() as session:
        job = session.get(IngestionJob, job_id)
        job.status = "succeeded"
        job.stage = "completed"
        session.add_all(
            [
                OCRBlock(
                    id=leading_block_id,
                    ingestion_job_id=job_id,
                    text="介绍一下你实际开发过的 Agent 项目。",
                    bbox_json={"x": 0.1, "y": 0.15, "width": 0.8, "height": 0.06},
                    reading_order=0,
                ),
                OCRBlock(
                    id=numbered_block_id,
                    ingestion_job_id=job_id,
                    text="1. 什么是 ReAct？",
                    bbox_json={"x": 0.1, "y": 0.28, "width": 0.5, "height": 0.06},
                    reading_order=1,
                ),
            ]
        )

    response = client.post(
        f"/api/v1/ingestions/{job_id}/candidates",
        json={"ocr_block_ids": [leading_block_id]},
    )

    assert response.status_code == 201
    candidate = response.get_json()
    assert candidate["text"] == "介绍一下你实际开发过的 Agent 项目。"
    assert candidate["origin_ingestion_job_id"] == job_id
    assert candidate["sources"][0]["source_asset_id"] == source_id
    assert candidate["sources"][0]["source_text_snapshot"] == "介绍一下你实际开发过的 Agent 项目。"
    assert [block["id"] for block in candidate["sources"][0]["ocr_blocks"]] == [leading_block_id]


def test_manual_candidate_create_rejects_cross_job_blocks_atomically(client, app):
    fixture_a = _candidate_fixture(client, app, text="Candidate A")
    fixture_b = _candidate_fixture(client, app, text="Candidate B")

    response = client.post(
        f"/api/v1/ingestions/{fixture_a['job_id']}/candidates",
        json={"ocr_block_ids": fixture_b["block_ids"]},
    )

    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "VALIDATION_ERROR"
    with app.extensions["sqlalchemy_session_factory"]() as session:
        assert (
            session.query(Question)
            .filter_by(origin_ingestion_job_id=fixture_a["job_id"])
            .count()
            == 1
        )
        assert session.query(QuestionSource).count() == 2


def test_split_keeps_corrected_question_text_separate_from_ocr_snapshot(client, app):
    fixture = _candidate_fixture(
        client,
        app,
        text="LangGrapn state question",
        block_texts=["LangGrapn state question"],
    )

    response = client.post(
        f"/api/v1/ingestions/{fixture['job_id']}/candidates/"
        f"{fixture['candidate_id']}/split",
        json={
            "expected_revision": 0,
            "parts": [
                {
                    "text": "LangGraph state",
                    "ocr_block_ids": fixture["block_ids"],
                    "source_text_snapshot": "LangGrapn state",
                },
                {
                    "text": "What does the question ask?",
                    "ocr_block_ids": fixture["block_ids"],
                    "source_text_snapshot": "question",
                },
            ],
        },
    )

    assert response.status_code == 200
    children = response.get_json()["children"]
    assert [child["text"] for child in children] == [
        "LangGraph state",
        "What does the question ask?",
    ]
    assert [child["sources"][0]["source_text_snapshot"] for child in children] == [
        "LangGrapn state",
        "question",
    ]
    assert all(child["sources"][0]["raw_ocr_text_snapshot"] == "LangGrapn state question" for child in children)


def test_candidate_confirmation_rescans_and_blocks_exact_active_duplicate(client, app):
    active = client.post(
        "/api/v1/questions",
        json={"text": "What is MCP?"},
    ).get_json()
    fixture = _candidate_fixture(client, app, text="What is MCP?")

    response = client.post(
        f"/api/v1/ingestion-candidates/{fixture['candidate_id']}/confirm",
        json={"expected_revision": fixture["revision"]},
    )

    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "CONFLICT"
    with app.extensions["sqlalchemy_session_factory"]() as session:
        candidate = session.get(Question, fixture["candidate_id"])
        relation = session.scalar(
            select(QuestionRelation).where(
                QuestionRelation.question_id == min(active["id"], candidate.id),
                QuestionRelation.related_question_id == max(active["id"], candidate.id),
            )
        )
        assert candidate.status == "pending_review"
        assert candidate.ingestion_candidate_state == "pending_review"
        assert candidate.candidate_revision == fixture["revision"]
        assert relation is not None
        assert relation.relation_type == "same_question"
        assert relation.decision_status == "suggested"
        relation.decision_status = "accepted"
        session.commit()

    assert [
        question["id"]
        for question in client.get(
            "/api/v1/questions", query_string={"q": "MCP"}
        ).get_json()
    ] == [active["id"]]
    practice = client.post(
        "/api/v1/practice-sessions",
        json={"mode": "random", "limit": 10},
    )
    assert practice.status_code == 201
    assert fixture["candidate_id"] not in {
        item["question_id"] for item in practice.get_json()["items"]
    }

    still_blocked = client.post(
        f"/api/v1/ingestion-candidates/{fixture['candidate_id']}/confirm",
        json={"expected_revision": fixture["revision"]},
    )
    assert still_blocked.status_code == 409
    with app.extensions["sqlalchemy_session_factory"].begin() as session:
        relation = session.scalar(
            select(QuestionRelation).where(
                QuestionRelation.question_id == min(active["id"], fixture["candidate_id"]),
                QuestionRelation.related_question_id == max(active["id"], fixture["candidate_id"]),
            )
        )
        assert relation.relation_type == "same_question"
        assert relation.decision_status == "accepted"
        relation.relation_type = "related_question"
        relation.decision_status = "accepted"

    explicitly_distinct = client.post(
        f"/api/v1/ingestion-candidates/{fixture['candidate_id']}/confirm",
        json={"expected_revision": fixture["revision"]},
    )
    assert explicitly_distinct.status_code == 200


def test_archived_duplicate_target_does_not_block_candidate_confirmation(client, app):
    similarity = _similarity_service()
    active = client.post(
        "/api/v1/questions",
        json={"text": "What is MCP?"},
    ).get_json()
    fixture = _candidate_fixture(client, app, text="What is MCP?")
    with app.extensions["sqlalchemy_session_factory"].begin() as session:
        similarity.refresh_rule_suggestions(session, fixture["candidate_id"])
        relation = session.scalar(
            select(QuestionRelation).where(
                QuestionRelation.question_id == min(active["id"], fixture["candidate_id"]),
                QuestionRelation.related_question_id == max(active["id"], fixture["candidate_id"]),
            )
        )
        assert relation is not None
        relation.decision_status = "accepted"

    archive = client.post(f"/api/v1/questions/{active['id']}/archive")
    assert archive.status_code == 200
    with app.extensions["sqlalchemy_session_factory"]() as session:
        assert session.scalar(
            select(QuestionRelation.id).where(
                QuestionRelation.question_id == min(active["id"], fixture["candidate_id"]),
                QuestionRelation.related_question_id == max(active["id"], fixture["candidate_id"]),
            )
        ) is None

    confirmed = client.post(
        f"/api/v1/ingestion-candidates/{fixture['candidate_id']}/confirm",
        json={"expected_revision": fixture["revision"]},
    )

    assert confirmed.status_code == 200
    with app.extensions["sqlalchemy_session_factory"]() as session:
        candidate = session.get(Question, fixture["candidate_id"])
        source = session.get(QuestionSource, fixture["source_id"])
        assert candidate.status == "active"
        assert candidate.ingestion_candidate_state == "confirmed"
        assert source.raw_ocr_text_snapshot == "What is MCP?"


@pytest.mark.parametrize(
    ("relation_type", "decision_status"),
    [
        ("same_question", "rejected"),
        ("different_question", "accepted"),
    ],
)
def test_explicit_duplicate_exclusion_allows_candidate_confirmation(
    client, app, relation_type, decision_status
):
    active = client.post(
        "/api/v1/questions",
        json={"text": "What is MCP?"},
    ).get_json()
    fixture = _candidate_fixture(client, app, text="What is MCP?")
    blocked = client.post(
        f"/api/v1/ingestion-candidates/{fixture['candidate_id']}/confirm",
        json={"expected_revision": fixture["revision"]},
    )
    assert blocked.status_code == 409

    with app.extensions["sqlalchemy_session_factory"].begin() as session:
        relation = session.scalar(
            select(QuestionRelation).where(
                QuestionRelation.question_id
                == min(active["id"], fixture["candidate_id"]),
                QuestionRelation.related_question_id
                == max(active["id"], fixture["candidate_id"]),
            )
        )
        relation.relation_type = relation_type
        relation.decision_status = decision_status

    confirmed = client.post(
        f"/api/v1/ingestion-candidates/{fixture['candidate_id']}/confirm",
        json={"expected_revision": fixture["revision"]},
    )

    assert confirmed.status_code == 200
    assert confirmed.get_json()["status"] == "active"


def test_manual_ocr_block_candidate_gets_rule_suggestion(client, app):
    active = client.post(
        "/api/v1/questions",
        json={"text": "What is MCP?"},
    ).get_json()
    fixture = _candidate_fixture(
        client,
        app,
        text="Unnumbered introduction",
        block_texts=["What is MCP?"],
    )

    response = client.post(
        f"/api/v1/ingestions/{fixture['job_id']}/candidates",
        json={"ocr_block_ids": fixture["block_ids"]},
    )

    assert response.status_code == 201
    candidate_id = response.get_json()["id"]
    with app.extensions["sqlalchemy_session_factory"]() as session:
        candidate = session.get(Question, candidate_id)
        relation = session.scalar(
            select(QuestionRelation).where(
                QuestionRelation.question_id == min(active["id"], candidate_id),
                QuestionRelation.related_question_id == max(active["id"], candidate_id),
            )
        )
        assert candidate.status == "pending_review"
        assert candidate.ingestion_candidate_state == "pending_review"
        assert relation is not None
        assert relation.decision_status == "suggested"


def test_candidate_text_edit_requeues_relation_even_when_normalized_hash_is_same(
    client, app
):
    similarity = _similarity_service()
    active = client.post(
        "/api/v1/questions",
        json={"text": "MCP 是什么?"},
    ).get_json()
    fixture = _candidate_fixture(client, app, text="MCP 是什么?")
    with app.extensions["sqlalchemy_session_factory"].begin() as session:
        similarity.refresh_rule_suggestions(session, fixture["candidate_id"])
        relation = session.scalar(
            select(QuestionRelation).where(
                QuestionRelation.question_id == min(active["id"], fixture["candidate_id"]),
                QuestionRelation.related_question_id == max(active["id"], fixture["candidate_id"]),
            )
        )
        relation.decision_status = "accepted"
        source_before = session.get(QuestionSource, fixture["source_id"]).raw_ocr_text_snapshot
        candidate_hash = session.get(Question, fixture["candidate_id"]).normalized_hash

    response = client.patch(
        f"/api/v1/ingestion-candidates/{fixture['candidate_id']}",
        json={"expected_revision": fixture["revision"], "text": "ＭＣＰ 是什么?"},
    )

    assert response.status_code == 200
    with app.extensions["sqlalchemy_session_factory"]() as session:
        candidate = session.get(Question, fixture["candidate_id"])
        relation = session.scalar(
            select(QuestionRelation).where(
                QuestionRelation.question_id == min(active["id"], candidate.id),
                QuestionRelation.related_question_id == max(active["id"], candidate.id),
            )
        )
        source = session.get(QuestionSource, fixture["source_id"])
        assert candidate.normalized_hash == candidate_hash
        assert candidate.candidate_revision == fixture["revision"] + 1
        assert relation.decision_status == "suggested"
        assert relation.suggested_by == "rule"
        expected_digest = sha256(candidate.text.encode("utf-8")).hexdigest()
        if relation.question_id == candidate.id:
            assert relation.question_text_sha256_snapshot == expected_digest
        else:
            assert relation.related_question_text_sha256_snapshot == expected_digest
        assert source.raw_ocr_text_snapshot == source_before


def test_split_children_receive_rule_suggestions_without_changing_parent_evidence(
    client, app
):
    active = client.post(
        "/api/v1/questions",
        json={"text": "What is MCP?"},
    ).get_json()
    full_text = "What is MCP? Another interview question?"
    fixture = _candidate_fixture(client, app, text=full_text, block_texts=[full_text])

    response = client.post(
        f"/api/v1/ingestions/{fixture['job_id']}/candidates/"
        f"{fixture['candidate_id']}/split",
        json={
            "expected_revision": fixture["revision"],
            "parts": [
                {
                    "text": "What is MCP?",
                    "ocr_block_ids": fixture["block_ids"],
                    "source_text_snapshot": "What is MCP?",
                },
                {
                    "text": "Another interview question?",
                    "ocr_block_ids": fixture["block_ids"],
                    "source_text_snapshot": "Another interview question?",
                },
            ],
        },
    )

    assert response.status_code == 200
    first_child_id = response.get_json()["children"][0]["id"]
    with app.extensions["sqlalchemy_session_factory"]() as session:
        relation = session.scalar(
            select(QuestionRelation).where(
                QuestionRelation.question_id == min(active["id"], first_child_id),
                QuestionRelation.related_question_id == max(active["id"], first_child_id),
            )
        )
        parent_source = session.get(QuestionSource, fixture["source_id"])
        assert relation is not None
        assert relation.decision_status == "suggested"
        assert parent_source.question_id == fixture["candidate_id"]
        assert parent_source.raw_ocr_text_snapshot == full_text


def test_candidate_merge_survivor_refreshes_suggestions_for_final_text(client, app):
    active = client.post(
        "/api/v1/questions",
        json={"text": "What is MCP?"},
    ).get_json()
    fixture = _candidate_fixture(
        client,
        app,
        text="First OCR part\nSecond OCR part",
        block_texts=["First OCR part", "Second OCR part"],
    )
    second_candidate = client.post(
        f"/api/v1/ingestions/{fixture['job_id']}/candidates",
        json={"ocr_block_ids": [fixture["block_ids"][1]]},
    )
    assert second_candidate.status_code == 201

    merged = client.post(
        f"/api/v1/ingestions/{fixture['job_id']}/candidates/merge",
        json={
            "survivor_id": fixture["candidate_id"],
            "candidates": [
                {"id": fixture["candidate_id"], "expected_revision": 0},
                {"id": second_candidate.get_json()["id"], "expected_revision": 0},
            ],
            "final_text": "What is MCP?",
        },
    )

    assert merged.status_code == 200
    with app.extensions["sqlalchemy_session_factory"]() as session:
        survivor = session.get(Question, fixture["candidate_id"])
        relation = session.scalar(
            select(QuestionRelation).where(
                QuestionRelation.question_id == min(active["id"], survivor.id),
                QuestionRelation.related_question_id == max(active["id"], survivor.id),
            )
        )
        assert survivor.text == "What is MCP?"
        assert survivor.status == "pending_review"
        assert relation is not None
        assert relation.decision_status == "suggested"
