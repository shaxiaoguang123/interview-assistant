import threading
import time

from app.models.practice import PracticeReview, PracticeSession
from app.models.material import Material, MaterialChunk, MaterialVersion, Project
from app.models.mock_interview import MockInterviewSession, MockInterviewTurn
from app.models.question import Question
from app.services.llm_provider import provider


def _create_question(client, text):
    response = client.post("/api/v1/questions", json={"text": text})
    assert response.status_code == 201
    return response.get_json()


def test_start_mock_interview_selects_real_questions_without_creating_practice_records(client, db_session):
    first = _create_question(client, "LangGraph checkpointer 面试题")
    second = _create_question(client, "MCP communication protocol 面试题")

    response = client.post(
        "/api/v1/mock-interviews",
        json={"topic_id": None, "question_count": 2, "context": {"project_ids": [], "material_ids": [], "exclude_material_ids": []}},
    )

    assert response.status_code == 201
    payload = response.get_json()
    assert payload["question_count"] == 2
    assert {question["id"] for question in payload["questions"]} == {first["id"], second["id"]}
    assert payload["current_question"]["id"] in {first["id"], second["id"]}
    db_session.expire_all()
    assert db_session.query(PracticeSession).count() == 0
    assert db_session.query(PracticeReview).count() == 0


class FakeProvider:
    provider = "fake"
    model = "test-model"

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def complete(self, messages):
        self.calls.append(messages)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


class BlockingProvider(FakeProvider):
    def __init__(self, reply):
        super().__init__([reply])
        self.entered = threading.Event()
        self.release = threading.Event()

    def complete(self, messages):
        self.calls.append(messages)
        self.entered.set()
        if not self.release.wait(timeout=10):
            raise TimeoutError("test provider was not released")
        return self.replies.pop(0)


def _create_mock_interview(client, question_count=1, context=None):
    return client.post(
        "/api/v1/mock-interviews",
        json={
            "topic_id": None,
            "question_count": question_count,
            "context": context or {"project_ids": [], "material_ids": [], "exclude_material_ids": []},
        },
    )


def test_follow_up_uses_selected_material_only_and_keeps_practice_state_untouched(app, client, db_session):
    question = _create_question(client, "LangGraph checkpointer 的作用是什么？")
    selected_project = Project(name="Selected Project")
    ignored_project = Project(name="Unselected Project")
    db_session.add_all([selected_project, ignored_project])
    db_session.flush()
    selected_material = Material(kind="readme", project_id=selected_project.id, title="Selected README")
    ignored_material = Material(kind="readme", project_id=ignored_project.id, title="Private Other README")
    disabled_material = Material(kind="architecture_doc", project_id=selected_project.id, title="Disabled Context", include_in_context=False)
    db_session.add_all([selected_material, ignored_material, disabled_material])
    db_session.flush()
    for material, text in (
        (selected_material, "SELECTED_EVIDENCE Checkpointer 保存线程状态并支持恢复。"),
        (ignored_material, "MUST_NOT_SEND secret resume details."),
        (disabled_material, "DISABLED_MUST_NOT_SEND unrelated disabled context."),
    ):
        version = MaterialVersion(
            material_id=material.id,
            version_no=1,
            path=f"materials/{material.id}/v1/source.txt",
            original_filename="source.txt",
            sha256=("a" if material.id == selected_material.id else "b") * 64,
            byte_size=100,
        )
        db_session.add(version)
        db_session.flush()
        db_session.add(MaterialChunk(material_version_id=version.id, project_id=material.project_id, ordinal=0, text=text))
    db_session.commit()

    fake = FakeProvider(["如果同一 thread_id 被多个请求复用，你会如何隔离状态？"])
    app.config["LLM_PROVIDER_FACTORY"] = lambda _config: fake
    created = _create_mock_interview(
        client,
        context={"project_ids": [selected_project.id], "material_ids": [], "exclude_material_ids": []},
    )
    assert created.status_code == 201
    session_id = created.get_json()["id"]

    response = client.post(
        f"/api/v1/mock-interviews/{session_id}/follow-up",
        json={"answer": "用于保存状态，便于中断后恢复。", "expected_revision": created.get_json()["revision"]},
    )

    assert response.status_code == 200
    assert response.get_json()["follow_up"] == "如果同一 thread_id 被多个请求复用，你会如何隔离状态？"
    prompt_text = "\n".join(message["content"] for message in fake.calls[0])
    assert "SELECTED_EVIDENCE" in prompt_text
    assert "MUST_NOT_SEND" not in prompt_text
    assert "DISABLED_MUST_NOT_SEND" not in prompt_text
    assert question["id"] == response.get_json()["session"]["current_question"]["id"]
    ended = client.post(
        f"/api/v1/mock-interviews/{session_id}/finish",
        json={"answer": "", "expected_revision": response.get_json()["session"]["revision"]},
    )
    assert ended.status_code == 200
    saved = client.post(f"/api/v1/mock-interviews/{session_id}/save", json={"title": "Context citation smoke"})
    assert saved.status_code == 201
    follow_up_turn = next(turn for turn in saved.get_json()["record"]["turns"] if turn["kind"] == "follow_up")
    assert follow_up_turn["sources"] == [
        {
            "material_id": selected_material.id,
            "material_version_id": follow_up_turn["sources"][0]["material_version_id"],
            "project_id": selected_project.id,
            "title": "Selected README",
            "version_no": 1,
            "sha256": "a" * 64,
            "chunk_ids": [follow_up_turn["sources"][0]["chunk_ids"][0]],
        }
    ]
    db_session.expire_all()
    assert db_session.query(PracticeSession).count() == 0
    assert db_session.query(PracticeReview).count() == 0
    assert db_session.query(Question).count() == 1


