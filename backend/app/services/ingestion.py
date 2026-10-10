from __future__ import annotations

from datetime import datetime, timezone

from flask import Flask, current_app, has_app_context
from sqlalchemy import update
from sqlalchemy.orm import Session
from PIL import Image

from app.errors import ApiError
from app.models.ingestion import (
    IngestionJob,
    OCRBlock,
    QuestionSource,
    QuestionSourceOCRBlock,
    SourceAsset,
)
from app.models.question import Question
from app.ocr import (
    OCRAdapter,
    OCRAdapterInitializationError,
    get_ocr_adapter,
    recognize_with_ocr_adapter,
)
from app.repositories.ingestion import get_ingestion_job
from app.services.candidate_builder import CandidateDraft, build_candidate_groups
from app.services.questions import prepare_question_text
from app.services.question_similarity import refresh_rule_suggestions
from app.services.source_storage import resolve_storage_path


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _configured_engine_version(config: dict) -> str:
    return (
        f"rapidocr={config['OCR_RAPIDOCR_VERSION']};"
        f"onnxruntime={config['OCR_ONNXRUNTIME_VERSION']};"
        "model=PP-OCRv6-small;provider=CPUExecutionProvider"
    )


def ingestion_job_json(job: IngestionJob) -> dict:
    return {
        "id": job.id,
        "source_asset_id": job.source_asset_id,
        "status": job.status,
        "stage": job.stage,
        "failure_stage": job.failure_stage,
        "engine": job.engine,
        "engine_version": job.engine_version,
        "error_code": job.error_code,
        "error_message": job.error_message,
        "candidate_count": job.candidate_count,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
    }


def _read_job_summary(session_factory, job_id: int) -> dict:
    with session_factory() as session:
        job = session.get(IngestionJob, job_id)
        if job is None:
            raise ApiError(404, "NOT_FOUND", "Ingestion job not found")
        return ingestion_job_json(job)


def claim_queued_job(app: Flask, job_id: int) -> None:
    session_factory = app.extensions["sqlalchemy_session_factory"]
    now = _utc_now()
    engine = (
        "rapidocr-onnxruntime"
        if app.config.get("OCR_ENGINE", "rapidocr_onnx") == "rapidocr_onnx"
        else str(app.config.get("OCR_ENGINE"))
    )
    try:
        expected_version = _configured_engine_version(app.config)
    except KeyError:
        expected_version = "configured-local-ocr"
    with session_factory.begin() as session:
        result = session.execute(
            update(IngestionJob)
            .where(IngestionJob.id == job_id, IngestionJob.status == "queued")
            .values(
                status="running",
                stage="initializing_adapter",
                failure_stage=None,
                engine=engine,
                engine_version=expected_version,
                error_code=None,
                error_message=None,
                started_at=now,
                completed_at=None,
                updated_at=now,
            )
        )
        if result.rowcount == 1:
            return
        if session.get(IngestionJob, job_id) is None:
            raise ApiError(404, "NOT_FOUND", "Ingestion job not found")
        raise ApiError(409, "CONFLICT", "Ingestion job is not queued")


def _set_job_stage(
    session_factory,
    job_id: int,
    stage: str,
    *,
    engine: str | None = None,
    engine_version: str | None = None,
) -> None:
    values = {"stage": stage, "updated_at": _utc_now()}
    if engine is not None:
        values["engine"] = engine
    if engine_version is not None:
        values["engine_version"] = engine_version
    with session_factory.begin() as session:
        result = session.execute(
            update(IngestionJob)
            .where(IngestionJob.id == job_id, IngestionJob.status == "running")
            .values(**values)
        )
        if result.rowcount != 1:
            raise ApiError(409, "CONFLICT", "Ingestion job is no longer running")


