from __future__ import annotations

from datetime import datetime, timezone
import json

from flask import Blueprint, current_app, jsonify, request, send_file
from sqlalchemy.orm import Session

from app.db import get_session
from app.errors import ApiError
from app.models.ingestion import IngestionJob, SourceAsset
from app.repositories.sources import (
    add_ingestion_job,
    add_source_asset,
    get_source_asset,
    list_source_assets,
)
from app.services.source_storage import (
    cleanup_source_files,
    resolve_storage_path,
    save_source_file,
)


blueprint = Blueprint("sources_v1", __name__, url_prefix="/api/v1")


def _timestamp(value):
    return value.isoformat() if value is not None else None


def _job_json(job: IngestionJob) -> dict:
    return {
        "id": job.id,
        "status": job.status,
        "stage": job.stage,
        "failure_stage": job.failure_stage,
        "engine": job.engine,
        "engine_version": job.engine_version,
        "error_code": job.error_code,
        "error_message": job.error_message,
        "candidate_count": job.candidate_count,
        "created_at": _timestamp(job.created_at),
        "started_at": _timestamp(job.started_at),
        "completed_at": _timestamp(job.completed_at),
    }


def _source_json(source: SourceAsset, *, include_jobs: bool = False) -> dict:
    result = {
        "id": source.id,
        "source_type": source.source_type,
        "platform": source.platform,
        "source_url": source.source_url,
        "external_id": source.external_id,
        "title": source.title,
        "author": source.author,
        "captured_at": _timestamp(source.captured_at),
        "original_filename": source.original_filename,
        "mime_type": source.mime_type,
        "byte_size": source.byte_size,
        "original_width": source.original_width,
        "original_height": source.original_height,
        "display_width": source.display_width,
        "display_height": source.display_height,
        "sha256": source.sha256,
        "metadata_json": source.metadata_json,
        "archived_at": _timestamp(source.archived_at),
        "created_at": _timestamp(source.created_at),
        "updated_at": _timestamp(source.updated_at),
    }
    if include_jobs:
        result["ingestion_jobs"] = [
            _job_json(job)
            for job in sorted(
                source.ingestion_jobs,
                key=lambda item: (item.created_at, item.id),
                reverse=True,
            )
        ]
    return result


def _metadata_payload(raw: str | None) -> dict:
    if raw is None:
        return {}
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError) as error:
        raise ApiError(
            400,
            "VALIDATION_ERROR",
            "Invalid source metadata",
            {"metadata": "Must be valid JSON"},
        ) from error
    if not isinstance(payload, dict):
        raise ApiError(
            400,
            "VALIDATION_ERROR",
            "Invalid source metadata",
            {"metadata": "Must be a JSON object"},
        )
    return payload


def _rejected_result(error: ApiError) -> dict:
    return {
        "status": "rejected",
        "error": {
            "code": error.code,
            "message": error.message,
            "fields": error.fields,
        },
    }


@blueprint.post("/sources")
def post_sources():
    metadata = _metadata_payload(request.form.get("metadata"))
    files = request.files.getlist("files")
    if not files:
        raise ApiError(400, "VALIDATION_ERROR", "No images were uploaded", {"files": "Required"})
    max_files = int(current_app.config["MAX_UPLOAD_FILES"])
    if len(files) > max_files:
        raise ApiError(
            400,
            "VALIDATION_ERROR",
            "Too many images in one upload",
            {"files": f"Upload at most {max_files} images"},
        )

    results: list[dict] = []
    storage_root = current_app.config["SOURCE_STORAGE_DIR"]
    session_factory = current_app.extensions["sqlalchemy_session_factory"]
    for file_storage in files:
        source_asset = None
        try:
            source_asset = save_source_file(file_storage, storage_root, metadata)
            with session_factory.begin() as session:
                add_source_asset(session, source_asset)
                job = add_ingestion_job(session, source_asset.id)
                session.flush()
                result = {
                    "status": "stored",
                    "source": _source_json(source_asset),
                    "job": _job_json(job),
                }
            results.append(result)
        except ApiError as error:
            if source_asset is not None:
                cleanup_source_files(source_asset, storage_root)
            results.append(_rejected_result(error))
        except Exception as error:
            if source_asset is not None:
                cleanup_source_files(source_asset, storage_root)
            current_app.logger.error(
                "Could not store uploaded source (error_type=%s)",
                type(error).__name__,
            )
            results.append(
                _rejected_result(
                    ApiError(500, "INTERNAL_ERROR", "Could not store this image")
                )
            )
    return jsonify({"results": results}), 200


