from __future__ import annotations

import hashlib
import io
import json
import os
import sqlite3
import zipfile
from pathlib import Path

import pytest
from PIL import Image
from werkzeug.datastructures import FileStorage

from app import create_app
from app.models.ingestion import IngestionJob, OCRBlock, QuestionSource, QuestionSourceOCRBlock
from app.models.question import Question, QuestionState
from app.services.backups import BackupError, create_backup, inspect_backup, restore_backup
from app.services.source_storage import save_source_file
import app.services.backups as backups


@pytest.fixture
def clean_llm_environment(monkeypatch):
    for name in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"):
        monkeypatch.delenv(name, raising=False)


def create_question(client, text="Explain snapshot isolation"):
    response = client.post("/api/v1/questions", json={"text": text})
    assert response.status_code == 201, response.get_json()
    return response.get_json()["id"]


def add_source_evidence(app, db_session, question_id):
    image = Image.new("RGB", (12, 9), color=(30, 100, 130))
    image_bytes = io.BytesIO()
    image.save(image_bytes, format="PNG")
    image_bytes.seek(0)
    with app.app_context():
        source = save_source_file(
            FileStorage(stream=image_bytes, filename="practice.png", content_type="image/png"),
            app.config["SOURCE_STORAGE_DIR"],
            {},
        )
    db_session.add(source)
    db_session.flush()
    job = IngestionJob(source_asset_id=source.id, status="succeeded", stage="completed")
    db_session.add(job)
    db_session.flush()
    block = OCRBlock(
        ingestion_job_id=job.id,
        text="Source evidence block",
        bbox_json={"x": 1, "y": 2, "width": 8, "height": 3},
        reading_order=0,
    )
    db_session.add(block)
    db_session.flush()
    source_row = QuestionSource(
        question_id=question_id,
        source_asset_id=source.id,
        locator_json={"x": 1, "y": 2, "width": 8, "height": 3},
        source_text_snapshot="Explain snapshot isolation",
        raw_ocr_text_snapshot="Source evidence block",
    )
    db_session.add(source_row)
    db_session.flush()
    db_session.add(QuestionSourceOCRBlock(question_source_id=source_row.id, ocr_block_id=block.id))
    db_session.commit()
    return source.id, source_row.id, block.id


def seed_backup_data(client, app, db_session):
    question_id = create_question(client)
    answer_response = client.post(
        f"/api/v1/questions/{question_id}/saved-answers", json={"content": "My saved answer"}
    )
    assert answer_response.status_code == 201, answer_response.get_json()
    answer = answer_response.get_json()
    session_response = client.post("/api/v1/practice-sessions", json={"mode": "random", "limit": 1})
    assert session_response.status_code == 201, session_response.get_json()
    practice_session = session_response.get_json()
    session_item_id = practice_session["items"][0]["id"]
    review_response = client.post(
        f"/api/v1/session-items/{session_item_id}/review", json={"review_rating": "basic"}
    )
    assert review_response.status_code == 201, review_response.get_json()

    project_response = client.post(
        "/api/v1/projects", json={"name": "Backup Project", "summary": "Versioned project facts"}
    )
    assert project_response.status_code == 201, project_response.get_json()
    material_response = client.post(
        "/api/v1/materials",
        data={"file": (io.BytesIO(b"Material evidence for backup"), "notes.md"), "kind": "readme"},
        content_type="multipart/form-data",
    )
    assert material_response.status_code == 201, material_response.get_json()
    source_id, source_row_id, block_id = add_source_evidence(app, db_session, question_id)
    return {
        "question_id": question_id,
        "answer_id": answer["id"],
        "answer_version_id": answer["current_version"]["id"],
        "session_id": practice_session["id"],
        "session_item_id": session_item_id,
        "review_id": review_response.get_json()["id"],
        "material_id": material_response.get_json()["id"],
        "material_version_id": material_response.get_json()["current_version"]["id"],
        "source_id": source_id,
        "source_row_id": source_row_id,
        "ocr_block_id": block_id,
    }


