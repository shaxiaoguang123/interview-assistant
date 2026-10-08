from importlib import import_module, util
from pathlib import Path

import pytest

from app.errors import ApiError
from app.models.question import Question, QuestionTopic
from app.models.taxonomy import Topic


def _validate_active_topic_ids():
    service_path = Path(__file__).resolve().parents[2] / "app" / "services" / "taxonomy.py"
    assert service_path.is_file(), "missing feature: taxonomy validation service"
    assert util.find_spec("app.services.taxonomy") is not None
    return import_module("app.services.taxonomy").validate_active_topic_ids


def test_topic_crud_and_reparent(client):
    parent_response = client.post(
        "/api/v1/topics", json={"slug": "agent", "name": "Agent"}
    )
    assert parent_response.status_code == 201
    parent = parent_response.get_json()
    assert parent["parent_id"] is None

    child_response = client.post(
        "/api/v1/topics",
        json={"slug": "prompt", "name": "Prompt", "parent_id": parent["id"]},
    )
    assert child_response.status_code == 201
    child = child_response.get_json()
    assert child["parent_id"] == parent["id"]

    rename_response = client.patch(
        f"/api/v1/topics/{child['id']}", json={"name": "Prompt Engineering"}
    )
    assert rename_response.status_code == 200
    assert rename_response.get_json()["name"] == "Prompt Engineering"

    listing = client.get("/api/v1/topics").get_json()
    assert any(topic["slug"] == "prompt" for topic in listing)


def test_topic_slug_is_immutable(client):
    created = client.post("/api/v1/topics", json={"slug": "stable-topic", "name": "Stable"})
    topic = created.get_json()

    response = client.patch(f"/api/v1/topics/{topic['id']}", json={"slug": "renamed-topic"})

    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "VALIDATION_ERROR"
    assert "slug" in response.get_json()["error"]["fields"]
    unchanged = client.get("/api/v1/topics").get_json()
    assert next(item for item in unchanged if item["id"] == topic["id"])["slug"] == "stable-topic"


def test_topic_parent_cycle_is_rejected(client):
    first_response = client.post("/api/v1/topics", json={"slug": "first", "name": "First"})
    assert first_response.status_code == 201
    first = first_response.get_json()
    second_response = client.post(
        "/api/v1/topics",
        json={"slug": "second", "name": "Second", "parent_id": first["id"]},
    )
    assert second_response.status_code == 201
    second = second_response.get_json()

    response = client.patch(f"/api/v1/topics/{first['id']}", json={"parent_id": second["id"]})

    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "VALIDATION_ERROR"
    assert "parent_id" in response.get_json()["error"]["fields"]


def test_deactivating_topic_preserves_existing_question_links(client, db_session):
    topic = Topic(track_key="agent_development", slug="linked-topic", name="Linked Topic")
    question = Question(
        text="How does MCP work?",
        normalized_text="how does mcp work?",
        search_text="how does mcp work?",
        normalized_hash="linked-question-hash",
    )
    db_session.add_all([topic, question])
    db_session.flush()
    db_session.add(QuestionTopic(question_id=question.id, topic_id=topic.id))
    db_session.commit()

    response = client.patch(f"/api/v1/topics/{topic.id}", json={"is_active": False})

    assert response.status_code == 200
    db_session.expire_all()
    assert db_session.get(Topic, topic.id).is_active is False
    assert db_session.query(QuestionTopic).filter_by(question_id=question.id, topic_id=topic.id).count() == 1


def test_validate_active_topic_ids_rejects_unknown_id(db_session):
    validate_active_topic_ids = _validate_active_topic_ids()
    with pytest.raises(ApiError) as error:
        validate_active_topic_ids(db_session, [999999])

    assert error.value.status_code == 400
    assert error.value.code == "VALIDATION_ERROR"
    assert "topic_ids" in error.value.fields


def test_validate_active_topic_ids_rejects_inactive_id(db_session):
    validate_active_topic_ids = _validate_active_topic_ids()
    topic = Topic(
        track_key="agent_development", slug="inactive-topic", name="Inactive", is_active=False
    )
    db_session.add(topic)
    db_session.commit()

    with pytest.raises(ApiError) as error:
        validate_active_topic_ids(db_session, [topic.id])

    assert error.value.status_code == 400
    assert error.value.code == "VALIDATION_ERROR"
    assert "topic_ids" in error.value.fields
