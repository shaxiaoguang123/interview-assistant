from io import BytesIO
import uuid

from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.ingestion import (
    IngestionJob,
    OCRBlock,
    QuestionSource,
    QuestionSourceOCRBlock,
)
from app.models.practice import PracticeSession, SessionItem
from app.models.question import Question
from app.ocr.adapter import OCRDetection


def _png_bytes():
    stream = BytesIO()
    Image.new("RGB", (200, 120), color=(210, 220, 230)).save(stream, format="PNG")
    return stream.getvalue()


def test_phase1b_upload_ocr_review_confirm_and_practice_flow(client, app):
    first_detection = OCRDetection(
        id=str(uuid.uuid4()),
        text="1. What is MCP?",
        bbox=(0.1, 0.1, 0.7, 0.12),
        confidence=0.97,
        reading_order=0,
        block_type="text",
    )
    second_detection = OCRDetection(
        id=str(uuid.uuid4()),
        text="2. What does LangGraph persist?",
        bbox=(0.1, 0.35, 0.7, 0.12),
        confidence=0.95,
        reading_order=1,
        block_type="text",
    )

    class FakeAdapter:
        name = "acceptance-fake"
        version = "acceptance-fake-1;provider=CPUExecutionProvider"

        def recognize(self, image):
            assert image.size == (200, 120)
            return [first_detection, second_detection]

    app.config["OCR_ADAPTER_FACTORY"] = lambda: FakeAdapter()
    upload = client.post(
        "/api/v1/sources",
        data={"files": (BytesIO(_png_bytes()), "realistic-agent-interview.png")},
        content_type="multipart/form-data",
    )
    assert upload.status_code == 200
    uploaded = upload.get_json()["results"][0]
    source_id = uploaded["source"]["id"]
    job_id = uploaded["job"]["id"]
    assert client.get(f"/api/v1/sources/{source_id}/original").data == _png_bytes()

    run = client.post(f"/api/v1/ingestions/{job_id}/run")
    assert run.status_code == 200
    assert run.get_json()["job"]["status"] == "succeeded"
    candidates = client.get(f"/api/v1/ingestions/{job_id}/candidates").get_json()
    assert [item["text"] for item in candidates] == [
        "1. What is MCP?",
        "2. What does LangGraph persist?",
    ]
    candidate = candidates[0]
    source_row = candidate["sources"][0]
    assert source_row["source_text_snapshot"] == "1. What is MCP?"
    assert source_row["ocr_blocks"][0]["id"] == first_detection.id

    generic_patch = client.patch(
        f"/api/v1/questions/{candidate['id']}",
        json={"text": "Bypass review"},
    )
    assert generic_patch.status_code == 409
    corrected = client.patch(
        f"/api/v1/ingestion-candidates/{candidate['id']}",
        json={
            "expected_revision": candidate["candidate_revision"],
            "text": "What is MCP?",
            "source_locator_corrections": [
                {
                    "question_source_id": source_row["question_source_id"],
                    "locator_correction_json": {
                        "x": 0.12,
                        "y": 0.11,
                        "width": 0.68,
                        "height": 0.11,
                    },
                }
            ],
        },
    )
    assert corrected.status_code == 200
    confirmed = client.post(
        f"/api/v1/ingestion-candidates/{candidate['id']}/confirm",
        json={"expected_revision": corrected.get_json()["candidate_revision"]},
    )
    assert confirmed.status_code == 200
    assert confirmed.get_json()["status"] == "active"
    assert len(client.get("/api/v1/questions?q=MCP").get_json()) == 1
    source_history = client.get(f"/api/v1/questions/{candidate['id']}/sources")
    assert source_history.status_code == 200
    assert source_history.get_json()[0]["question_source_id"] == source_row["question_source_id"]

    practice = client.post(
        "/api/v1/practice-sessions",
        json={"mode": "random", "filters": {}, "limit": 10, "selection_seed": 17},
    )
    assert practice.status_code == 201
    assert [item["question"]["id"] for item in practice.get_json()["items"]] == [
        candidate["id"]
    ]
    with app.extensions["sqlalchemy_session_factory"]() as session:
        assert session.scalar(select(Question).where(Question.id == candidate["id"])).status == "active"


def test_phase1b_retry_does_not_overwrite_old_blocks_or_confirmed_source(client, app):
    detection = OCRDetection(
        id=str(uuid.uuid4()),
        text="What is Agent memory?",
        bbox=(0.1, 0.1, 0.6, 0.1),
        confidence=0.96,
        reading_order=0,
        block_type="text",
    )

    class FakeAdapter:
        name = "retry-fake"
        version = "retry-fake-1;provider=CPUExecutionProvider"

        def recognize(self, _image):
            return [detection]

    app.config["OCR_ADAPTER_FACTORY"] = lambda: FakeAdapter()
    uploaded = client.post(
        "/api/v1/sources",
        data={"files": (BytesIO(_png_bytes()), "retry-source.png")},
        content_type="multipart/form-data",
    ).get_json()["results"][0]
    first_job_id = uploaded["job"]["id"]
    client.post(f"/api/v1/ingestions/{first_job_id}/run")
    candidate = client.get(
        f"/api/v1/ingestions/{first_job_id}/candidates"
    ).get_json()[0]
    confirmed = client.post(
        f"/api/v1/ingestion-candidates/{candidate['id']}/confirm",
        json={"expected_revision": 0},
    )
    assert confirmed.status_code == 200
    old_source_id = candidate["sources"][0]["question_source_id"]
    old_block_id = candidate["sources"][0]["ocr_blocks"][0]["id"]

    retried = client.post(
        f"/api/v1/sources/{uploaded['source']['id']}/ingestions"
    )

    assert retried.status_code == 201
    assert retried.get_json()["job"]["id"] != first_job_id
    with Session(app.extensions["sqlalchemy_engine"]) as session:
        assert session.get(OCRBlock, old_block_id) is not None
        assert session.get(QuestionSource, old_source_id).question_id == candidate["id"]
