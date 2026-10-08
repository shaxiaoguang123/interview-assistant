from io import BytesIO
import json
import os
from pathlib import Path
from uuid import uuid4

from PIL import Image
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.models.ingestion import IngestionJob, QuestionSource, SourceAsset
from app.models.question import Question


def _storage_deletion_api():
    import app.services.source_storage as source_storage

    assert callable(getattr(source_storage, "recover_source_tombstones", None)), (
        "missing feature: source tombstone recovery"
    )
    assert callable(getattr(source_storage, "source_tombstone_directory", None)), (
        "missing feature: source tombstone directory"
    )
    return source_storage


def _png_bytes():
    stream = BytesIO()
    Image.new("RGB", (20, 12), color=(70, 90, 120)).save(stream, format="PNG")
    return stream.getvalue()


def _upload_source(client, name="delete-test.png"):
    response = client.post(
        "/api/v1/sources",
        data={"files": (BytesIO(_png_bytes()), name)},
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    result = response.get_json()["results"][0]
    assert result["status"] == "stored"
    return result["source"], result["job"]


def _path_for(app, source: SourceAsset, relative_path: str) -> Path:
    return Path(app.config["SOURCE_STORAGE_DIR"]) / relative_path


def _add_candidate_with_source(app, source_id: int, job_id: int) -> tuple[int, int]:
    with app.extensions["sqlalchemy_session_factory"].begin() as session:
        candidate = Question(
            text="Referenced OCR question",
            normalized_text="referenced ocr question",
            search_text="referenced ocr question",
            normalized_hash=str(uuid4().hex),
            status="pending_review",
            origin_ingestion_job_id=job_id,
            ingestion_candidate_state="pending_review",
        )
        session.add(candidate)
        session.flush()
        source = QuestionSource(
            question_id=candidate.id,
            source_asset_id=source_id,
            locator_type="image_region",
            locator_json={"x": 0.1, "y": 0.1, "width": 0.4, "height": 0.1},
            source_text_snapshot="Referenced OCR question",
            raw_ocr_text_snapshot="Referenced OCR question",
        )
        session.add(source)
        session.flush()
        return candidate.id, source.id


def _write_tombstone(app, source: SourceAsset, asset_id: int, *, move_files: bool):
    source_storage = _storage_deletion_api()
    root = Path(app.config["SOURCE_STORAGE_DIR"]).resolve()
    tombstone_root = source_storage.source_tombstone_directory(root)
    directory = tombstone_root / ("asset-" + str(asset_id) + "-test")
    directory.mkdir(parents=True, exist_ok=True)
    original = root / source.original_path
    display = root / source.display_preview_path
    tomb_original = directory / "original.bin"
    tomb_display = directory / "display.png"
    manifest = {
        "source_asset_id": asset_id,
        "original_path": source.original_path,
        "display_preview_path": source.display_preview_path,
    }
    (directory / "journal.json").write_text(json.dumps(manifest), encoding="utf-8")
    if move_files:
        os.replace(original, tomb_original)
        os.replace(display, tomb_display)
    return directory, original, display, tomb_original, tomb_display


def test_delete_source_with_candidate_or_source_reference_returns_409(client, app):
    _storage_deletion_api()
    source, job = _upload_source(client)
    _add_candidate_with_source(app, source["id"], job["id"])

    response = client.delete("/api/v1/sources/" + str(source["id"]))

    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "CONFLICT"
    assert client.get(f"/api/v1/sources/{source['id']}/original").status_code == 200


def test_archived_source_stays_hidden_from_default_list_but_keeps_image_and_history(client, app):
    source, job = _upload_source(client)
    candidate_id, question_source_id = _add_candidate_with_source(
        app, source["id"], job["id"]
    )

    archived = client.post(f"/api/v1/sources/{source['id']}/archive")
    default_list = client.get("/api/v1/sources")
    include_archived = client.get("/api/v1/sources?include_archived=true")
    original = client.get(f"/api/v1/sources/{source['id']}/original")
    history = client.get(f"/api/v1/questions/{candidate_id}/sources")

    assert archived.status_code == 200
    assert archived.get_json()["archived_at"] is not None
    assert default_list.get_json() == []
    assert include_archived.get_json()[0]["id"] == source["id"]
    assert original.status_code == 200
    assert history.status_code == 200
    assert history.get_json()[0]["question_source_id"] == question_source_id


def test_delete_source_with_attempted_job_history_returns_409(client, app):
    _storage_deletion_api()
    source, job = _upload_source(client)
    with app.extensions["sqlalchemy_session_factory"].begin() as session:
        row = session.get(IngestionJob, job["id"])
        row.status = "failed"
        row.stage = "recognizing"
        row.failure_stage = "recognizing"

    response = client.delete("/api/v1/sources/" + str(source["id"]))

    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "CONFLICT"
    assert client.get(f"/api/v1/sources/{source['id']}/original").status_code == 200


def test_unreferenced_queued_source_delete_removes_generated_files_and_rows(client, app):
    _storage_deletion_api()
    source, job = _upload_source(client)
    source_path = Path(app.config["SOURCE_STORAGE_DIR"])
    with app.app_context():
        session = app.extensions["sqlalchemy_session_factory"]()
        row = session.get(SourceAsset, source["id"])
        original = _path_for(app, row, row.original_path)
        display = _path_for(app, row, row.display_preview_path)
        session.close()
    assert original.is_file()
    assert display.is_file()

    response = client.delete("/api/v1/sources/" + str(source["id"]))

    assert response.status_code == 200
    assert response.get_json()["deleted"] is True
    assert not original.exists()
    assert not display.exists()
    with app.app_context():
        session = app.extensions["sqlalchemy_session_factory"]()
        assert session.get(SourceAsset, source["id"]) is None
        assert session.get(IngestionJob, job["id"]) is None
        session.close()
    assert not list(source_path.glob(".tombstones/*/journal.json"))


def test_db_failure_restores_original_and_preview_from_tombstone(client, app):
    _storage_deletion_api()
    source, _job = _upload_source(client)
    with app.app_context():
        session = app.extensions["sqlalchemy_session_factory"]()
        row = session.get(SourceAsset, source["id"])
        original_path = _path_for(app, row, row.original_path)
        display_path = _path_for(app, row, row.display_preview_path)
        session.close()
    original_bytes = original_path.read_bytes()
    display_bytes = display_path.read_bytes()

    def fail_source_delete(session, _flush_context, _instances):
        if any(isinstance(item, SourceAsset) for item in session.deleted):
            raise RuntimeError("simulated DB delete failure")

    event.listen(Session, "before_flush", fail_source_delete)
    try:
        response = client.delete("/api/v1/sources/" + str(source["id"]))
    finally:
        event.remove(Session, "before_flush", fail_source_delete)

    assert response.status_code == 500
    assert original_path.read_bytes() == original_bytes
    assert display_path.read_bytes() == display_bytes
    assert not list(Path(app.config["SOURCE_STORAGE_DIR"]).glob(".tombstones/*/journal.json"))
    with app.app_context():
        session = app.extensions["sqlalchemy_session_factory"]()
        assert session.get(SourceAsset, source["id"]) is not None
        session.close()


def test_restart_recovers_tombstone_when_source_row_exists(app):
    source_storage = _storage_deletion_api()
    with app.test_client() as client:
        source_json, _job = _upload_source(client)
    with app.app_context():
        session = app.extensions["sqlalchemy_session_factory"]()
        source = session.get(SourceAsset, source_json["id"])
        directory, original, display, tomb_original, tomb_display = _write_tombstone(
            app, source, source.id, move_files=True
        )
        session.close()

    recovered = source_storage.recover_source_tombstones(
        app.extensions["sqlalchemy_session_factory"],
        app.config["SOURCE_STORAGE_DIR"],
    )

    assert recovered == 1
    assert original.is_file()
    assert display.is_file()
    assert not tomb_original.exists()
    assert not tomb_display.exists()
    assert not directory.exists()


def test_restart_cleans_tombstone_after_committed_delete(app):
    source_storage = _storage_deletion_api()
    with app.test_client() as client:
        source_json, _job = _upload_source(client)
    with app.app_context():
        session = app.extensions["sqlalchemy_session_factory"]()
        source = session.get(SourceAsset, source_json["id"])
        directory, original, display, tomb_original, tomb_display = _write_tombstone(
            app, source, source.id, move_files=True
        )
        session.close()
        with app.extensions["sqlalchemy_session_factory"].begin() as session:
            source = session.get(SourceAsset, source_json["id"])
            job = session.get(IngestionJob, source.ingestion_jobs[0].id)
            session.delete(job)
            session.delete(source)

    recovered = source_storage.recover_source_tombstones(
        app.extensions["sqlalchemy_session_factory"],
        app.config["SOURCE_STORAGE_DIR"],
    )

    assert recovered == 1
    assert not tomb_original.exists()
    assert not tomb_display.exists()
    assert not original.exists()
    assert not display.exists()
    assert not directory.exists()