def test_failed_provider_keeps_answer_in_temporary_session_and_reports_unconfigured(client, app):
    _create_question(client, "MCP request lifecycle")
    created = _create_mock_interview(client)
    session_id = created.get_json()["id"]
    app.config["LLM_PROVIDER_FACTORY"] = None

    failed = client.post(
        f"/api/v1/mock-interviews/{session_id}/follow-up",
        json={"answer": "The transport negotiates tool calls.", "expected_revision": created.get_json()["revision"]},
    )

    assert failed.status_code == 503
    assert failed.get_json()["error"]["code"] == "LLM_NOT_CONFIGURED"
    resumed = client.get(f"/api/v1/mock-interviews/{session_id}")
    assert resumed.status_code == 200
    assert [turn["text"] for turn in resumed.get_json()["turns"] if turn["kind"] == "answer"] == [
        "The transport negotiates tool calls."
    ]
    assert client.get("/api/v1/mock-interviews/saved").get_json() == []


def test_summary_and_transcript_are_persisted_only_after_explicit_save(client, db_session, app):
    question = _create_question(client, "Function calling 与 MCP 有什么区别？")
    summary_json = (
        '{"overview":"回答覆盖了工具调用的基础。","items":[{"question_ordinal":1,'
        '"answer_summary":"说明了模型发起工具调用。","missing_points":["协议协商"],'
        '"technical_concerns":[],"next_directions":["比较 MCP 与 Provider 原生工具协议"]}],'
        '"recommendations":[{"question_ordinal":1,"reason":"继续比较协议边界。"}]}'
    )
    fake = FakeProvider([summary_json])
    app.config["LLM_PROVIDER_FACTORY"] = lambda _config: fake
    created = _create_mock_interview(client)
    session_id = created.get_json()["id"]
    ended = client.post(
        f"/api/v1/mock-interviews/{session_id}/finish",
        json={"answer": "Function calling is model tool invocation; MCP standardizes tool discovery and communication.", "expected_revision": created.get_json()["revision"]},
    )
    assert ended.status_code == 200

    summary = client.post(f"/api/v1/mock-interviews/{session_id}/summary", json={})

    assert summary.status_code == 200
    value = summary.get_json()["summary"]
    assert value["items"][0]["question_id"] == question["id"]
    assert value["recommendations"][0]["question_id"] == question["id"]
    db_session.expire_all()
    assert db_session.query(MockInterviewSession).count() == 0

    saved = client.post(f"/api/v1/mock-interviews/{session_id}/save", json={"title": "Agent 技术模拟面试"})

    assert saved.status_code == 201
    record_id = saved.get_json()["record"]["id"]
    detail = client.get(f"/api/v1/mock-interviews/saved/{record_id}")
    assert detail.status_code == 200
    record = detail.get_json()
    assert record["title"] == "Agent 技术模拟面试"
    assert record["summary"]["overview"] == "回答覆盖了工具调用的基础。"
    assert [(turn["kind"], turn["question_id"]) for turn in record["turns"]] == [
        ("question", question["id"]),
        ("answer", question["id"]),
    ]
    db_session.expire_all()
    assert db_session.query(MockInterviewSession).count() == 1
    assert db_session.query(MockInterviewTurn).count() == 2


