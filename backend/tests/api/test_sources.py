from io import BytesIO
import hashlib
import json
from pathlib import Path

from PIL import Image
import pytest
from sqlalchemy import event
from sqlalchemy.exc import StatementError
from sqlalchemy.orm import Session

import app.errors as api_errors
from app.models.ingestion import IngestionJob, SourceAsset


def _png_bytes(size=(4, 3), color=(10, 80, 140)):
    image = Image.new("RGB", size, color=color)
    stream = BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


def _upload(client, files, metadata=None):
    data = {"files": files}
    if metadata is not None:
        data["metadata"] = json.dumps(metadata)
    return client.post("/api/v1/sources", data=data, content_type="multipart/form-data")


def _stored_result(response, index=0):
    payload = response.get_json()
    assert "results" in payload
    result = payload["results"][index]
    assert result["status"] == "stored"
    return result


def test_upload_preserves_original_bytes_and_sha256(client, app):
    original = _png_bytes()
    response = _upload(client, [(BytesIO(original), "agent-questions.png")])

    assert response.status_code == 200
    result = _stored_result(response)
    source = result["source"]
    assert source["sha256"] == hashlib.sha256(original).hexdigest()
    assert "original_path" not in source
    assert "display_preview_path" not in source

    downloaded = client.get(f"/api/v1/sources/{source['id']}/original")
    assert downloaded.status_code == 200
    assert downloaded.data == original
    with app.app_context():
        row = app.extensions["sqlalchemy_session_factory"]().get(SourceAsset, source["id"])
        assert row.sha256 == hashlib.sha256(original).hexdigest()


def test_upload_path_does_not_use_user_filename(client, app):
    response = _upload(client, [(BytesIO(_png_bytes()), "../../outside/secret.png")])

    assert response.status_code == 200
    source = _stored_result(response)["source"]
    with app.app_context():
        session = app.extensions["sqlalchemy_session_factory"]()
        row = session.get(SourceAsset, source["id"])
        assert ".." not in row.original_path
        assert "secret.png" not in row.original_path
        assert Path(app.config["SOURCE_STORAGE_DIR"]).resolve() in (
            Path(app.config["SOURCE_STORAGE_DIR"]).resolve() / row.original_path
        ).parents
        session.close()


def test_upload_rejects_extension_and_mime_spoof(client):
    response = _upload(
        client,
        [(BytesIO(_png_bytes()), "screenshot.jpg", "image/jpeg")],
    )

    assert response.status_code == 200
    rejected = response.get_json()["results"][0]
    assert rejected["status"] == "rejected"
    assert rejected["error"]["code"] == "VALIDATION_ERROR"


def test_upload_rejects_invalid_image_and_pixel_bomb(client, app):
    app.config["SOURCE_MAX_DECODED_PIXELS"] = 32
    response = _upload(
        client,
        [
            (BytesIO(b"not an image"), "bad.png"),
            (BytesIO(_png_bytes(size=(8, 8))), "too-large.png"),
        ],
    )

    assert response.status_code == 200
    assert [item["status"] for item in response.get_json()["results"]] == [
        "rejected",
        "rejected",
    ]


def test_upload_creates_exif_normalized_lossless_display_preview(client):
    image = Image.new("RGB", (8, 4), color=(180, 25, 55))
    exif = Image.Exif()
    exif[274] = 6
    stream = BytesIO()
    image.save(stream, format="JPEG", exif=exif)
    original = stream.getvalue()
    response = _upload(
        client,
        [(BytesIO(original), "rotated.jpg", "image/jpeg")],
    )

    source = _stored_result(response)["source"]
    display = client.get(f"/api/v1/sources/{source['id']}/display")
    assert display.status_code == 200
    assert display.mimetype == "image/png"
    with Image.open(BytesIO(display.data)) as preview:
        assert preview.size == (4, 8)
    assert client.get(f"/api/v1/sources/{source['id']}/original").data == original


