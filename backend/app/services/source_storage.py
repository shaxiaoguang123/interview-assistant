from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import tempfile
from typing import Any
from uuid import uuid4
import warnings

from flask import current_app
from PIL import Image, ImageOps
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session
from werkzeug.datastructures import FileStorage

from app.errors import ApiError
from app.models.ingestion import IngestionJob, OCRBlock, QuestionSource, SourceAsset
from app.models.question import Question


_FORMAT_TO_MIME = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
}
_EXTENSION_TO_FORMAT = {
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".png": "PNG",
    ".webp": "WEBP",
}
_ALLOWED_METADATA_FIELDS = {
    "platform",
    "source_url",
    "external_id",
    "title",
    "author",
    "captured_at",
    "metadata_json",
}


def _validation_error(message: str, field: str = "file") -> ApiError:
    return ApiError(400, "VALIDATION_ERROR", message, {field: message})


def _parse_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    if metadata is None:
        return {}
    if not isinstance(metadata, dict):
        raise _validation_error("Metadata must be a JSON object", "metadata")
    unknown = set(metadata) - _ALLOWED_METADATA_FIELDS
    if unknown:
        raise _validation_error(
            f"Unsupported metadata fields: {', '.join(sorted(unknown))}",
            "metadata",
        )
    data = dict(metadata)
    captured_at = data.get("captured_at")
    if captured_at is not None:
        if not isinstance(captured_at, str):
            raise _validation_error("captured_at must be an ISO-8601 string", "metadata")
        try:
            data["captured_at"] = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
        except ValueError as error:
            raise _validation_error("captured_at must be an ISO-8601 string", "metadata") from error
    extra = data.get("metadata_json", {})
    if not isinstance(extra, dict):
        raise _validation_error("metadata_json must be an object", "metadata")
    data["metadata_json"] = extra
    return data


def _read_original(file_storage: FileStorage, max_bytes: int) -> bytes:
    payload = file_storage.stream.read(max_bytes + 1)
    if len(payload) > max_bytes:
        raise _validation_error("Image exceeds the per-file size limit")
    if not payload:
        raise _validation_error("Image file is empty")
    return payload


def _decode_and_orient(
    payload: bytes,
    filename: str | None,
    declared_mime: str | None,
    max_pixels: int,
):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            image = Image.open(BytesIO(payload))
            detected_format = image.format
            if detected_format not in _FORMAT_TO_MIME:
                raise _validation_error("Only JPEG, PNG, and WebP images are supported")
            original_width, original_height = image.size
            if original_width * original_height > max_pixels:
                raise _validation_error("Image exceeds the decoded pixel limit")

            extension = Path(filename or "").suffix.lower()
            expected_format = _EXTENSION_TO_FORMAT.get(extension)
            if extension and expected_format != detected_format:
                raise _validation_error("Filename extension does not match image content")

            detected_mime = _FORMAT_TO_MIME[detected_format]
            declared_mime = (declared_mime or "").lower()
            if declared_mime not in {"", "application/octet-stream", detected_mime}:
                raise _validation_error("Declared MIME type does not match image content")

            image.load()
            oriented = ImageOps.exif_transpose(image)
            oriented.load()
            display_width, display_height = oriented.size
            has_alpha = "A" in oriented.getbands()
            preview = oriented.convert("RGBA" if has_alpha else "RGB")
            return (
                detected_mime,
                original_width,
                original_height,
                display_width,
                display_height,
                preview,
            )
    except ApiError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        raise _validation_error("Image exceeds the decoded pixel limit") from error
    except Exception as error:
        raise _validation_error("Image bytes could not be decoded") from error


def _write_temp(directory: Path, asset_key: str, suffix: str, payload: bytes) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="wb",
        prefix=f".{asset_key}-",
        suffix=suffix,
        dir=directory,
        delete=False,
    ) as temporary:
        temporary.write(payload)
        temporary.flush()
        os.fsync(temporary.fileno())
        return Path(temporary.name)


