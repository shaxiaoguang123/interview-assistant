from __future__ import annotations

from datetime import datetime, timezone
import tempfile
from pathlib import Path

from flask import Blueprint, current_app, jsonify, request, send_file

from app.errors import ApiError
from app.services.backups import BackupError, MAX_ARCHIVE_BYTES, create_backup, inspect_backup


blueprint = Blueprint("backups_v1", __name__, url_prefix="/api/v1")


def _backup_error(error: BackupError) -> ApiError:
    return ApiError(400, "BACKUP_INVALID", str(error))


@blueprint.get("/backups/export")
def export_backup():
    try:
        archive_path, cleanup = create_backup(current_app._get_current_object())
    except BackupError as error:
        raise _backup_error(error) from error
    response = send_file(
        archive_path,
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"agent-interview-backup-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}.zip",
        max_age=0,
    )
    response.call_on_close(cleanup)
    return response


@blueprint.post("/backups/inspect")
def inspect_uploaded_backup():
    # This endpoint alone accepts larger archives; source and material uploads
    # retain their smaller per-file limits.
    request.max_content_length = int(current_app.config.get("BACKUP_MAX_UPLOAD_BYTES", MAX_ARCHIVE_BYTES))
    upload = request.files.get("file")
    if upload is None:
        raise ApiError(400, "VALIDATION_ERROR", "请选择备份 ZIP 文件。")
    with tempfile.TemporaryDirectory(prefix="backup-check-") as temporary:
        path = Path(temporary) / "selected-backup.zip"
        total = 0
        try:
            with path.open("xb") as destination:
                while chunk := upload.stream.read(1024 * 1024):
                    total += len(chunk)
                    if total > MAX_ARCHIVE_BYTES:
                        raise ApiError(413, "BACKUP_TOO_LARGE", "备份文件超过 8 GB。")
                    destination.write(chunk)
            result = inspect_backup(path)
        except BackupError as error:
            raise _backup_error(error) from error
    return jsonify(result)