def test_upload_rejects_oversized_file(client, app):
    app.config["SOURCE_MAX_FILE_BYTES"] = 4
    response = _upload(client, [(BytesIO(_png_bytes()), "oversized.png")])

    assert response.status_code == 200
    result = response.get_json()["results"][0]
    assert result["status"] == "rejected"
    assert result["error"]["code"] == "VALIDATION_ERROR"


def test_multi_upload_keeps_valid_files_when_sibling_is_invalid(client, app):
    response = _upload(
        client,
        [
            (BytesIO(_png_bytes(color=(1, 2, 3))), "first.png"),
            (BytesIO(b"bad image"), "broken.png"),
            (BytesIO(_png_bytes(color=(4, 5, 6))), "third.png"),
        ],
    )

    assert response.status_code == 200
    results = response.get_json()["results"]
    assert [item["status"] for item in results] == ["stored", "rejected", "stored"]
    with app.app_context():
        session = app.extensions["sqlalchemy_session_factory"]()
        assert session.query(SourceAsset).count() == 2
        assert session.query(IngestionJob).count() == 2
        session.close()
    assert client.get(
        f"/api/v1/sources/{results[0]['source']['id']}/original"
    ).status_code == 200
    assert client.get(
        f"/api/v1/sources/{results[2]['source']['id']}/original"
    ).status_code == 200


def test_database_failure_removes_only_that_files_original_and_preview(client, app):
    engine = app.extensions["sqlalchemy_engine"]
    failed = False

    def fail_once_on_job_insert(_session, _flush_context, _instances):
        nonlocal failed
        if not failed and any(isinstance(item, IngestionJob) for item in _session.new):
            failed = True
            raise RuntimeError("simulated database failure")

    event.listen(Session, "before_flush", fail_once_on_job_insert)
    try:
        response = _upload(
            client,
            [
                (BytesIO(_png_bytes(color=(20, 30, 40))), "first.png"),
                (BytesIO(_png_bytes(color=(50, 60, 70))), "second.png"),
            ],
        )
    finally:
        event.remove(Session, "before_flush", fail_once_on_job_insert)

    assert response.status_code == 200
    results = response.get_json()["results"]
    assert [item["status"] for item in results] == ["rejected", "stored"]
    source_root = Path(app.config["SOURCE_STORAGE_DIR"])
    with app.app_context():
        session = app.extensions["sqlalchemy_session_factory"]()
        rows = session.query(SourceAsset).all()
        assert len(rows) == 1
        assert rows[0].id == results[1]["source"]["id"]
        assert session.query(IngestionJob).count() == 1
        session.close()
    assert len(list(source_root.rglob("*.bin"))) == 1
    assert len(list(source_root.rglob("*.png"))) == 1


def test_batch_request_limit_returns_standard_413(client, app):
    app.config["MAX_CONTENT_LENGTH"] = 128
    response = _upload(client, [(BytesIO(_png_bytes((32, 32))), "large.png")])

    assert response.status_code == 413
    assert response.get_json()["error"]["code"] == "PAYLOAD_TOO_LARGE"


def test_original_and_display_routes_use_source_id_only(client):
    response = _upload(client, [(BytesIO(_png_bytes()), "visible.png")])
    source = _stored_result(response)["source"]
    assert client.get(f"/api/v1/sources/{source['id']}/original").status_code == 200
    assert client.get(f"/api/v1/sources/{source['id']}/display").status_code == 200
    assert client.get("/api/v1/sources/../../outside").status_code == 404


def test_source_patch_rejects_non_string_metadata_without_logging_values(client):
    source = _stored_result(_upload(client, [(BytesIO(_png_bytes()), "metadata.png")]))["source"]
    private_marker = "SOURCE-METADATA-PRIVATE-MARKER"

    response = client.patch(
        f"/api/v1/sources/{source['id']}",
        json={"title": {"private": private_marker}},
    )

    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "VALIDATION_ERROR"
    assert "title" in response.get_json()["error"]["fields"]


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({"platform": {"name": "x"}}, "platform"),
        ({"source_url": []}, "source_url"),
        ({"external_id": ["x"]}, "external_id"),
        ({"title": {"value": "x"}}, "title"),
        ({"author": ["x"]}, "author"),
        ({"captured_at": "not-an-iso-date"}, "captured_at"),
        ({"metadata_json": []}, "metadata_json"),
    ],
)
def test_source_patch_uses_upload_metadata_validation(client, payload, field):
    source = _stored_result(_upload(client, [(BytesIO(_png_bytes()), "patch-metadata.png")]))["source"]

    response = client.patch(f"/api/v1/sources/{source['id']}", json=payload)

    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "VALIDATION_ERROR"
    assert field in response.get_json()["error"]["fields"]


