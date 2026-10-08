import ast
from importlib import import_module
from io import BytesIO
from pathlib import Path
import threading
from queue import Queue

from PIL import Image
from werkzeug.datastructures import FileStorage

from app import create_app
from app.models.ingestion import IngestionJob
from app.services.source_storage import save_source_file


BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _ingestion_api():
    module_path = BACKEND_ROOT / "app" / "api" / "v1" / "ingestions.py"
    assert module_path.is_file(), "missing feature: ingestion API"
    return import_module("app.api.v1.ingestions")


def _fake_adapter(detections=None, entered=None, release=None):
    class FakeAdapter:
        name = "fake-ocr"
        version = "fake-1;provider=CPUExecutionProvider"

        def recognize(self, image):
            if entered is not None:
                entered.set()
            if release is not None:
                release.wait(timeout=5)
            assert image.size == (12, 8)
            return detections or []

    return FakeAdapter()


def _png_bytes():
    image = Image.new("RGB", (12, 8), color=(20, 80, 140))
    stream = BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


def _upload_source(client):
    response = client.post(
        "/api/v1/sources",
        data={"files": (BytesIO(_png_bytes()), "agent-questions.png")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    result = response.get_json()["results"][0]
    assert result["status"] == "stored"
    return result["source"], result["job"]


def test_run_claim_is_atomic_under_two_requests(app):
    _ingestion_api()
    entered = threading.Event()
    release = threading.Event()
    app.config["OCR_ADAPTER_FACTORY"] = lambda: _fake_adapter(
        entered=entered, release=release
    )
    first_client = app.test_client()
    second_client = app.test_client()
    _, job = _upload_source(first_client)
    first_result: Queue = Queue()

    def run_first():
        first_result.put(
            first_client.post(f"/api/v1/ingestions/{job['id']}/run")
        )

    worker = threading.Thread(target=run_first)
    worker.start()
    try:
        assert entered.wait(timeout=3), "first request did not begin OCR"
        second = second_client.post(f"/api/v1/ingestions/{job['id']}/run")
        assert second.status_code == 409
        assert second.get_json()["error"]["code"] == "CONFLICT"
    finally:
        release.set()
        worker.join(timeout=5)

    assert not worker.is_alive()
    first = first_result.get_nowait()
    assert first.status_code == 200
    assert first.get_json()["job"]["status"] == "succeeded"


def test_non_queued_run_returns_conflict(client):
    _ingestion_api()
    _, job = _upload_source(client)
    client.post(f"/api/v1/ingestions/{job['id']}/run")

    repeated = client.post(f"/api/v1/ingestions/{job['id']}/run")

    assert repeated.status_code == 409
    assert repeated.get_json()["error"]["code"] == "CONFLICT"


def test_create_app_does_not_initialize_ocr_models(tmp_path):
    called = []
    database_path = tmp_path / "lazy.sqlite3"
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": f"sqlite:///{database_path}",
            "SOURCE_STORAGE_DIR": tmp_path / "sources",
            "SEED_TOPICS_ON_STARTUP": False,
            "OCR_ADAPTER_FACTORY": lambda: called.append(True),
        }
    )

    assert app.test_client().get("/api/v1/health").status_code == 200
    assert called == []
    app.extensions["sqlalchemy_engine"].dispose()


def test_app_factory_does_not_run_startup_recovery(app, tmp_path):
    _ingestion_api()
    factory = app.extensions["sqlalchemy_session_factory"]
    with app.app_context():
        with factory.begin() as session:
            source = save_source_file(
                FileStorage(
                stream=BytesIO(_png_bytes()),
                filename="running.png",
                content_type="image/png",
                ),
                app.config["SOURCE_STORAGE_DIR"],
                {},
            )
            session.add(source)
            session.flush()
            job = IngestionJob(
                source_asset_id=source.id,
                status="running",
                stage="recognizing",
            )
            session.add(job)
            session.flush()
            job_id = job.id
    config = {
        "TESTING": True,
        "DATABASE_URL": app.config["DATABASE_URL"],
        "SOURCE_STORAGE_DIR": app.config["SOURCE_STORAGE_DIR"],
        "SEED_TOPICS_ON_STARTUP": False,
    }

    reopened = create_app(config)
    with reopened.extensions["sqlalchemy_session_factory"]() as session:
        job = session.get(IngestionJob, job_id)
        assert job.status == "running"
    reopened.extensions["sqlalchemy_engine"].dispose()


def test_supported_runner_recovers_once_with_reloader_disabled(monkeypatch):
    run_path = BACKEND_ROOT / "run.py"
    assert run_path.is_file(), "missing feature: supported single-process runner"
    tree = ast.parse(run_path.read_text(encoding="utf-8"))
    assert any(
        isinstance(node, ast.FunctionDef) and node.name == "main" for node in tree.body
    ), "missing feature: explicit runner main function"
    run = import_module("run")

    calls = []

    class FakeApp:
        config = {"DEBUG": True}
        extensions = {"sqlalchemy_session_factory": object()}

        def run(self, **kwargs):
            calls.append(("run", kwargs))

    app = FakeApp()
    monkeypatch.setattr(run, "create_app", lambda: app)
    monkeypatch.setattr(
        run,
        "recover_interrupted_jobs",
        lambda _factory: calls.append(("recover", None)),
    )

    run.main()

    assert calls[0] == ("recover", None)
    assert calls[1][0] == "run"
    assert calls[1][1]["use_reloader"] is False
    assert calls[1][1]["debug"] is True
