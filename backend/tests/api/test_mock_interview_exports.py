from hashlib import sha256
from uuid import uuid4

from sqlalchemy import select

from app.models.mock_interview import MockInterviewSession, MockInterviewTurn
from app.models.assistant import AssistantOutput
from app.models.practice import PracticeReview, PracticeSession, SessionItem
from app.models.question import Question, QuestionRelation
from app.models.saved_answer import SavedAnswer, SavedAnswerVersion
from app.models.taxonomy import Topic


def _topic(db_session, slug):
    topic = Topic(track_key="agent_development", slug=slug, name=slug.replace("-", " "))
    db_session.add(topic)
    db_session.commit()
    return topic.id


def _question(client, text, topic_id=None):
    payload = {"text": text}
    if topic_id is not None:
        payload["topic_ids"] = [topic_id]
    response = client.post("/api/v1/questions", json=payload)
    assert response.status_code == 201
    return response.get_json()


def _saved_interview(client, question_id, answer="用户在模拟面试中的真实回答。", topic_id=None):
    started = client.post(
        "/api/v1/mock-interviews",
        json={
            "topic_id": topic_id,
            "question_count": 1,
            "context": {"project_ids": [], "material_ids": [], "exclude_material_ids": []},
        },
    )
    assert started.status_code == 201
    state = started.get_json()
    ended = client.post(
        f"/api/v1/mock-interviews/{state['id']}/finish",
        json={"answer": answer, "expected_revision": state["revision"]},
    )
    assert ended.status_code == 200
    saved = client.post(f"/api/v1/mock-interviews/{state['id']}/save", json={"title": "合成模拟面试"})
    assert saved.status_code == 201
    return saved.get_json()["record"]


def _answer_turn_id(db_session, record_id, kind="answer"):
    return db_session.scalar(
        select(MockInterviewTurn.id)
        .join(MockInterviewSession, MockInterviewSession.id == MockInterviewTurn.session_id)
        .where(MockInterviewSession.id == record_id, MockInterviewTurn.kind == kind)
    )


def _export(client, record_id, turn_id, **payload):
    return client.post(
        f"/api/v1/mock-interviews/saved/{record_id}/answers/{turn_id}/export",
        json=payload,
    )


def test_export_creates_user_written_answer_with_traceable_mock_source(client, db_session):
    question = _question(client, "LangGraph Checkpointer 如何工作？")
    record = _saved_interview(client, question["id"])
    turn_id = _answer_turn_id(db_session, record["id"])

    response = _export(
        client,
        record["id"],
        turn_id,
        save_mode="new_answer",
        content="整理后的用户回答，说明状态检查点和线程恢复。",
        self_rating=4,
    )

    assert response.status_code == 201, response.get_json()
    result = response.get_json()
    assert result["saved_answer"]["question_id"] == question["id"]
    assert result["version"]["origin_kind"] == "user_written"
    assert result["version"]["self_rating"] == 4
    assert result["version"]["source_session_item_id"] is None
    assert result["version"]["source_practice_review_id"] is None
    assert result["source"] == {
        "mock_interview_id": record["id"],
        "mock_interview_title": "合成模拟面试",
        "turn_id": turn_id,
        "question_id": question["id"],
        "question_text": question["text"],
    }
    source = client.get(f"/api/v1/saved-answer-versions/{result['version']['id']}/mock-interview-source")
    assert source.status_code == 200
    assert source.get_json() == result["source"]
    listed = client.get(f"/api/v1/questions/{question['id']}/saved-answers").get_json()
    assert listed[0]["current_version"]["mock_interview_source"] == result["source"]
    versions = client.get(f"/api/v1/saved-answers/{result['saved_answer']['id']}/versions").get_json()
    assert versions[0]["mock_interview_source"] == result["source"]
    assert db_session.query(PracticeReview).count() == 0
    assert db_session.query(PracticeSession).count() == 0
    assert db_session.query(SessionItem).count() == 0
    assert db_session.query(Question).count() == 1