def test_stale_revision_does_not_duplicate_or_overwrite_answer(client, app):
    _create_question(client, "RAG reranking question")
    fake = FakeProvider(["Which reranking signal would you compare first?"])
    app.config["LLM_PROVIDER_FACTORY"] = lambda _config: fake
    created = _create_mock_interview(client)
    session_id = created.get_json()["id"]
    response = client.post(
        f"/api/v1/mock-interviews/{session_id}/follow-up",
        json={"answer": "Use reciprocal rank fusion.", "expected_revision": created.get_json()["revision"]},
    )
    assert response.status_code == 200

    stale = client.post(
        f"/api/v1/mock-interviews/{session_id}/follow-up",
        json={"answer": "Overwrite with stale content", "expected_revision": created.get_json()["revision"]},
    )

    assert stale.status_code == 409
    assert stale.get_json()["error"]["code"] == "CONFLICT"
    current = client.get(f"/api/v1/mock-interviews/{session_id}").get_json()
    assert [turn["text"] for turn in current["turns"] if turn["kind"] == "answer"] == ["Use reciprocal rank fusion."]


def test_busy_follow_up_does_not_append_second_answer(client, app):
    _create_question(client, "LangGraph checkpointer 的作用是什么？")
    fake = BlockingProvider("thread_id 如何隔离不同用户的状态？")
    app.config["LLM_PROVIDER_FACTORY"] = lambda _config: fake
    created = _create_mock_interview(client)
    session_id = created.get_json()["id"]
    result = {}

    def make_first_request():
        with app.test_client() as thread_client:
            response = thread_client.post(
                f"/api/v1/mock-interviews/{session_id}/follow-up",
                json={"answer": "先持久化状态，再从检查点恢复。", "expected_revision": 0},
            )
            result["first_status"] = response.status_code

    worker = threading.Thread(target=make_first_request)
    worker.start()
    assert fake.entered.wait(timeout=5)
    busy_state = client.get(f"/api/v1/mock-interviews/{session_id}").get_json()
    second = client.post(
        f"/api/v1/mock-interviews/{session_id}/follow-up",
        json={"answer": "This answer must not be appended.", "expected_revision": busy_state["revision"]},
    )
    fake.release.set()
    worker.join(timeout=10)

    assert result["first_status"] == 200
    assert second.status_code == 409
    assert second.get_json()["error"]["code"] == "MOCK_INTERVIEW_BUSY"
    current = client.get(f"/api/v1/mock-interviews/{session_id}").get_json()
    assert [turn["text"] for turn in current["turns"] if turn["kind"] == "answer"] == [
        "先持久化状态，再从检查点恢复。"
    ]
    assert current["revision"] == 2