def _remove_path(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        current_app.logger.warning("Could not remove a temporary source file")


def resolve_storage_path(storage_root: str | Path, relative_path: str) -> Path:
    root = Path(storage_root).expanduser().resolve()
    path = (root / relative_path).resolve()
    if path == root or root not in path.parents:
        raise ApiError(404, "NOT_FOUND", "Source file not found")
    return path


def cleanup_source_files(source_asset: SourceAsset, storage_root: str | Path) -> None:
    for relative_path in (source_asset.original_path, source_asset.display_preview_path):
        try:
            resolve_storage_path(storage_root, relative_path).unlink(missing_ok=True)
        except (OSError, ApiError):
            current_app.logger.warning("Could not clean up a source file after a failed transaction")


def source_tombstone_directory(storage_root: str | Path) -> Path:
    return Path(storage_root).expanduser().resolve() / ".tombstones"


def _assert_source_is_unreferenced(
    session: Session,
    source_asset_id: int,
) -> tuple[SourceAsset, list[int]]:
    source = session.get(SourceAsset, source_asset_id)
    if source is None:
        raise ApiError(404, "NOT_FOUND", "Source not found")

    if session.scalar(
        select(func.count())
        .select_from(QuestionSource)
        .where(QuestionSource.source_asset_id == source_asset_id)
    ):
        raise ApiError(
            409,
            "CONFLICT",
            "Source has question history and cannot be permanently deleted",
        )

    jobs = list(
        session.scalars(
            select(IngestionJob)
            .where(IngestionJob.source_asset_id == source_asset_id)
            .order_by(IngestionJob.id)
        )
    )
    job_ids = [job.id for job in jobs]
    if job_ids:
        if any(job.status != "queued" or job.started_at is not None for job in jobs):
            raise ApiError(
                409,
                "CONFLICT",
                "Source has attempted OCR history and cannot be permanently deleted",
            )
        if session.scalar(
            select(func.count())
            .select_from(Question)
            .where(Question.origin_ingestion_job_id.in_(job_ids))
        ):
            raise ApiError(
                409,
                "CONFLICT",
                "Source has candidate history and cannot be permanently deleted",
            )
        if session.scalar(
            select(func.count())
            .select_from(OCRBlock)
            .where(OCRBlock.ingestion_job_id.in_(job_ids))
        ):
            raise ApiError(
                409,
                "CONFLICT",
                "Source has OCR block history and cannot be permanently deleted",
            )
    return source, job_ids


def _write_tombstone_manifest(directory: Path, manifest: dict[str, Any]) -> Path:
    directory.mkdir(parents=True, exist_ok=False)
    temporary = _write_temp(
        directory,
        "journal",
        ".tmp",
        json.dumps(manifest, sort_keys=True).encode("utf-8"),
    )
    journal_path = directory / "journal.json"
    os.replace(temporary, journal_path)
    return journal_path


def _restore_tombstone_files(
    directory: Path,
    storage_root: Path,
    manifest: dict[str, Any],
) -> None:
    pairs = (
        ("original.bin", manifest["original_path"]),
        ("display.png", manifest["display_preview_path"]),
    )
    for tombstone_name, relative_path in pairs:
        tombstone_path = directory / tombstone_name
        destination = resolve_storage_path(storage_root, relative_path)
        if not tombstone_path.exists():
            # A path not moved yet remains at its normal destination.
            if destination.is_file():
                continue
            raise OSError("A tombstone and its source file are both missing")
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            if sha256(destination.read_bytes()).digest() != sha256(tombstone_path.read_bytes()).digest():
                raise OSError("A source path is occupied by different data")
            tombstone_path.unlink()
        else:
            os.replace(tombstone_path, destination)


def _remove_tombstone_directory(directory: Path) -> None:
    if not directory.exists():
        return
    for item in directory.iterdir():
        if item.is_file():
            item.unlink()
    directory.rmdir()


def delete_unreferenced_source(
    session_factory,
    source_asset_id: int,
    storage_root: str | Path,
) -> None:
    storage_root = Path(storage_root).expanduser().resolve()
    with session_factory() as session:
        source, _job_ids = _assert_source_is_unreferenced(session, source_asset_id)
        original_path = resolve_storage_path(storage_root, source.original_path)
        display_path = resolve_storage_path(storage_root, source.display_preview_path)
        if not original_path.is_file() or not display_path.is_file():
            raise ApiError(409, "CONFLICT", "Source files are incomplete; archive the source instead")
        manifest = {
            "source_asset_id": source.id,
            "original_path": source.original_path,
            "display_preview_path": source.display_preview_path,
        }

    tombstone_root = source_tombstone_directory(storage_root)
    tombstone_directory = tombstone_root / ("asset-" + str(source_asset_id) + "-" + uuid4().hex)
    _write_tombstone_manifest(tombstone_directory, manifest)
    try:
        os.replace(original_path, tombstone_directory / "original.bin")
        os.replace(display_path, tombstone_directory / "display.png")
        with session_factory.begin() as session:
            source, job_ids = _assert_source_is_unreferenced(session, source_asset_id)
            if job_ids:
                session.execute(
                    delete(IngestionJob)
                    .where(
                        IngestionJob.source_asset_id == source_asset_id,
                        IngestionJob.status == "queued",
                        IngestionJob.started_at.is_(None),
                    )
                    .execution_options(synchronize_session=False)
                )
            session.delete(source)
            session.flush()
    except Exception:
        try:
            _restore_tombstone_files(tombstone_directory, storage_root, manifest)
            _remove_tombstone_directory(tombstone_directory)
        except OSError as restore_error:
            current_app.logger.error(
                "Could not restore source tombstone (error_type=%s)",
                type(restore_error).__name__,
            )
            raise ApiError(
                500,
                "INTERNAL_ERROR",
                "Source deletion failed and its files need local recovery",
            ) from restore_error
        raise
    else:
        try:
            _remove_tombstone_directory(tombstone_directory)
        except OSError:
            # The committed delete is authoritative; startup removes this journal.
            current_app.logger.warning("Committed source tombstone cleanup is pending")


def recover_source_tombstones(session_factory, storage_root: str | Path) -> int:
    storage_root = Path(storage_root).expanduser().resolve()
    tombstone_root = source_tombstone_directory(storage_root)
    if not tombstone_root.exists():
        return 0
    recovered = 0
    for directory in sorted(tombstone_root.iterdir()):
        if not directory.is_dir():
            continue
        journal_path = directory / "journal.json"
        if not journal_path.is_file():
            # No move can occur before the durable journal is in place.
            _remove_tombstone_directory(directory)
            continue
        try:
            manifest = json.loads(journal_path.read_text(encoding="utf-8"))
            source_asset_id = manifest["source_asset_id"]
            if not isinstance(source_asset_id, int):
                raise ValueError("invalid source ID")
            original = resolve_storage_path(storage_root, manifest["original_path"])
            display = resolve_storage_path(storage_root, manifest["display_preview_path"])
        except (OSError, ValueError, KeyError, TypeError, ApiError) as error:
            current_app.logger.error(
                "Source tombstone journal is invalid (error_type=%s)",
                type(error).__name__,
            )
            raise ApiError(
                500,
                "INTERNAL_ERROR",
                "A source deletion journal needs local recovery",
            ) from error

        with session_factory() as session:
            source = session.get(SourceAsset, source_asset_id)
            source_matches_journal = (
                source is not None
                and source.original_path == manifest["original_path"]
                and source.display_preview_path == manifest["display_preview_path"]
            )
        try:
            if source_matches_journal:
                _restore_tombstone_files(directory, storage_root, manifest)
            else:
                for path in (directory / "original.bin", directory / "display.png"):
                    path.unlink(missing_ok=True)
            _remove_tombstone_directory(directory)
            recovered += 1
        except OSError as error:
            current_app.logger.error(
                "Source tombstone reconciliation failed (error_type=%s)",
                type(error).__name__,
            )
            raise ApiError(
                500,
                "INTERNAL_ERROR",
                "A source deletion journal could not be reconciled",
            ) from error
    return recovered


def save_source_file(
    file_storage: FileStorage,
    storage_root: str | Path,
    metadata: dict[str, Any] | None,
) -> SourceAsset:
    metadata = _parse_metadata(metadata)
    max_bytes = int(current_app.config["SOURCE_MAX_FILE_BYTES"])
    max_pixels = int(current_app.config["SOURCE_MAX_DECODED_PIXELS"])
    original_bytes = _read_original(file_storage, max_bytes)
    (
        detected_mime,
        original_width,
        original_height,
        display_width,
        display_height,
        preview,
    ) = _decode_and_orient(
        original_bytes,
        file_storage.filename,
        file_storage.mimetype,
        max_pixels,
    )

    storage_root = Path(storage_root).expanduser().resolve()
    asset_key = uuid4().hex
    original_relative = Path("original") / f"{asset_key}.bin"
    preview_relative = Path("display") / f"{asset_key}.png"
    original_path = resolve_storage_path(storage_root, str(original_relative))
    preview_path = resolve_storage_path(storage_root, str(preview_relative))
    original_temp: Path | None = None
    preview_temp: Path | None = None
    committed_paths: list[Path] = []
    try:
        original_temp = _write_temp(original_path.parent, asset_key, ".tmp", original_bytes)
        preview_stream = BytesIO()
        preview.save(preview_stream, format="PNG", optimize=False)
        preview_temp = _write_temp(
            preview_path.parent, asset_key, ".tmp", preview_stream.getvalue()
        )
        os.replace(original_temp, original_path)
        committed_paths.append(original_path)
        original_temp = None
        os.replace(preview_temp, preview_path)
        committed_paths.append(preview_path)
        preview_temp = None
    except Exception:
        for temporary in (original_temp, preview_temp):
            if temporary is not None:
                _remove_path(temporary)
        for committed in committed_paths:
            _remove_path(committed)
        raise

    fields = {
        key: metadata[key]
        for key in ("platform", "source_url", "external_id", "title", "author", "captured_at")
        if key in metadata
    }
    return SourceAsset(
        source_type="image",
        original_filename=(file_storage.filename or "")[:512] or None,
        mime_type=detected_mime,
        byte_size=len(original_bytes),
        original_width=original_width,
        original_height=original_height,
        display_width=display_width,
        display_height=display_height,
        original_path=str(original_relative),
        display_preview_path=str(preview_relative),
        sha256=sha256(original_bytes).hexdigest(),
        metadata_json=metadata.get("metadata_json", {}),
        **fields,
    )