def test_export_appends_immutable_user_written_version_without_inheriting_rating(client, db_session):
    question = _question(client, "MCP 工具发现与调用流程是什么？")
    record = _saved_interview(client, question["id"], "MCP 暴露工具清单和 schema。")
    turn_id = _answer_turn_id(db_session, record["id"])
    created = client.post(
        f"/api/v1/questions/{question['id']}/saved-answers",
        json={"content": "已有回答版本", "self_rating": 5},
    )
    assert created.status_code == 201
    answer_id = created.get_json()["id"]
    old_version_id = created.get_json()["current_version"]["id"]

    response = _export(
        client,
        record["id"],
        turn_id,
        save_mode="append_version",
        saved_answer_id=answer_id,
        content="从模拟面试复盘后补充的真实回答。",
        self_rating=None,
    )

    assert response.status_code == 201, response.get_json()
    result = response.get_json()
    assert result["saved_answer"]["id"] == answer_id
    assert result["version"]["version_no"] == 2
    assert result["version"]["origin_kind"] == "user_written"
    assert result["version"]["self_rating"] is None
    versions = client.get(f"/api/v1/saved-answers/{answer_id}/versions").get_json()
    assert [(row["id"], row["content"], row["self_rating"]) for row in versions] == [
        (result["version"]["id"], "从模拟面试复盘后补充的真实回答。", None),
        (old_version_id, "已有回答版本", 5),
    ]


def test_repeated_export_is_idempotent_and_does_not_create_duplicate_versions(client, db_session):
    question = _question(client, "Agent tool routing 如何评估？")
    record = _saved_interview(client, question["id"])
    turn_id = _answer_turn_id(db_session, record["id"])
    payload = {"save_mode": "new_answer", "content": "同一条面试回答。", "self_rating": None}

    first = client.post(f"/api/v1/mock-interviews/saved/{record['id']}/answers/{turn_id}/export", json=payload)
    second = client.post(f"/api/v1/mock-interviews/saved/{record['id']}/answers/{turn_id}/export", json=payload)

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.get_json()["already_exported"] is True
    assert second.get_json()["version"]["id"] == first.get_json()["version"]["id"]
    assert db_session.query(SavedAnswer).count() == 1
    assert db_session.query(SavedAnswerVersion).count() == 1


def test_invalid_export_rating_or_empty_content_writes_nothing(client, db_session):
    question = _question(client, "MCP server lifecycle")
    record = _saved_interview(client, question["id"])
    turn_id = _answer_turn_id(db_session, record["id"])

    invalid_rating = _export(
        client,
        record["id"],
        turn_id,
        save_mode="new_answer",
        content="Synthetic answer",
        self_rating=6,
    )
    empty_content = _export(
        client,
        record["id"],
        turn_id,
        save_mode="new_answer",
        content="   ",
        self_rating=None,
    )

    assert invalid_rating.status_code == 400
    assert empty_content.status_code == 400
    assert db_session.query(SavedAnswer).count() == 0
    assert db_session.query(SavedAnswerVersion).count() == 0


def test_export_rejects_question_turn_foreign_turn_and_unrelated_saved_answer(client, db_session):
    first_topic = _topic(db_session, "dag-orchestration")
    first_question = _question(client, "DAG 编排在什么情况下合适？", first_topic)
    record = _saved_interview(client, first_question["id"], topic_id=first_topic)
    question_turn_id = _answer_turn_id(db_session, record["id"], kind="question")
    invalid_kind = _export(client, record["id"], question_turn_id, save_mode="new_answer", content="回答文本")
    assert invalid_kind.status_code == 409

    other_topic = _topic(db_session, "sqlite-wal")
    other_question = _question(client, "SQLite WAL 有什么特点？", other_topic)
    other_record = _saved_interview(client, other_question["id"], topic_id=other_topic)
    other_turn_id = _answer_turn_id(db_session, other_record["id"])
    foreign_turn = _export(client, record["id"], other_turn_id, save_mode="new_answer", content="外部回答")
    assert foreign_turn.status_code == 404

    unrelated_answer = client.post(
        f"/api/v1/questions/{other_question['id']}/saved-answers",
        json={"content": "属于另一道题的回答"},
    ).get_json()
    mismatch = _export(
        client,
        record["id"],
        _answer_turn_id(db_session, record["id"]),
        save_mode="append_version",
        saved_answer_id=unrelated_answer["id"],
        content="不能追加到别题",
    )
    assert mismatch.status_code == 400


