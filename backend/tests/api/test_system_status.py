from pathlib import Path


def test_system_status_reports_migration_and_optional_features_without_secrets(client, app, tmp_path, monkeypatch):
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    secret = "status-must-never-return-this-key"
    app.config.update(
        APP_DATA_DIR=tmp_path / "private-local-data",
        OCR_MODEL_DIR=tmp_path / "missing-ocr-models",
        OCR_MODEL_MANIFEST_PATH=tmp_path / "missing-ocr-models" / "manifest.json",
        LLM_BASE_URL="http://provider.invalid/v1",
        LLM_MODEL="local-model",
        LLM_API_KEY=secret,
    )

    response = client.get("/api/v1/system/status")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["application"] == "agent-interview-assistant"
    assert payload["backend"] == {"ready": True, "state": "ready"}
    assert payload["database"]["ready"] is True
    assert payload["database"]["migration_required"] is False
    assert payload["database"]["current_revision"] == payload["database"]["latest_revision"]
    assert payload["ocr"]["state"] == "missing"
    assert payload["llm"]["configured"] is True
    assert payload["storage"] == {"configured": True, "location": "custom"}
    assert secret not in response.get_data(as_text=True)
    assert str(tmp_path) not in response.get_data(as_text=True)


def test_system_status_reports_uninitialized_database_without_creating_it(app, tmp_path):
    from sqlalchemy import create_engine

    from app.services.system_status import get_system_status

    database_path = tmp_path / "not-created.sqlite3"
    engine = create_engine(f"sqlite:///{database_path}")
    app.extensions["sqlalchemy_engine"].dispose()
    app.extensions["sqlalchemy_engine"] = engine
    try:
        status = get_system_status(app)
    finally:
        engine.dispose()

    assert status["database"]["state"] == "not_initialized"
    assert status["database"]["migration_required"] is True
    assert not database_path.exists()
