from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request
from sqlalchemy.orm import Session

from app.db import get_session
from app.errors import ApiError
from app.models.ingestion import OCRBlock
from app.repositories.ingestion import (
    get_ingestion_job,
    list_candidate_ids_by_parent,
    list_ingestion_candidates,
    list_ocr_blocks,
)
from app.services.ingestion import (
    create_retry_job,
    ingestion_job_json,
    run_ingestion,
)


blueprint = Blueprint("ingestions_v1", __name__, url_prefix="/api/v1")

_CANDIDATE_FILTERS = {
    "all",
    "pending_review",
    "confirmed",
    "rejected",
    "superseded",
    "archived",
}


def _ocr_block_json(block: OCRBlock) -> dict:
    return {
        "id": block.id,
        "ingestion_job_id": block.ingestion_job_id,
        "text": block.text,
        "bbox": block.bbox_json,
        "reading_order": block.reading_order,
        "confidence": block.confidence,
        "block_type": block.block_type,
        "created_at": block.created_at.isoformat() if block.created_at else None,
    }


def _candidate_json(candidate, child_ids: list[int], source_asset_id: int) -> dict:
    sources = []
    for source in sorted(candidate.source_rows, key=lambda item: item.id):
        blocks = sorted(
            [link.ocr_block for link in source.ocr_block_links],
            key=lambda block: (block.reading_order, block.id),
        )
        sources.append(
            {
                "question_source_id": source.id,
                "source_asset_id": source.source_asset_id,
                "locator_type": source.locator_type,
                "locator_json": source.locator_json,
                "locator_correction_json": source.locator_correction_json,
                "source_text_snapshot": source.source_text_snapshot,
                "raw_ocr_text_snapshot": source.raw_ocr_text_snapshot,
                "confidence": source.confidence,
                "ocr_blocks": [_ocr_block_json(block) for block in blocks],
            }
        )
    return {
        "id": candidate.id,
        "text": candidate.text,
        "status": candidate.status,
        "archived_at": candidate.archived_at.isoformat() if candidate.archived_at else None,
        "candidate_state": candidate.ingestion_candidate_state,
        "candidate_revision": candidate.candidate_revision,
        "origin_ingestion_job_id": candidate.origin_ingestion_job_id,
        "source_asset_id": source_asset_id,
        "split_from_candidate_id": candidate.split_from_candidate_id,
        "split_child_ids": child_ids,
        "superseded_by_candidate_id": candidate.superseded_by_candidate_id,
        "sources": sources,
    }


@blueprint.get("/ingestions/<int:job_id>")
def get_ingestion(job_id: int):
    job = get_ingestion_job(get_session(), job_id)
    if job is None:
        raise ApiError(404, "NOT_FOUND", "Ingestion job not found")
    return jsonify({"job": ingestion_job_json(job)})


@blueprint.get("/ingestions/<int:job_id>/ocr-blocks")
def get_ingestion_ocr_blocks(job_id: int):
    session: Session = get_session()
    job = get_ingestion_job(session, job_id)
    if job is None:
        raise ApiError(404, "NOT_FOUND", "Ingestion job not found")
    return jsonify([_ocr_block_json(block) for block in list_ocr_blocks(session, job_id)])


@blueprint.get("/ingestions/<int:job_id>/candidates")
def get_ingestion_candidates(job_id: int):
    session: Session = get_session()
    job = get_ingestion_job(session, job_id)
    if job is None:
        raise ApiError(404, "NOT_FOUND", "Ingestion job not found")
    status_filter = request.args.get("status", "all")
    if status_filter not in _CANDIDATE_FILTERS:
        raise ApiError(
            400,
            "VALIDATION_ERROR",
            "Invalid candidate status filter",
            {"status": "Unsupported candidate status"},
        )
    candidates = list_ingestion_candidates(
        session, job_id, status_filter=status_filter
    )
    child_ids = list_candidate_ids_by_parent(
        session, job_id, [candidate.id for candidate in candidates]
    )
    return jsonify(
        [
            _candidate_json(
                candidate,
                child_ids.get(candidate.id, []),
                job.source_asset_id,
            )
            for candidate in candidates
        ]
    )


@blueprint.post("/ingestions/<int:job_id>/run")
def post_run_ingestion(job_id: int):
    job = run_ingestion(current_app._get_current_object(), job_id)
    return jsonify({"job": job})


@blueprint.post("/sources/<int:source_id>/ingestions")
def post_retry_ingestion(source_id: int):
    session: Session = get_session()
    with session.begin():
        job = create_retry_job(session, source_id)
        session.flush()
    return jsonify({"job": ingestion_job_json(job)}), 201