def _mark_job_failed(
    session_factory,
    job_id: int,
    failure_stage: str,
    code: str,
    message: str,
) -> None:
    with session_factory.begin() as session:
        finalized = session.execute(
            update(IngestionJob)
            .where(IngestionJob.id == job_id, IngestionJob.status == "running")
            .values(
                status="failed",
                failure_stage=failure_stage,
                error_code=code,
                error_message=message,
                completed_at=_utc_now(),
                updated_at=_utc_now(),
            )
        )
        if finalized.rowcount != 1:
            raise ApiError(409, "CONFLICT", "Ingestion job cannot be marked complete")


def _load_display_image(app: Flask, job_id: int) -> Image.Image:
    session_factory = app.extensions["sqlalchemy_session_factory"]
    with session_factory() as session:
        job = get_ingestion_job(session, job_id)
        if job is None:
            raise ApiError(404, "NOT_FOUND", "Ingestion job not found")
        relative_path = job.source_asset.display_preview_path
    path = resolve_storage_path(app.config["SOURCE_STORAGE_DIR"], relative_path)
    if not path.is_file():
        raise FileNotFoundError("Stored display image is missing")
    with Image.open(path) as image:
        image.load()
        return image.convert("RGB")


def _persist_job_results(
    app: Flask,
    job_id: int,
    detections,
    drafts: list[CandidateDraft],
    engine: str,
    engine_version: str,
) -> None:
    session_factory = app.extensions["sqlalchemy_session_factory"]
    detection_by_id = {detection.id: detection for detection in detections}
    with session_factory.begin() as session:
        claim = session.execute(
            update(IngestionJob)
            .where(
                IngestionJob.id == job_id,
                IngestionJob.status == "running",
                IngestionJob.stage == "persisting_results",
            )
            .values(updated_at=_utc_now())
        )
        if claim.rowcount != 1:
            raise ApiError(409, "CONFLICT", "Ingestion job cannot be finalized")
        job = session.get(IngestionJob, job_id)
        if job is None:
            raise ApiError(404, "NOT_FOUND", "Ingestion job not found")

        blocks = [
            OCRBlock(
                id=detection.id,
                ingestion_job_id=job_id,
                text=detection.text,
                bbox_json={
                    "x": detection.bbox[0],
                    "y": detection.bbox[1],
                    "width": detection.bbox[2],
                    "height": detection.bbox[3],
                },
                reading_order=detection.reading_order,
                confidence=detection.confidence,
                block_type=detection.block_type,
            )
            for detection in detections
        ]
        session.add_all(blocks)
        session.flush()

        for draft in drafts:
            question_text, normalized_text, normalized_hash = prepare_question_text(draft.text)
            question = Question(
                text=question_text,
                normalized_text=normalized_text,
                search_text=normalized_text,
                normalized_hash=normalized_hash,
                status="pending_review",
                origin_ingestion_job_id=job_id,
                ingestion_candidate_state="pending_review",
                candidate_revision=0,
            )
            session.add(question)
            session.flush()

            cited_detections = [
                detection_by_id[block_id]
                for block_id in draft.ocr_block_ids
                if block_id in detection_by_id
            ]
            raw_ocr_text = "\n".join(detection.text for detection in cited_detections)
            source = QuestionSource(
                question_id=question.id,
                source_asset_id=job.source_asset_id,
                locator_type="image_region",
                locator_json=draft.locator,
                source_text_snapshot=draft.source_text_snapshot,
                raw_ocr_text_snapshot=raw_ocr_text,
                confidence=draft.confidence,
            )
            session.add(source)
            session.flush()
            session.add_all(
                [
                    QuestionSourceOCRBlock(
                        question_source_id=source.id,
                        ocr_block_id=block_id,
                    )
                    for block_id in draft.ocr_block_ids
                ]
            )
            session.flush()
            refresh_rule_suggestions(session, question.id)

        session.execute(
            update(IngestionJob)
            .where(
                IngestionJob.id == job_id,
                IngestionJob.status == "running",
                IngestionJob.stage == "persisting_results",
            )
            .values(
                status="succeeded",
                stage="completed",
                candidate_count=len(drafts),
                engine=engine,
                engine_version=engine_version,
                completed_at=_utc_now(),
                updated_at=_utc_now(),
            )
        )


