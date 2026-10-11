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
