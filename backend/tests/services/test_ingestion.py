from importlib import import_module
from io import BytesIO
from pathlib import Path
import subprocess
import sys
import uuid

from PIL import Image
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from werkzeug.datastructures import FileStorage

from app.errors import ApiError
from app.models.ingestion import (
    IngestionJob,
    OCRBlock,
    QuestionSource,
    QuestionSourceOCRBlock,
    SourceAsset,
)
from app.models.question import Question
from app.services.source_storage import save_source_file


BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _ingestion_service():
    module_path = BACKEND_ROOT / "app" / "services" / "ingestion.py"
    assert module_path.is_file(), "missing feature: ingestion job service"
    return import_module("app.services.ingestion")


def _adapter_module():
    module_path = BACKEND_ROOT / "app" / "ocr" / "adapter.py"
    assert module_path.is_file(), "missing feature: replaceable OCR adapter"
    return import_module("app.ocr.adapter")


def _candidate_builder_module():
    module_path = BACKEND_ROOT / "app" / "services" / "candidate_builder.py"
    assert module_path.is_file(), "missing feature: baseline candidate grouping"
    return import_module("app.services.candidate_builder")


def _png_bytes():
    image = Image.new("RGB", (12, 8), color=(20, 80, 140))
    stream = BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


def _create_source_job(app):
    with app.app_context():
        source = save_source_file(
            FileStorage(
                stream=BytesIO(_png_bytes()),
                filename="practice.png",
                content_type="image/png",
            ),
            app.config["SOURCE_STORAGE_DIR"],
            {},
        )
        session_factory = app.extensions["sqlalchemy_session_factory"]
        with session_factory.begin() as session:
            session.add(source)
            session.flush()
            job = IngestionJob(source_asset_id=source.id, status="queued", stage="queued")
            session.add(job)
            session.flush()
            return source.id, job.id


class FakeOCRAdapter:
    name = "fake-ocr"
    version = "fake-1;provider=CPUExecutionProvider"

    def __init__(self, detections=None, error=None):
        self.detections = detections or []
        self.error = error
        self.calls = 0

    def recognize(self, image):
        self.calls += 1
        if self.error is not None:
            raise self.error
        assert image.size == (12, 8)
        return list(self.detections)


def _detection(adapter_module, text="What is MCP?", bbox=(0.1, 0.2, 0.5, 0.2), order=0):
    return adapter_module.OCRDetection(
        id=str(uuid.uuid4()),
        text=text,
        bbox=bbox,
        confidence=0.95,
        reading_order=order,
        block_type="text",
    )


def test_fake_ocr_adapter_returns_stable_normalized_detections():
    adapter_module = _adapter_module()
    detection = _detection(adapter_module)
    assert str(uuid.UUID(detection.id)) == detection.id
    assert detection.bbox == (0.1, 0.2, 0.5, 0.2)


