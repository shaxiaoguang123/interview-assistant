from io import BytesIO

from PIL import Image
from sqlalchemy import select

from app.models.ingestion import (
    IngestionJob,
    OCRBlock,
    QuestionSource,
    QuestionSourceOCRBlock,
)
from app.models.question import Question


def _create_candidate(client, app):
    stream = BytesIO()
    Image.new("RGB", (30, 20), color=(34, 65, 100)).save(stream, format="PNG")
    response = client.post(
        "/api/v1/sources",
        data={"files": (BytesIO(stream.getvalue()), "source.png")},
        content_type="multipart/form-data",
    )
    uploaded = response.get_json()["results"][0]
    source_asset_id = uploaded["source"]["id"]
    job_id = uploaded["job"]["id"]
    with app.extensions["sqlalchemy_session_factory"].begin() as session:
        job = session.get(IngestionJob, job_id)
        job.status = "succeeded"
        job.stage = "completed"
        block = OCRBlock(
            ingestion_job_id=job_id,
            text="Where is the evidence?",
            bbox_json={"x": 0.2, "y": 0.25, "width": 0.55, "height": 0.1},
            reading_order=0,
            confidence=0.96,
        )
        candidate = Question(
            text="Where is the evidence?",
            normalized_text="where is the evidence?",
            search_text="where is the evidence?",
            normalized_hash="source-display-hash",
            status="pending_review",
            origin_ingestion_job_id=job_id,
            ingestion_candidate_state="pending_review",
        )
        session.add_all([block, candidate])
        session.flush()
        question_source = QuestionSource(
            question_id=candidate.id,
            source_asset_id=source_asset_id,
            locator_type="image_region",
            locator_json={"x": 0.2, "y": 0.25, "width": 0.55, "height": 0.1},
            source_text_snapshot="Where is the evidence?",
            raw_ocr_text_snapshot="Where is the evidence?",
        )
        session.add(question_source)
        session.flush()
        session.add(
            QuestionSourceOCRBlock(
                question_source_id=question_source.id,
                ocr_block_id=block.id,
            )
        )
        return candidate.id, question_source.id, source_asset_id, block.id


def test_question_source_history_opens_original_and_display_images(client, app):
    candidate_id, source_id, asset_id, block_id = _create_candidate(client, app)
    response = client.get(f"/api/v1/questions/{candidate_id}/sources")

    assert response.status_code == 200
    item = response.get_json()[0]
    assert item["question_source_id"] == source_id
    assert item["source_asset_id"] == asset_id
    assert item["raw_ocr_text_snapshot"] == "Where is the evidence?"
    assert item["ocr_block_ids"] == [block_id]
    assert item["original_image_url"] == f"/api/v1/sources/{asset_id}/original"
    assert item["display_image_url"] == f"/api/v1/sources/{asset_id}/display"
    assert client.get(item["original_image_url"]).status_code == 200
    assert client.get(item["display_image_url"]).status_code == 200