def test_export_failure_rolls_back_answer_and_source_link(client, db_session, monkeypatch):
    from app.services import saved_answers

    question = _question(client, "Agent state checkpoint recovery")
    record = _saved_interview(client, question["id"])
    turn_id = _answer_turn_id(db_session, record["id"])

    def fail_after_answer_creation(*args, **kwargs):
        raise RuntimeError("synthetic failure after version creation")

    monkeypatch.setattr(saved_answers, "_append", fail_after_answer_creation)
    response = _export(client, record["id"], turn_id, save_mode="new_answer", content="回滚测试内容")
    db_session.expire_all()

    assert response.status_code == 500
    assert db_session.query(SavedAnswer).count() == 0
    assert db_session.query(SavedAnswerVersion).count() == 0


def test_export_after_canonical_merge_keeps_original_question_and_turn_ids(client, app, db_session):
    from app.models.mock_interview import MockInterviewAnswerExport
    from app.models.practice import SessionItem

    original = _question(client, "LangGraph checkpoint 如何恢复执行？")
    original_id = original["id"]
    with app.extensions["sqlalchemy_session_factory"].begin() as session:
        answer = SavedAnswer(question_id=original_id)
        session.add(answer)
        session.flush()
        output = AssistantOutput(
            preview_key=str(uuid4()),
            question_id=original_id,
            output_type="reference_answer",
            origin_kind="ai_generated",
            selected_context_json={},
            content_text="历史 AI 草稿",
            provider="fake",
            model="test-model",
            prompt_version="test",
        )
        session.add(output)
        session.flush()
        version = SavedAnswerVersion(
            saved_answer_id=answer.id,
            version_no=1,
            content="历史 AI 草稿",
            origin_kind="ai_generated",
            assistant_output_id=output.id,
        )
        session.add(version)
        session.flush()
        answer_id = answer.id
        original_version_id = version.id

    record = _saved_interview(client, original_id, "这是我在面试中的真实回答。")
    turn_id = _answer_turn_id(db_session, record["id"])
    duplicate = _question(client, "LangGraph checkpoint 如何恢复执行？")
    canonical_id = duplicate["id"]
    with app.extensions["sqlalchemy_session_factory"].begin() as session:
        relation = session.scalar(
            select(QuestionRelation).where(
                QuestionRelation.question_id == original_id,
                QuestionRelation.related_question_id == canonical_id,
            )
        )
        assert relation is not None
        relation.relation_type = "same_question"
        relation.decision_status = "accepted"
        relation.suggested_by = "user"
        relation.question_text_sha256_snapshot = sha256(session.get(Question, original_id).text.encode()).hexdigest()
        relation.related_question_text_sha256_snapshot = sha256(session.get(Question, canonical_id).text.encode()).hexdigest()
        relation_id = relation.id

    preview = client.get(
        f"/api/v1/questions/{canonical_id}/merge-preview?source_question_id={original_id}"
    ).get_json()
    merged = client.post(
        f"/api/v1/questions/{canonical_id}/merge",
        json={
            "canonical_id": canonical_id,
            "source_question_id": original_id,
            "relation_id": relation_id,
            "preview_token": preview["preview_token"],
            "topic_ids": [],
            "tag_ids": [],
        },
    )
    assert merged.status_code == 200, merged.get_json()

    exported = _export(
        client,
        record["id"],
        turn_id,
        save_mode="append_version",
        saved_answer_id=answer_id,
        content="合并后整理的用户回答。",
        self_rating=None,
    )
    assert exported.status_code == 201, exported.get_json()
    result = exported.get_json()
    assert result["saved_answer"]["question_id"] == original_id
    assert result["version"]["version_no"] == 2
    assert result["version"]["origin_kind"] == "user_written"
    assert result["version"]["based_on_version_id"] is None
    assert result["version"]["assistant_output_id"] is None
    assert result["version"]["self_rating"] is None
    assert result["source"]["question_id"] == original_id
    assert result["source"]["question_text"] == original["text"]

    history = client.get(f"/api/v1/mock-interviews/saved/{record['id']}").get_json()
    saved_turn = next(turn for turn in history["turns"] if turn["id"] == turn_id)
    assert saved_turn["question_id"] == original_id
    assert saved_turn["question_text"] == original["text"]
    assert saved_turn["answer_export"]["saved_answer_id"] == answer_id
    versions = client.get(f"/api/v1/saved-answers/{answer_id}/versions").get_json()
    assert versions[1]["id"] == original_version_id
    assert versions[1]["content"] == "历史 AI 草稿"
    assert versions[1]["origin_kind"] == "ai_generated"
    assert versions[0]["origin_kind"] == "user_written"
    assert versions[0]["mock_interview_source"]["turn_id"] == turn_id
    assert db_session.query(PracticeReview).count() == 0
    assert db_session.query(SessionItem).count() == 0
    assert db_session.query(MockInterviewAnswerExport).count() == 1
    assert db_session.query(Question).count() == 2