def test_cpu_smoke_cli_imports_app_from_backend_directory():
    smoke_script = BACKEND_ROOT / "scripts" / "ocr_cpu_smoke.py"
    result = subprocess.run(
        [sys.executable, str(smoke_script), "--help"],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "--offline" in result.stdout


def test_rapidocr_adapter_maps_boxes_to_top_left_normalized_xywh():
    adapter_path = BACKEND_ROOT / "app" / "ocr" / "rapidocr_adapter.py"
    assert adapter_path.is_file(), "missing feature: RapidOCR adapter"
    module = import_module("app.ocr.rapidocr_adapter")
    output = type(
        "FakeRapidOutput",
        (),
        {
            "boxes": [[[1, 2], [7, 2], [7, 6], [1, 6]]],
            "txts": ("Function Calling?",),
            "scores": (0.9,),
        },
    )()

    detections = module.detections_from_output(output, image_width=10, image_height=8)

    assert len(detections) == 1
    assert detections[0].bbox == pytest.approx((0.1, 0.25, 0.6, 0.5))
    assert detections[0].confidence == pytest.approx(0.9)
    assert str(uuid.UUID(detections[0].id)) == detections[0].id


def test_ocr_job_persists_engine_version_and_blocks(app):
    service = _ingestion_service()
    adapter_module = _adapter_module()
    _, job_id = _create_source_job(app)
    adapter = FakeOCRAdapter([_detection(adapter_module)])

    result = service.run_ingestion(app, job_id, adapter=adapter)

    assert result["status"] == "succeeded"
    assert result["engine"] == "fake-ocr"
    assert result["engine_version"] == adapter.version
    assert result["candidate_count"] == 1
    with Session(app.extensions["sqlalchemy_engine"]) as session:
        block = session.scalar(select(OCRBlock).where(OCRBlock.ingestion_job_id == job_id))
        candidate = session.scalar(
            select(Question).where(Question.origin_ingestion_job_id == job_id)
        )
        source = session.scalar(
            select(QuestionSource).where(QuestionSource.question_id == candidate.id)
        )
        link = session.scalar(
            select(QuestionSourceOCRBlock).where(
                QuestionSourceOCRBlock.question_source_id == source.id
            )
        )
        assert str(uuid.UUID(block.id)) == block.id
        assert candidate.status == "pending_review"
        assert candidate.ingestion_candidate_state == "pending_review"
        assert source.source_text_snapshot == "What is MCP?"
        assert source.raw_ocr_text_snapshot == "What is MCP?"
        assert link.ocr_block_id == block.id


def test_empty_ocr_result_completes_without_candidates(app):
    service = _ingestion_service()
    _, job_id = _create_source_job(app)
    adapter = FakeOCRAdapter([])

    result = service.run_ingestion(app, job_id, adapter=adapter)

    assert result["status"] == "succeeded"
    assert result["candidate_count"] == 0
    with Session(app.extensions["sqlalchemy_engine"]) as session:
        assert session.scalar(
            select(func.count()).select_from(OCRBlock).where(OCRBlock.ingestion_job_id == job_id)
        ) == 0
        assert session.scalar(
            select(func.count())
            .select_from(Question)
            .where(Question.origin_ingestion_job_id == job_id)
        ) == 0


def test_ocr_failure_records_stage_and_sanitized_error(app):
    service = _ingestion_service()
    _, job_id = _create_source_job(app)
    adapter = FakeOCRAdapter(error=RuntimeError("/private/source.png OCR private text"))

    result = service.run_ingestion(app, job_id, adapter=adapter)

    assert result["status"] == "failed"
    assert result["failure_stage"] == "recognizing"
    assert result["error_code"] == "OCR_FAILED"
    assert "/private/source.png" not in result["error_message"]
    assert "private text" not in result["error_message"]


def test_candidate_group_failure_does_not_mark_job_succeeded(app, monkeypatch):
    service = _ingestion_service()
    _, job_id = _create_source_job(app)
    adapter_module = _adapter_module()
    adapter = FakeOCRAdapter([_detection(adapter_module)])
    _candidate_builder_module()

    def fail_grouping(_detections):
        raise RuntimeError("grouping failed")

    monkeypatch.setattr(service, "build_candidate_groups", fail_grouping)
    result = service.run_ingestion(app, job_id, adapter=adapter)

    assert result["status"] == "failed"
    assert result["failure_stage"] == "building_candidates"
    with Session(app.extensions["sqlalchemy_engine"]) as session:
        assert session.scalar(
            select(func.count()).select_from(OCRBlock).where(OCRBlock.ingestion_job_id == job_id)
        ) == 0
        assert session.scalar(
            select(func.count())
            .select_from(Question)
            .where(Question.origin_ingestion_job_id == job_id)
        ) == 0


def test_candidate_validation_error_after_claim_marks_job_failed(app, monkeypatch):
    service = _ingestion_service()
    _, job_id = _create_source_job(app)
    adapter_module = _adapter_module()
    adapter = FakeOCRAdapter([_detection(adapter_module)])

    def reject_grouping(_detections):
        raise ApiError(400, "VALIDATION_ERROR", "invalid candidate text")

    monkeypatch.setattr(service, "build_candidate_groups", reject_grouping)
    result = service.run_ingestion(app, job_id, adapter=adapter)

    assert result["status"] == "failed"
    assert result["failure_stage"] == "building_candidates"
    assert result["error_code"] == "CANDIDATE_BUILD_FAILED"


def test_finalization_failure_rolls_back_blocks_questions_and_sources(app, monkeypatch):
    service = _ingestion_service()
    adapter_module = _adapter_module()
    _, job_id = _create_source_job(app)
    adapter = FakeOCRAdapter([_detection(adapter_module)])
    failed = False

    def fail_question_source_flush(session, _flush_context, _instances):
        nonlocal failed
        if not failed and any(isinstance(item, QuestionSource) for item in session.new):
            failed = True
            raise RuntimeError("simulated source insert failure")

    from sqlalchemy import event

    event.listen(Session, "before_flush", fail_question_source_flush)
    try:
        result = service.run_ingestion(app, job_id, adapter=adapter)
    finally:
        event.remove(Session, "before_flush", fail_question_source_flush)

    assert result["status"] == "failed"
    assert result["failure_stage"] == "persisting_results"
    with Session(app.extensions["sqlalchemy_engine"]) as session:
        assert session.scalar(
            select(func.count()).select_from(OCRBlock).where(OCRBlock.ingestion_job_id == job_id)
        ) == 0
        assert session.scalar(
            select(func.count())
            .select_from(Question)
            .where(Question.origin_ingestion_job_id == job_id)
        ) == 0
        assert session.scalar(select(func.count()).select_from(QuestionSource)) == 0


def test_missing_models_mark_claimed_job_failed_without_startup_failure(app):
    service = _ingestion_service()
    _, job_id = _create_source_job(app)
    model_root = Path(app.instance_path) / "missing-models"
    app.config["OCR_MODEL_DIR"] = model_root
    app.config["OCR_MODEL_MANIFEST_PATH"] = model_root / "manifest.json"
    app.config["OCR_DETECTION_MODEL_PATH"] = model_root / "PP-OCRv6_det_small.onnx"
    app.config["OCR_RECOGNITION_MODEL_PATH"] = model_root / "PP-OCRv6_rec_small.onnx"
    app.config["OCR_CLASSIFICATION_MODEL_PATH"] = (
        model_root / "ch_ppocr_mobile_v2.0_cls_mobile.onnx"
    )

    result = service.run_ingestion(app, job_id)

    assert result["status"] == "failed"
    assert result["failure_stage"] == "initializing_adapter"
    assert result["error_code"] == "OCR_MODEL_MISSING"
    assert app.test_client().get("/api/v1/health").status_code == 200


def test_invalid_model_manifest_marks_claimed_job_failed(app, tmp_path):
    service = _ingestion_service()
    _, job_id = _create_source_job(app)
    model_root = tmp_path / "models"
    model_root.mkdir()
    names = {
        "det": "PP-OCRv6_det_small.onnx",
        "rec": "PP-OCRv6_rec_small.onnx",
        "cls": "ch_ppocr_mobile_v2.0_cls_mobile.onnx",
    }
    for filename in names.values():
        (model_root / filename).write_bytes(b"not-the-model")
    (model_root / "manifest.json").write_text(
        __import__("json").dumps(
            {
                "model_release": "PP-OCRv6-small",
                "rapidocr_version": "3.9.2",
                "onnxruntime_version": "1.30.0",
                "files": {
                    role: {"filename": filename, "sha256": "0" * 64}
                    for role, filename in names.items()
                },
            }
        ),
        encoding="utf-8",
    )
    app.config["OCR_MODEL_DIR"] = str(model_root)
    app.config["OCR_MODEL_MANIFEST_PATH"] = model_root / "manifest.json"
    app.config["OCR_DETECTION_MODEL_PATH"] = model_root / names["det"]
    app.config["OCR_RECOGNITION_MODEL_PATH"] = model_root / names["rec"]
    app.config["OCR_CLASSIFICATION_MODEL_PATH"] = model_root / names["cls"]

    result = service.run_ingestion(app, job_id)

    assert result["status"] == "failed"
    assert result["failure_stage"] == "initializing_adapter"
    assert result["error_code"] == "OCR_MODEL_INVALID"


def test_retry_preserves_old_question_source(client, app):
    service = _ingestion_service()
    adapter_module = _adapter_module()
    source_response = client.post(
        "/api/v1/sources",
        data={"files": (BytesIO(_png_bytes()), "retry.png")},
        content_type="multipart/form-data",
    )
    first_job_id = source_response.get_json()["results"][0]["job"]["id"]
    adapter = FakeOCRAdapter([_detection(adapter_module)])
    service.run_ingestion(app, first_job_id, adapter=adapter)
    with Session(app.extensions["sqlalchemy_engine"]) as session:
        old_block_id = session.scalar(
            select(OCRBlock.id).where(OCRBlock.ingestion_job_id == first_job_id)
        )
        old_source_id = session.scalar(
            select(QuestionSource.id)
            .join(Question, Question.id == QuestionSource.question_id)
            .where(Question.origin_ingestion_job_id == first_job_id)
        )

    retry = client.post(
        f"/api/v1/sources/{source_response.get_json()['results'][0]['source']['id']}/ingestions"
    )

    assert retry.status_code == 201
    second_job_id = retry.get_json()["job"]["id"]
    assert second_job_id != first_job_id
    with Session(app.extensions["sqlalchemy_engine"]) as session:
        assert session.get(OCRBlock, old_block_id) is not None
        assert session.get(QuestionSource, old_source_id).question_id is not None


def test_startup_recovery_marks_orphaned_running_job_and_is_idempotent(app):
    service = _ingestion_service()
    _, job_id = _create_source_job(app)
    with app.extensions["sqlalchemy_session_factory"].begin() as session:
        job = session.get(IngestionJob, job_id)
        job.status = "running"
        job.stage = "recognizing"

    recovered = service.recover_interrupted_jobs(
        app.extensions["sqlalchemy_session_factory"]
    )
    recovered_again = service.recover_interrupted_jobs(
        app.extensions["sqlalchemy_session_factory"]
    )

    assert recovered == 1
    assert recovered_again == 0
    with Session(app.extensions["sqlalchemy_engine"]) as session:
        job = session.get(IngestionJob, job_id)
        assert job.status == "failed"
        assert job.failure_stage == "recognizing"
        assert job.error_code == "INGESTION_INTERRUPTED"


def test_adapter_factory_is_lazy_and_cached(app):
    adapter_module = _adapter_module()
    calls = []
    fake = FakeOCRAdapter()
    app.config["OCR_ADAPTER_FACTORY"] = lambda: calls.append("initialized") or fake
    module = import_module("app.ocr")

    assert calls == []
    assert module.get_ocr_adapter(app) is fake
    assert module.get_ocr_adapter(app) is fake
    assert calls == ["initialized"]