def _run_ingestion(app: Flask, job_id: int, adapter: OCRAdapter | None) -> dict:
    session_factory = app.extensions["sqlalchemy_session_factory"]
    claim_queued_job(app, job_id)
    failure_stage = "initializing_adapter"

    try:
        if adapter is None:
            adapter = get_ocr_adapter(app)
        _set_job_stage(
            session_factory,
            job_id,
            "recognizing",
            engine=adapter.name,
            engine_version=adapter.version,
        )

        failure_stage = "recognizing"
        image = _load_display_image(app, job_id)
        detections = recognize_with_ocr_adapter(app, adapter, image)

        failure_stage = "building_candidates"
        _set_job_stage(session_factory, job_id, "building_candidates")
        drafts = build_candidate_groups(detections)

        failure_stage = "persisting_results"
        _set_job_stage(session_factory, job_id, "persisting_results")
        _persist_job_results(
            app,
            job_id,
            detections,
            drafts,
            adapter.name,
            adapter.version,
        )
    except ApiError as error:
        if error.status_code == 409 and error.code == "CONFLICT":
            raise
        failure_code, message = {
            "initializing_adapter": (
                "OCR_RUNTIME_UNAVAILABLE",
                "Local OCR could not be initialized",
            ),
            "recognizing": ("OCR_FAILED", "Local OCR processing failed"),
            "building_candidates": (
                "CANDIDATE_BUILD_FAILED",
                "OCR candidate grouping failed",
            ),
            "persisting_results": (
                "RESULT_PERSIST_FAILED",
                "OCR results could not be saved",
            ),
        }.get(
            failure_stage,
            ("OCR_FAILED", "Local OCR processing failed"),
        )
        _mark_job_failed(
            session_factory,
            job_id,
            failure_stage,
            failure_code,
            message,
        )
    except OCRAdapterInitializationError as error:
        _mark_job_failed(
            session_factory,
            job_id,
            failure_stage,
            error.code,
            error.message,
        )
    except FileNotFoundError:
        _mark_job_failed(
            session_factory,
            job_id,
            failure_stage,
            "SOURCE_FILE_MISSING",
            "Stored source image is unavailable",
        )
    except Exception:
        failure_code, message = {
            "recognizing": ("OCR_FAILED", "Local OCR processing failed"),
            "building_candidates": (
                "CANDIDATE_BUILD_FAILED",
                "OCR candidate grouping failed",
            ),
            "persisting_results": (
                "RESULT_PERSIST_FAILED",
                "OCR results could not be saved",
            ),
        }.get(
            failure_stage,
            ("OCR_RUNTIME_UNAVAILABLE", "Local OCR could not be initialized"),
        )
        _mark_job_failed(session_factory, job_id, failure_stage, failure_code, message)
    return _read_job_summary(session_factory, job_id)


def run_ingestion(app: Flask, job_id: int, adapter: OCRAdapter | None = None) -> dict:
    if has_app_context() and current_app._get_current_object() is app:
        return _run_ingestion(app, job_id, adapter)
    with app.app_context():
        return _run_ingestion(app, job_id, adapter)


def create_retry_job(session: Session, source_asset_id: int) -> IngestionJob:
    source = session.get(SourceAsset, source_asset_id)
    if source is None:
        raise ApiError(404, "NOT_FOUND", "Source not found")
    job = IngestionJob(source_asset_id=source_asset_id, status="queued", stage="queued")
    session.add(job)
    session.flush()
    return job


def recover_interrupted_jobs(session_factory) -> int:
    with session_factory.begin() as session:
        result = session.execute(
            update(IngestionJob)
            .where(IngestionJob.status == "running")
            .values(
                status="failed",
                failure_stage=IngestionJob.stage,
                error_code="INGESTION_INTERRUPTED",
                error_message="OCR job was interrupted by application shutdown",
                completed_at=_utc_now(),
                updated_at=_utc_now(),
            )
        )
        return result.rowcount or 0
