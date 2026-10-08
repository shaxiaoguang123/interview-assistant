import ast
from importlib import import_module
from io import BytesIO
from pathlib import Path
import threading
from queue import Queue
from datetime import datetime, timezone
from uuid import uuid4

from PIL import Image
from werkzeug.datastructures import FileStorage

from app import create_app
from app.models.ingestion import (
    IngestionJob,
    OCRBlock,
    QuestionSource,
    QuestionSourceOCRBlock,
)
from app.models.question import Question
from app.ocr.adapter import OCRAdapterInitializationError, OCRDetection
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


def test_two_different_jobs_share_one_adapter_without_concurrent_inference(
    client, app, monkeypatch
):
    service = import_module("app.services.ingestion")
    _, first_job = _upload_source(client)
    _, second_job = _upload_source(client)
    first_entered = threading.Event()
    second_entered = threading.Event()
    release_first = threading.Event()
    second_claimed = threading.Event()
    guard = threading.Lock()
    calls = {"factory": 0, "recognize": 0, "active": 0, "max_active": 0}
    detection = OCRDetection(
        id=str(uuid4()),
        text="Question from the second job",
        bbox=(0.1, 0.2, 0.5, 0.2),
        confidence=0.9,
        reading_order=0,
    )

    class SharedAdapter:
        name = "shared-test-ocr"
        version = "shared-test;provider=CPUExecutionProvider"

        def recognize(self, image):
            with guard:
                calls["recognize"] += 1
                call_number = calls["recognize"]
                calls["active"] += 1
                calls["max_active"] = max(calls["max_active"], calls["active"])
            try:
                assert image.size == (12, 8)
                if call_number == 1:
                    first_entered.set()
                    release_first.wait(timeout=3)
                    raise RuntimeError("first job OCR failure")
                second_entered.set()
                return [detection]
            finally:
                with guard:
                    calls["active"] -= 1

    adapter = SharedAdapter()

    def factory():
        with guard:
            calls["factory"] += 1
        return adapter

    app.config["OCR_ADAPTER_FACTORY"] = factory
    original_claim = service.claim_queued_job

    def signal_second_claim(app_object, job_id):
        original_claim(app_object, job_id)
        if job_id == second_job["id"]:
            second_claimed.set()

    monkeypatch.setattr(service, "claim_queued_job", signal_second_claim)
    results = Queue()

    def run(job_id):
        results.put((job_id, service.run_ingestion(app, job_id)))

    first = threading.Thread(target=run, args=(first_job["id"],))
    second = threading.Thread(target=run, args=(second_job["id"],))
    first.start()
    assert first_entered.wait(timeout=3), "first job did not enter OCR"
    second.start()
    try:
        assert second_claimed.wait(timeout=3), "second job was not claimed"
        assert not second_entered.wait(timeout=0.1)
    finally:
        release_first.set()
        first.join(timeout=5)
        second.join(timeout=5)

    assert not first.is_alive()
    assert not second.is_alive()
    outcomes = {job_id: result["status"] for job_id, result in [results.get(), results.get()]}
    assert outcomes == {first_job["id"]: "failed", second_job["id"]: "succeeded"}
    assert calls["factory"] == 1
    assert calls["recognize"] == 2
    assert calls["max_active"] == 1


def test_adapter_initialization_failure_for_one_job_does_not_poison_another(app):
    service = import_module("app.services.ingestion")
    _, first_job = _upload_source(app.test_client())
    _, second_job = _upload_source(app.test_client())
    calls = []

    def factory():
        calls.append(len(calls) + 1)
        if len(calls) == 1:
            raise OCRAdapterInitializationError(
                "OCR_MODEL_INVALID",
                "Local OCR model validation failed",
            )
        return _fake_adapter(
            detections=[
                OCRDetection(
                    id=str(uuid4()),
                    text="Second job question",
                    bbox=(0.1, 0.2, 0.5, 0.2),
                    confidence=0.9,
                    reading_order=0,
                )
            ]
        )

    app.config["OCR_ADAPTER_FACTORY"] = factory
    first_result = service.run_ingestion(app, first_job["id"])
    second_result = service.run_ingestion(app, second_job["id"])

    assert first_result["status"] == "failed"
    assert first_result["error_code"] == "OCR_MODEL_INVALID"
    assert second_result["status"] == "succeeded"
    assert second_result["candidate_count"] == 1
    assert calls == [1, 2]


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
        config = {"DEBUG": True, "SOURCE_STORAGE_DIR": "/tmp/ocr-sources"}
        extensions = {"sqlalchemy_session_factory": object()}

        def run(self, **kwargs):
            calls.append(("run", kwargs))

    app = FakeApp()
    monkeypatch.setattr(run, "create_app", lambda: app)
    monkeypatch.setattr(
        run,
        "recover_interrupted_jobs",
        lambda _factory: calls.append(("recover_jobs", None)),
    )
    monkeypatch.setattr(
        run,
        "recover_source_tombstones",
        lambda _factory, _root: calls.append(("recover_tombstones", None)),
    )

    run.main()

    assert calls[0] == ("recover_jobs", None)
    assert calls[1] == ("recover_tombstones", None)
    assert calls[2][0] == "run"
    assert calls[2][1]["use_reloader"] is False
    assert calls[2][1]["debug"] is True