def test_export_rejects_archived_original_question_or_archived_target_answer(client):
    question = _question(client, "Agent memory lifecycle")
    record = _saved_interview(client, question["id"])
    turn_id = _answer_turn_id_from_record(client, record["id"])
    saved = client.post(
        f"/api/v1/questions/{question['id']}/saved-answers",
        json={"content": "Will be archived"},
    ).get_json()
    archived_answer = client.post(f"/api/v1/saved-answers/{saved['id']}/archive")
    assert archived_answer.status_code == 200
    rejected_target = _export(
        client,
        record["id"],
        turn_id,
        save_mode="append_version",
        saved_answer_id=saved["id"],
        content="Cannot append to archived answer",
    )
    assert rejected_target.status_code == 409

    archived_question = client.post(f"/api/v1/questions/{question['id']}/archive")
    assert archived_question.status_code == 200
    rejected_question = _export(
        client,
        record["id"],
        turn_id,
        save_mode="new_answer",
        content="Cannot save against archived original",
    )
    assert rejected_question.status_code == 409


def test_manual_wrong_mark_does_not_create_review_and_enables_existing_wrong_practice(client, db_session):
    question = _question(client, "LangGraph thread state isolation")
    record = _saved_interview(client, question["id"])

    marked = client.patch(f"/api/v1/questions/{question['id']}/state", json={"is_wrong": True})
    assert marked.status_code == 200
    assert marked.get_json()["is_wrong"] is True
    assert db_session.query(PracticeReview).count() == 0

    practice = client.post("/api/v1/practice-sessions", json={"mode": "wrong", "limit": 10})
    assert practice.status_code == 201
    assert [item["question_id"] for item in practice.get_json()["items"]] == [question["id"]]
    assert db_session.query(PracticeReview).count() == 0
    assert client.get(f"/api/v1/mock-interviews/saved/{record['id']}").status_code == 200


def _answer_turn_id_from_record(client, record_id):
    record = client.get(f"/api/v1/mock-interviews/saved/{record_id}").get_json()
    return next(turn["id"] for turn in record["turns"] if turn["kind"] == "answer")