def test_backup_online_snapshot_restores_database_and_immutable_files(client, app, db_session, tmp_path):
    ids = seed_backup_data(client, app, db_session)
    engine = app.extensions["sqlalchemy_engine"]
    with sqlite3.connect(engine.url.database) as wal_connection:
        wal_connection.execute("PRAGMA journal_mode=WAL")
    with engine.begin() as connection:
        connection.exec_driver_sql("UPDATE project SET summary = 'WAL committed project fact'")

    archive_path, _cleanup = create_backup(app)
    archive_path = Path(archive_path)
    try:
        info = inspect_backup(archive_path)
        assert info["backup_format_version"] == 1
        with zipfile.ZipFile(archive_path) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            names = set(archive.namelist())
            assert "database/interview_assistant.sqlite3" in names
            assert any(name.startswith("files/sources/original/") for name in names)
            assert any(name.startswith("files/sources/display/") for name in names)
            assert any(name.startswith("files/materials/") for name in names)
            for entry in manifest["files"]:
                payload = archive.read(entry["path"])
                assert len(payload) == entry["size"]
                assert hashlib.sha256(payload).hexdigest() == entry["sha256"]

        restored_dir = tmp_path / "restored-data"
        result = restore_backup(archive_path, restored_dir)
        assert result["restored_to"] == str(restored_dir)
        restored_db = restored_dir / "interview_assistant.sqlite3"
        with sqlite3.connect(restored_db) as connection:
            assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
            assert connection.execute("SELECT summary FROM project").fetchone()[0] == "WAL committed project fact"
            assert connection.execute("SELECT id FROM question").fetchone()[0] == ids["question_id"]
            assert connection.execute("SELECT id FROM saved_answer").fetchone()[0] == ids["answer_id"]
            assert connection.execute("SELECT id FROM saved_answer_version").fetchone()[0] == ids["answer_version_id"]
            assert connection.execute("SELECT id FROM practice_session WHERE id = ?", (ids["session_id"],)).fetchone()[0] == ids["session_id"]
            assert connection.execute("SELECT id FROM session_item WHERE id = ?", (ids["session_item_id"],)).fetchone()[0] == ids["session_item_id"]
            assert connection.execute("SELECT id FROM practice_review WHERE id = ?", (ids["review_id"],)).fetchone()[0] == ids["review_id"]
            assert connection.execute(
                "SELECT id FROM material_version WHERE id = ?", (ids["material_version_id"],)
            ).fetchone()[0] == ids["material_version_id"]
            assert connection.execute("SELECT id FROM question_source").fetchone()[0] == ids["source_row_id"]
            assert connection.execute("SELECT id FROM ocr_block").fetchone()[0] == ids["ocr_block_id"]
            assert connection.execute("SELECT count(*) FROM question_source_ocr_block").fetchone()[0] == 1
            original_path = connection.execute(
                "SELECT original_path FROM source_asset WHERE id = ?", (ids["source_id"],)
            ).fetchone()[0]
            material_path = connection.execute(
                "SELECT path FROM material_version WHERE id = ?", (ids["material_version_id"],)
            ).fetchone()[0]
        assert (restored_dir / "sources" / original_path).is_file()
        assert (restored_dir / "materials" / material_path).is_file()
    finally:
        _cleanup()