def test_save_is_rejected_while_summary_is_generating(client, app):
    _create_question(client, "MCP 工具发现如何工作？")
    summary_json = (
        '{"overview":"回答覆盖了基础。","items":[{"question_ordinal":1,'
        '"answer_summary":"说明了工具发现。","missing_points":[],"technical_concerns":[],'
        '"next_directions":["比较不同传输方式"]}],"recommendations":[]}'
    )
    fake = BlockingProvider(summary_json)
    app.config["LLM_PROVIDER_FACTORY"] = lambda _config: fake
    created = _create_mock_interview(client)
    session_id = created.get_json()["id"]
    ended = client.post(
        f"/api/v1/mock-interviews/{session_id}/finish",
        json={"answer": "MCP 提供统一的工具发现接口。", "expected_revision": 0},
    )
    assert ended.status_code == 200
    result = {}

    def generate():
        with app.test_client() as thread_client:
            response = thread_client.post(f"/api/v1/mock-interviews/{session_id}/summary", json={})
            result["summary_status"] = response.status_code

    worker = threading.Thread(target=generate)
    worker.start()
    assert fake.entered.wait(timeout=5)
    saving = client.post(f"/api/v1/mock-interviews/{session_id}/save", json={"title": "Concurrency check"})
    fake.release.set()
    worker.join(timeout=10)

    assert saving.status_code == 409
    assert saving.get_json()["error"]["code"] == "MOCK_INTERVIEW_BUSY"
    assert result["summary_status"] == 200
    saved = client.post(f"/api/v1/mock-interviews/{session_id}/save", json={"title": "Concurrency check"})
    assert saved.status_code == 201
    assert saved.get_json()["record"]["summary"]["overview"] == "回答覆盖了基础。"


def test_cache_evicts_saved_sessions_but_keeps_saved_history(client, app):
    from app.services.mock_interviews import TEMP_SESSION_LIMIT

    _create_question(client, "Agent 系统设计题")
    ids = []
    saved_record_id = None
    for index in range(TEMP_SESSION_LIMIT):
        created = _create_mock_interview(client)
        assert created.status_code == 201
        session_id = created.get_json()["id"]
        ids.append(session_id)
        if index == 0:
            ended = client.post(
                f"/api/v1/mock-interviews/{session_id}/finish",
                json={"answer": "一个合成答案。", "expected_revision": 0},
            )
            assert ended.status_code == 200
            saved = client.post(f"/api/v1/mock-interviews/{session_id}/save", json={})
            assert saved.status_code == 201
            saved_record_id = saved.get_json()["record"]["id"]

    extra = _create_mock_interview(client)

    assert extra.status_code == 201
    assert client.get(f"/api/v1/mock-interviews/{ids[0]}").status_code == 404
    assert client.get(f"/api/v1/mock-interviews/saved/{saved_record_id}").status_code == 200
    assert all(client.get(f"/api/v1/mock-interviews/{session_id}").status_code == 200 for session_id in ids[1:])


def test_cache_refuses_to_evict_unexpired_unsaved_sessions(client):
    from app.services.mock_interviews import TEMP_SESSION_LIMIT

    _create_question(client, "Agent 可靠性题")
    ids = [_create_mock_interview(client).get_json()["id"] for _ in range(TEMP_SESSION_LIMIT)]

    rejected = _create_mock_interview(client)

    assert rejected.status_code == 503
    assert rejected.get_json()["error"]["code"] == "MOCK_INTERVIEW_CAPACITY"
    assert all(client.get(f"/api/v1/mock-interviews/{session_id}").status_code == 200 for session_id in ids)


def test_expired_in_flight_session_is_not_purged(client, app):
    from app.services.mock_interviews import TEMP_SESSION_TTL_SECONDS

    _create_question(client, "Agent state recovery")
    created = _create_mock_interview(client)
    session_id = created.get_json()["id"]
    cache = app.extensions["mock_interview_sessions"]
    with app.extensions["mock_interview_lock"]:
        cache[session_id]["generating"] = True
        cache[session_id]["generation_token"] = "in-flight-test"
        cache[session_id]["last_active_monotonic"] = time.monotonic() - TEMP_SESSION_TTL_SECONDS - 1

    response = client.get(f"/api/v1/mock-interviews/{session_id}")

    assert response.status_code == 200
    assert response.get_json()["id"] == session_id
