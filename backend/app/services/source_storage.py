from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from io import BytesIO
import os
from pathlib import Path
import tempfile
from typing import Any
from uuid import uuid4
import warnings

from flask import current_app
from PIL import Image, ImageOps
from werkzeug.datastructures import FileStorage

from app.errors import ApiError
from app.models.ingestion import SourceAsset


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