def test_backup_refuses_tampered_archive_without_touching_existing_data(client, app, tmp_path):
    archive_path, cleanup = create_backup(app)
    archive_path = Path(archive_path)
    tampered = tmp_path / "tampered.zip"
    try:
        with zipfile.ZipFile(archive_path) as source, zipfile.ZipFile(tampered, "w") as target:
            for name in source.namelist():
                payload = source.read(name)
                if name == "database/interview_assistant.sqlite3":
                    payload += b"tampered"
                target.writestr(name, payload)
        existing = tmp_path / "existing-data"
        existing.mkdir()
        sentinel = existing / "keep.txt"
        sentinel.write_text("existing user data", encoding="utf-8")
        with pytest.raises(BackupError):
            restore_backup(tampered, existing, replace_existing=True, confirmed=True)
        assert sentinel.read_text(encoding="utf-8") == "existing user data"
        assert not (tmp_path / "existing-data.pre-restore").exists()
        traversal = tmp_path / "traversal.zip"
        with zipfile.ZipFile(archive_path) as source, zipfile.ZipFile(traversal, "w") as target_zip:
            for name in source.namelist():
                target_zip.writestr(name, source.read(name))
            target_zip.writestr("../../outside.txt", b"unsafe")
        with pytest.raises(BackupError):
            inspect_backup(traversal)
        assert not (tmp_path.parent / "outside.txt").exists()
    finally:
        cleanup()


def test_replace_restore_preserves_previous_directory(client, app, tmp_path):
    client.post("/api/v1/questions", json={"text": "Recoverable content"})
    archive_path, cleanup = create_backup(app)
    target = tmp_path / "existing-app-data"
    target.mkdir()
    (target / "keep.txt").write_text("old local state", encoding="utf-8")
    try:
        with pytest.raises(BackupError):
            restore_backup(archive_path, target)
        result = restore_backup(archive_path, target, replace_existing=True, confirmed=True)
        preserved = Path(result["previous_data_preserved_at"])
        assert (preserved / "keep.txt").read_text(encoding="utf-8") == "old local state"
        assert (target / "interview_assistant.sqlite3").is_file()
    finally:
        cleanup()


def test_restore_refuses_data_directory_with_running_service_marker(client, app, tmp_path):
    client.post("/api/v1/questions", json={"text": "Live data directory"})
    archive_path, cleanup = create_backup(app)
    target = tmp_path / "live-data"
    target.mkdir()
    marker = target / ".agent-interview-assistant.pid"
    marker.write_text(str(os.getpid()), encoding="ascii")
    keep = target / "keep.txt"
    keep.write_text("service still owns this directory", encoding="utf-8")
    try:
        with pytest.raises(BackupError, match="仍在运行"):
            restore_backup(archive_path, target, replace_existing=True, confirmed=True)
        assert keep.read_text(encoding="utf-8") == "service still owns this directory"
        assert marker.exists()
    finally:
        cleanup()


def test_backup_fails_if_database_changes_while_assets_are_copied(client, app, monkeypatch):
    client.post("/api/v1/projects", json={"name": "Concurrent change"})
    original_copy = backups._hash_copy_to_zip
    changed = False

    def copy_with_concurrent_write(path, archive, name, expected):
        nonlocal changed
        result = original_copy(path, archive, name, expected)
        if name.startswith("files/materials/") and not changed:
            with app.extensions["sqlalchemy_engine"].begin() as connection:
                connection.exec_driver_sql("UPDATE project SET summary = 'changed during snapshot'")
            changed = True
        return result

    monkeypatch.setattr(backups, "_hash_copy_to_zip", copy_with_concurrent_write)
    with pytest.raises(BackupError, match="数据库发生变化"):
        create_backup(app)


def test_dashboard_uses_live_counts_and_links_recent_answer(client, db_session):
    question_id = create_question(client, "Dashboard due question")
    project_response = client.post("/api/v1/projects", json={"name": "Dashboard project", "summary": "Current project"})
    assert project_response.status_code == 201
    answer_response = client.post(
        f"/api/v1/questions/{question_id}/saved-answers", json={"content": "Recent answer"}
    )
    assert answer_response.status_code == 201
    db_session.add(
        Question(
            text="Pending OCR candidate",
            normalized_text="pending ocr candidate",
            search_text="pending ocr candidate",
            normalized_hash=hashlib.sha256(b"pending ocr candidate").hexdigest(),
            status="pending_review",
            ingestion_candidate_state="pending_review",
        )
    )
    state = db_session.get(QuestionState, question_id)
    assert state is not None
    state.next_review_at = state.updated_at.replace(year=2020)
    db_session.commit()

    response = client.get("/api/v1/dashboard")
    assert response.status_code == 200, response.get_json()
    payload = response.get_json()
    assert payload["due_question_count"] == 1
    assert payload["pending_candidate_count"] == 1
    assert payload["active_question_count"] == 1
    assert payload["practice_session_count"] == 0
    assert payload["unfinished_session"] is None
    assert payload["recent_answers"][0]["question_id"] == question_id
    assert payload["recent_answers"][0]["question_text"] == "Dashboard due question"
    assert payload["active_project_count"] == 1
    assert payload["recent_materials"][0]["is_system_managed"] is True
    assert payload["recent_materials"][0]["project_id"] == project_response.get_json()["id"]