@blueprint.get("/sources")
def get_sources():
    include_archived = request.args.get("include_archived", "false").strip().lower()
    if include_archived not in {"true", "false", "1", "0"}:
        raise ApiError(
            400,
            "VALIDATION_ERROR",
            "Invalid source filter",
            {"include_archived": "Must be true or false"},
        )
    sources = list_source_assets(
        get_session(), include_archived=include_archived in {"true", "1"}
    )
    return jsonify([_source_json(source, include_jobs=True) for source in sources])


@blueprint.get("/sources/<int:source_id>")
def get_source(source_id: int):
    source = get_source_asset(get_session(), source_id)
    if source is None:
        raise ApiError(404, "NOT_FOUND", "Source not found")
    return jsonify(_source_json(source, include_jobs=True))


@blueprint.patch("/sources/<int:source_id>")
def patch_source(source_id: int):
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or not payload:
        raise ApiError(
            400,
            "VALIDATION_ERROR",
            "Invalid source update",
            {"body": "Expected a non-empty JSON object"},
        )
    allowed = {
        "platform",
        "source_url",
        "external_id",
        "title",
        "author",
        "captured_at",
        "metadata_json",
    }
    unknown = set(payload) - allowed
    if unknown:
        raise ApiError(
            400,
            "VALIDATION_ERROR",
            "Invalid source update",
            {"body": f"Unsupported fields: {', '.join(sorted(unknown))}"},
        )
    if "metadata_json" in payload and not isinstance(payload["metadata_json"], dict):
        raise ApiError(
            400,
            "VALIDATION_ERROR",
            "Invalid source update",
            {"metadata_json": "Must be an object"},
        )
    if "captured_at" in payload and payload["captured_at"] is not None:
        value = payload["captured_at"]
        if not isinstance(value, str):
            raise ApiError(
                400,
                "VALIDATION_ERROR",
                "Invalid source update",
                {"captured_at": "Must be an ISO-8601 string"},
            )
        try:
            payload["captured_at"] = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise ApiError(
                400,
                "VALIDATION_ERROR",
                "Invalid source update",
                {"captured_at": "Must be an ISO-8601 string"},
            ) from error

    session: Session = get_session()
    with session.begin():
        source = session.get(SourceAsset, source_id)
        if source is None:
            raise ApiError(404, "NOT_FOUND", "Source not found")
        for field, value in payload.items():
            setattr(source, field, value)
        session.flush()
    source = get_source_asset(session, source_id)
    return jsonify(_source_json(source, include_jobs=True))


@blueprint.post("/sources/<int:source_id>/archive")
def archive_source(source_id: int):
    session: Session = get_session()
    with session.begin():
        source = session.get(SourceAsset, source_id)
        if source is None:
            raise ApiError(404, "NOT_FOUND", "Source not found")
        if source.archived_at is None:
            source.archived_at = datetime.now(timezone.utc)
        session.flush()
    source = get_source_asset(session, source_id)
    return jsonify(_source_json(source, include_jobs=True))


def _image_file(relative_path: str, mime_type: str, download_name: str | None):
    path = resolve_storage_path(current_app.config["SOURCE_STORAGE_DIR"], relative_path)
    if not path.is_file():
        raise ApiError(404, "NOT_FOUND", "Source image not found")
    return send_file(path, mimetype=mime_type, download_name=download_name, conditional=True)


@blueprint.get("/sources/<int:source_id>/original")
def get_source_original(source_id: int):
    source = get_source_asset(get_session(), source_id)
    if source is None:
        raise ApiError(404, "NOT_FOUND", "Source not found")
    return _image_file(source.original_path, source.mime_type, source.original_filename)


@blueprint.get("/sources/<int:source_id>/display")
def get_source_display(source_id: int):
    source = get_source_asset(get_session(), source_id)
    if source is None:
        raise ApiError(404, "NOT_FOUND", "Source not found")
    return _image_file(source.display_preview_path, "image/png", None)