def test_runner_allows_local_port_override(monkeypatch):
    run_path = BACKEND_ROOT / "run.py"
    tree = ast.parse(run_path.read_text(encoding="utf-8"))
    assert any(isinstance(node, ast.FunctionDef) and node.name == "main" for node in tree.body)
    run = import_module("run")
    calls = []

    class FakeApp:
        config = {"DEBUG": False, "SOURCE_STORAGE_DIR": "/tmp/ocr-sources"}
        extensions = {"sqlalchemy_session_factory": object()}

        def run(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setenv("APP_PORT", "5017")
    monkeypatch.setattr(run, "create_app", FakeApp)
    monkeypatch.setattr(run, "recover_interrupted_jobs", lambda _factory: None)
    monkeypatch.setattr(run, "recover_source_tombstones", lambda _factory, _root: None)

    run.main()

    assert calls[0]["port"] == 5017
    assert calls[0]["use_reloader"] is False


def test_candidate_query_includes_pending_confirmed_rejected_and_superseded(client, app):
    source, job = _upload_source(client)
    now = datetime.now(timezone.utc)
    rows = [
        Question(
            text="pending candidate",
            normalized_text="pending candidate",
            search_text="pending candidate",
            normalized_hash="pending-hash",
            status="pending_review",
            origin_ingestion_job_id=job["id"],
            ingestion_candidate_state="pending_review",
        ),
        Question(
            text="confirmed candidate",
            normalized_text="confirmed candidate",
            search_text="confirmed candidate",
            normalized_hash="confirmed-hash",
            status="active",
            origin_ingestion_job_id=job["id"],
            ingestion_candidate_state="confirmed",
        ),
        Question(
            text="rejected candidate",
            normalized_text="rejected candidate",
            search_text="rejected candidate",
            normalized_hash="rejected-hash",
            status="pending_review",
            origin_ingestion_job_id=job["id"],
            ingestion_candidate_state="rejected",
            archived_at=now,
        ),
        Question(
            text="superseded candidate",
            normalized_text="superseded candidate",
            search_text="superseded candidate",
            normalized_hash="superseded-hash",
            status="pending_review",
            origin_ingestion_job_id=job["id"],
            ingestion_candidate_state="superseded",
            archived_at=now,
        ),
    ]
    with app.extensions["sqlalchemy_session_factory"].begin() as session:
        session.add_all(rows)

    response = client.get(f"/api/v1/ingestions/{job['id']}/candidates")

    assert response.status_code == 200
    assert {item["candidate_state"] for item in response.get_json()} == {
        "pending_review",
        "confirmed",
        "rejected",
        "superseded",
    }
    assert {item["source_asset_id"] for item in response.get_json()} == {source["id"]}


def test_candidate_query_returns_split_parent_children_and_superseded_target(client, app):
    _, job = _upload_source(client)
    with app.extensions["sqlalchemy_session_factory"].begin() as session:
        parent = Question(
            text="split parent",
            normalized_text="split parent",
            search_text="split parent",
            normalized_hash="lineage-parent",
            status="pending_review",
            origin_ingestion_job_id=job["id"],
            ingestion_candidate_state="superseded",
            archived_at=datetime.now(timezone.utc),
        )
        survivor = Question(
            text="merge survivor",
            normalized_text="merge survivor",
            search_text="merge survivor",
            normalized_hash="lineage-survivor",
            status="pending_review",
            origin_ingestion_job_id=job["id"],
            ingestion_candidate_state="pending_review",
        )
        session.add_all([parent, survivor])
        session.flush()
        child = Question(
            text="split child",
            normalized_text="split child",
            search_text="split child",
            normalized_hash="lineage-child",
            status="pending_review",
            origin_ingestion_job_id=job["id"],
            ingestion_candidate_state="pending_review",
            split_from_candidate_id=parent.id,
        )
        loser = Question(
            text="merge loser",
            normalized_text="merge loser",
            search_text="merge loser",
            normalized_hash="lineage-loser",
            status="pending_review",
            origin_ingestion_job_id=job["id"],
            ingestion_candidate_state="superseded",
            archived_at=datetime.now(timezone.utc),
            superseded_by_candidate_id=survivor.id,
        )
        session.add_all([child, loser])
        session.flush()
        child_ids = [child.id]
        parent_id = parent.id
        survivor_id = survivor.id
        loser_id = loser.id

    candidates = client.get(
        f"/api/v1/ingestions/{job['id']}/candidates"
    ).get_json()
    by_id = {candidate["id"]: candidate for candidate in candidates}
    assert by_id[parent_id]["split_child_ids"] == child_ids
    assert by_id[child_ids[0]]["split_from_candidate_id"] == parent_id
    assert by_id[loser_id]["superseded_by_candidate_id"] == survivor_id


def test_candidate_status_filter_and_wrong_job_scope(client, app):
    _, job = _upload_source(client)
    _, other_job = _upload_source(client)
    with app.extensions["sqlalchemy_session_factory"].begin() as session:
        session.add(
            Question(
                text="only first job candidate",
                normalized_text="only first job candidate",
                search_text="only first job candidate",
                normalized_hash="only-first-job",
                status="pending_review",
                origin_ingestion_job_id=job["id"],
                ingestion_candidate_state="pending_review",
            )
        )

    pending = client.get(
        f"/api/v1/ingestions/{job['id']}/candidates?status=pending_review"
    )
    other = client.get(f"/api/v1/ingestions/{other_job['id']}/candidates")
    invalid = client.get(f"/api/v1/ingestions/{job['id']}/candidates?status=unknown")

    assert pending.status_code == 200
    assert len(pending.get_json()) == 1
    assert other.status_code == 200
    assert other.get_json() == []
    assert invalid.status_code == 400
    assert invalid.get_json()["error"]["code"] == "VALIDATION_ERROR"


def test_candidate_query_contains_raw_source_and_stable_ocr_block(client, app):
    source, job = _upload_source(client)
    with app.extensions["sqlalchemy_session_factory"].begin() as session:
        block = OCRBlock(
            ingestion_job_id=job["id"],
            text="Which tool protocol?",
            bbox_json={"x": 0.1, "y": 0.2, "width": 0.7, "height": 0.1},
            reading_order=0,
            confidence=0.99,
        )
        candidate = Question(
            text="Which tool protocol?",
            normalized_text="which tool protocol?",
            search_text="which tool protocol?",
            normalized_hash="source-evidence-question",
            status="pending_review",
            origin_ingestion_job_id=job["id"],
            ingestion_candidate_state="pending_review",
        )
        session.add_all([block, candidate])
        session.flush()
        source_row = QuestionSource(
            question_id=candidate.id,
            source_asset_id=source["id"],
            locator_type="image_region",
            locator_json={"x": 0.1, "y": 0.2, "width": 0.7, "height": 0.1},
            source_text_snapshot="Which tool protocol?",
            raw_ocr_text_snapshot="Which tool protocol?",
        )
        session.add(source_row)
        session.flush()
        session.add(
            QuestionSourceOCRBlock(
                question_source_id=source_row.id,
                ocr_block_id=block.id,
            )
        )
        block_id = block.id

    response = client.get(f"/api/v1/ingestions/{job['id']}/candidates")
    candidate_json = response.get_json()[0]
    source_json = candidate_json["sources"][0]

    assert response.status_code == 200
    assert source_json["source_text_snapshot"] == "Which tool protocol?"
    assert source_json["raw_ocr_text_snapshot"] == "Which tool protocol?"
    assert source_json["ocr_blocks"][0]["id"] == block_id


def test_unconfirmed_candidate_is_absent_from_default_list_search_and_practice(app):
    import uuid

    client = app.test_client()
    detection = OCRDetection(
        id=str(uuid.uuid4()),
        text="What is MCP?",
        bbox=(0.1, 0.1, 0.6, 0.15),
        confidence=0.98,
        reading_order=0,
    )
    app.config["OCR_ADAPTER_FACTORY"] = lambda: _fake_adapter([detection])
    _, job = _upload_source(client)
    run = client.post(f"/api/v1/ingestions/{job['id']}/run")
    assert run.status_code == 200
    assert run.get_json()["job"]["status"] == "succeeded"

    listing = client.get("/api/v1/questions")
    search = client.get("/api/v1/questions?q=MCP")
    practice = client.post(
        "/api/v1/practice-sessions",
        json={"mode": "random", "filters": {}, "limit": 5},
    )

    assert listing.status_code == 200
    assert listing.get_json() == []
    assert search.status_code == 200
    assert search.get_json() == []
    assert practice.status_code == 201
    assert practice.get_json()["items"] == []