def test_provider_settings_are_private_and_survive_app_restart(clean_llm_environment, app, client):
    response = client.patch(
        "/api/v1/llm/config",
        json={"base_url": "http://localhost:57680/v1", "model": "gpt-6-luna", "api_key": "test-key-never-echo"},
    )
    assert response.status_code == 200, response.get_json()
    assert "test-key-never-echo" not in response.get_data(as_text=True)
    provider_dir = Path(app.config["APP_DATA_DIR"]) / "provider"
    secret_path = provider_dir / "api-key"
    settings_path = provider_dir / "settings.json"
    assert secret_path.read_text(encoding="utf-8") == "test-key-never-echo"
    assert settings_path.stat().st_mode & 0o777 == 0o600
    assert secret_path.stat().st_mode & 0o777 == 0o600
    assert provider_dir.stat().st_mode & 0o777 == 0o700
    assert "test-key-never-echo" not in settings_path.read_text(encoding="utf-8")

    config = {
        "TESTING": True,
        "PROPAGATE_EXCEPTIONS": False,
        "APP_DATA_DIR": app.config["APP_DATA_DIR"],
        "SOURCE_STORAGE_DIR": app.config["SOURCE_STORAGE_DIR"],
        "DATABASE_URL": app.config["DATABASE_URL"],
        "SEED_TOPICS_ON_STARTUP": False,
    }
    app.extensions["sqlalchemy_engine"].dispose()
    restarted = create_app(config)
    try:
        restarted_client = restarted.test_client()
        public = restarted_client.get("/api/v1/llm/config").get_json()
        assert public["base_url"] == "http://localhost:57680/v1"
        assert public["model"] == "gpt-6-luna"
        assert public["has_api_key"] is True
        assert "test-key-never-echo" not in json.dumps(public)
        cleared = restarted_client.patch("/api/v1/llm/config", json={"clear_api_key": True})
        assert cleared.status_code == 200 and cleared.get_json()["has_api_key"] is False
        assert not secret_path.exists()
    finally:
        restarted.extensions["sqlalchemy_engine"].dispose()


def test_backup_never_contains_provider_secret(client, app):
    response = client.patch(
        "/api/v1/llm/config",
        json={"base_url": "http://localhost:57680/v1", "model": "gpt-6-luna", "api_key": "backup-secret"},
    )
    assert response.status_code == 200
    archive_path, cleanup = create_backup(app)
    try:
        with zipfile.ZipFile(archive_path) as archive:
            assert all("provider" not in name for name in archive.namelist())
            assert all(b"backup-secret" not in archive.read(name) for name in archive.namelist())
    finally:
        cleanup()


def test_backup_http_export_can_be_checked_before_offline_restore(client, app):
    client.post("/api/v1/questions", json={"text": "HTTP backup question"})
    exported = client.get("/api/v1/backups/export")
    assert exported.status_code == 200
    assert exported.mimetype == "application/zip"
    checked = client.post(
        "/api/v1/backups/inspect",
        data={"file": (io.BytesIO(exported.data), "backup.zip")},
        content_type="multipart/form-data",
    )
    assert checked.status_code == 200, checked.get_json()
    assert checked.get_json()["valid"] is True
    assert checked.get_json()["data_counts"]["questions"] == 1