def test_source_database_errors_do_not_log_metadata_or_sql_parameters(client, monkeypatch):
    source = _stored_result(_upload(client, [(BytesIO(_png_bytes()), "metadata.png")]))["source"]
    private_marker = "SOURCE-METADATA-PRIVATE-MARKER"
    logged = []
    monkeypatch.setattr(
        api_errors.logger,
        "error",
        lambda *args, **kwargs: logged.append((args, kwargs)),
    )

    def fail_source_update(session, _flush_context, _instances):
        if any(isinstance(item, SourceAsset) for item in session.dirty):
            raise StatementError(
                "simulated update failure",
                "UPDATE source_asset SET title = ?",
                {"title": private_marker},
                ValueError("simulated"),
            )

    event.listen(Session, "before_flush", fail_source_update)
    try:
        response = client.patch(
            f"/api/v1/sources/{source['id']}",
            json={"title": private_marker},
        )
    finally:
        event.remove(Session, "before_flush", fail_source_update)

    assert response.status_code == 500
    assert response.get_json()["error"]["code"] == "INTERNAL_ERROR"
    assert any("StatementError" in str(args) for args, _kwargs in logged)
    assert private_marker not in repr(logged)


@pytest.mark.parametrize(
    ("metadata", "field"),
    [
        ({"platform": {"name": "x"}}, "platform"),
        ({"source_url": ["https://example.invalid"]}, "source_url"),
        ({"external_id": {"value": "x"}}, "external_id"),
        ({"title": {"value": "x"}}, "title"),
        ({"author": ["x"]}, "author"),
        ({"captured_at": "not-an-iso-date"}, "captured_at"),
        ({"metadata_json": []}, "metadata_json"),
    ],
)
def test_upload_rejects_invalid_metadata_types_with_field_errors(client, app, metadata, field):
    response = _upload(client, [(BytesIO(_png_bytes()), "invalid-metadata.png")], metadata)

    assert response.status_code == 200
    result = response.get_json()["results"][0]
    assert result["status"] == "rejected"
    assert result["error"]["code"] == "VALIDATION_ERROR"
    assert field in result["error"]["fields"]
    with app.app_context():
        session = app.extensions["sqlalchemy_session_factory"]()
        assert session.query(SourceAsset).count() == 0
        assert session.query(IngestionJob).count() == 0
        session.close()


def test_multi_upload_isolates_per_file_metadata_validation(client, app):
    files = [
        (BytesIO(_png_bytes(color=(1, 2, 3))), "valid-metadata.png"),
        (BytesIO(_png_bytes(color=(4, 5, 6))), "invalid-metadata.png"),
    ]
    metadata = [
        json.dumps({"title": "Valid source"}),
        json.dumps({"title": {"private": "must not reach SQL"}}),
    ]

    response = client.post(
        "/api/v1/sources",
        data={"files": files, "metadata": metadata},
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    results = response.get_json()["results"]
    assert [item["status"] for item in results] == ["stored", "rejected"]
    assert results[1]["error"]["code"] == "VALIDATION_ERROR"
    assert "title" in results[1]["error"]["fields"]
    assert client.get(f"/api/v1/sources/{results[0]['source']['id']}/original").status_code == 200
    with app.app_context():
        session = app.extensions["sqlalchemy_session_factory"]()
        assert session.query(SourceAsset).count() == 1
        assert session.query(IngestionJob).count() == 1
        session.close()
