from datetime import datetime, timezone

from app.models.practice import PracticeReview, PracticeSession, SessionItem
from app.models.question import Question, QuestionState


def _create_topic(client, slug="agent-topic", name="Agent Topic"):
    response = client.post("/api/v1/topics", json={"slug": slug, "name": name})
    assert response.status_code == 201
    return response.get_json()


def _create_tag(client, name="RAG"):
    response = client.post("/api/v1/tags", json={"name": name})
    assert response.status_code == 201
    return response.get_json()


def _error_fields(response):
    assert response.status_code == 400
    payload = response.get_json()
    assert payload["error"]["code"] == "VALIDATION_ERROR"
    return payload["error"]["fields"]


def test_question_crud_with_topics_and_tags(client):
    topic = _create_topic(client)
    tag = _create_tag(client)
    original_text = "  LangGraph 如何实现持久化？  "

    created = client.post(
        "/api/v1/questions",
        json={
            "text": original_text,
            "answer_type": "conceptual",
            "difficulty": "medium",
            "topic_ids": [topic["id"]],
            "tag_ids": [tag["id"]],
        },
    )

    assert created.status_code == 201
    question = created.get_json()
    assert question["text"] == "LangGraph 如何实现持久化？"
    assert question["normalized_text"] == "langgraph 如何实现持久化?"
    assert question["search_text"] == question["normalized_text"]
    assert question["status"] == "active"
    assert question["archived_at"] is None
    assert question["answer_type"] == "conceptual"
    assert question["difficulty"] == "medium"
    assert [item["id"] for item in question["topics"]] == [topic["id"]]
    assert [item["id"] for item in question["tags"]] == [tag["id"]]

    detail = client.get(f"/api/v1/questions/{question['id']}")
    assert detail.status_code == 200
    assert detail.get_json()["text"] == question["text"]

    updated = client.patch(
        f"/api/v1/questions/{question['id']}",
        json={"text": "MCP 通信协议是什么？"},
    )
    assert updated.status_code == 200
    assert updated.get_json()["text"] == "MCP 通信协议是什么？"
    assert [item["id"] for item in updated.get_json()["topics"]] == [topic["id"]]
    assert [item["id"] for item in updated.get_json()["tags"]] == [tag["id"]]


def test_question_taxonomy_patch_response_matches_saved_relations(client):
    first_topic = _create_topic(client, slug="first-topic", name="First Topic")
    second_topic = _create_topic(client, slug="second-topic", name="Second Topic")
    first_tag = _create_tag(client, name="First Tag")
    second_tag = _create_tag(client, name="Second Tag")
    created = client.post(
        "/api/v1/questions",
        json={
            "text": "Replace taxonomy relationships",
            "topic_ids": [first_topic["id"]],
            "tag_ids": [first_tag["id"]],
        },
    )
    question_id = created.get_json()["id"]

    updated = client.patch(
        f"/api/v1/questions/{question_id}",
        json={"topic_ids": [second_topic["id"]], "tag_ids": [second_tag["id"]]},
    )

    assert updated.status_code == 200
    assert [item["id"] for item in updated.get_json()["topics"]] == [second_topic["id"]]
    assert [item["id"] for item in updated.get_json()["tags"]] == [second_tag["id"]]
    reloaded = client.get(f"/api/v1/questions/{question_id}").get_json()
    assert [item["id"] for item in reloaded["topics"]] == [second_topic["id"]]
    assert [item["id"] for item in reloaded["tags"]] == [second_tag["id"]]


def test_question_rejects_unknown_topic_id(client):
    fields = _error_fields(
        client.post("/api/v1/questions", json={"text": "Question?", "topic_ids": [999999]})
    )
    assert "topic_ids" in fields


def test_question_rejects_inactive_topic_id(client):
    topic = _create_topic(client)
    client.patch(f"/api/v1/topics/{topic['id']}", json={"is_active": False})

    fields = _error_fields(
        client.post(
            "/api/v1/questions",
            json={"text": "Question?", "topic_ids": [topic["id"]]},
        )
    )
    assert "topic_ids" in fields


def test_question_rejects_unknown_tag_id(client):
    fields = _error_fields(
        client.post("/api/v1/questions", json={"text": "Question?", "tag_ids": [999999]})
    )
    assert "tag_ids" in fields


def test_question_rejects_inactive_tag_id(client):
    tag = _create_tag(client)
    client.patch(f"/api/v1/tags/{tag['id']}", json={"is_active": False})

    fields = _error_fields(
        client.post("/api/v1/questions", json={"text": "Question?", "tag_ids": [tag["id"]]})
    )
    assert "tag_ids" in fields


def test_manual_question_defaults_active_and_unarchived(client):
    response = client.post("/api/v1/questions", json={"text": "Manual Agent question"})

    assert response.status_code == 201
    assert response.get_json()["status"] == "active"
    assert response.get_json()["archived_at"] is None


def test_archive_hides_question_but_preserves_record(client, db_session):
    created = client.post("/api/v1/questions", json={"text": "Archived question"})
    assert created.status_code == 201
    question = created.get_json()
    session = PracticeSession(mode="random", filters_json={}, selector_version="v1")
    db_session.add(session)
    db_session.flush()
    item = SessionItem(session_id=session.id, question_id=question["id"], ordinal=1, status="completed")
    db_session.add(item)
    db_session.flush()
    review = PracticeReview(
        question_id=question["id"],
        session_item_id=item.id,
        review_rating="basic",
        reviewed_at=datetime.now(timezone.utc),
    )
    db_session.add(review)
    db_session.commit()

    archived = client.post(f"/api/v1/questions/{question['id']}/archive")
    assert archived.status_code == 200
    assert archived.get_json()["status"] == "active"
    assert archived.get_json()["archived_at"]

    assert client.get("/api/v1/questions").get_json() == []
    assert len(client.get("/api/v1/questions?include_archived=true").get_json()) == 1
    assert client.get(f"/api/v1/questions/{question['id']}").status_code == 200
    db_session.expire_all()
    assert db_session.get(Question, question["id"]) is not None
    assert db_session.query(SessionItem).filter_by(id=item.id).count() == 1
    assert db_session.query(PracticeReview).filter_by(id=review.id).count() == 1


def test_question_state_flags_are_independent(client, db_session):
    created = client.post("/api/v1/questions", json={"text": "State flags question"})
    assert created.status_code == 201
    question = created.get_json()
    practice_session = PracticeSession(mode="random", filters_json={}, selector_version="v1")
    db_session.add(practice_session)
    db_session.flush()
    item = SessionItem(
        session_id=practice_session.id,
        question_id=question["id"],
        ordinal=1,
        status="completed",
    )
    db_session.add(item)
    db_session.flush()
    review = PracticeReview(
        question_id=question["id"],
        session_item_id=item.id,
        review_rating="vague",
        reviewed_at=datetime.now(timezone.utc),
    )
    db_session.add(review)
    db_session.commit()

    state = client.patch(
        f"/api/v1/questions/{question['id']}/state",
        json={"is_favorite": True, "is_wrong": True},
    )

    assert state.status_code == 200
    db_session.expire_all()
    assert db_session.get(PracticeReview, review.id).review_rating == "vague"
    assert db_session.query(PracticeReview).filter_by(session_item_id=item.id).count() == 1
