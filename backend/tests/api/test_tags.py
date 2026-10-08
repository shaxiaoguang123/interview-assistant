from importlib import import_module, util
from pathlib import Path

import pytest

from app.errors import ApiError
from app.models.question import Question, QuestionTag
from app.models.taxonomy import Tag


def _validate_active_tag_ids():
    service_path = Path(__file__).resolve().parents[2] / "app" / "services" / "taxonomy.py"
    assert service_path.is_file(), "missing feature: taxonomy validation service"
    assert util.find_spec("app.services.taxonomy") is not None
    return import_module("app.services.taxonomy").validate_active_tag_ids


def test_tag_crud(client):
    created = client.post("/api/v1/tags", json={"name": "Agent Security"})
    assert created.status_code == 201
    tag = created.get_json()

    renamed = client.patch(f"/api/v1/tags/{tag['id']}", json={"name": "Security"})
    assert renamed.status_code == 200
    assert renamed.get_json()["name"] == "Security"

    deactivated = client.patch(f"/api/v1/tags/{tag['id']}", json={"is_active": False})
    assert deactivated.status_code == 200
    assert deactivated.get_json()["is_active"] is False

    listing = client.get("/api/v1/tags").get_json()
    assert any(item["id"] == tag["id"] and item["is_active"] is False for item in listing)


def test_deactivating_tag_preserves_existing_question_links(client, db_session):
    tag = Tag(name="Linked Tag")
    question = Question(
        text="What is RAG?",
        normalized_text="what is rag?",
        search_text="what is rag?",
        normalized_hash="linked-tag-question-hash",
    )
    db_session.add_all([tag, question])
    db_session.flush()
    db_session.add(QuestionTag(question_id=question.id, tag_id=tag.id))
    db_session.commit()

    response = client.patch(f"/api/v1/tags/{tag.id}", json={"is_active": False})

    assert response.status_code == 200
    db_session.expire_all()
    assert db_session.get(Tag, tag.id).is_active is False
    assert db_session.query(QuestionTag).filter_by(question_id=question.id, tag_id=tag.id).count() == 1


def test_validate_active_tag_ids_rejects_unknown_id(db_session):
    validate_active_tag_ids = _validate_active_tag_ids()
    with pytest.raises(ApiError) as error:
        validate_active_tag_ids(db_session, [999999])

    assert error.value.status_code == 400
    assert error.value.code == "VALIDATION_ERROR"
    assert "tag_ids" in error.value.fields


def test_validate_active_tag_ids_rejects_inactive_id(db_session):
    validate_active_tag_ids = _validate_active_tag_ids()
    tag = Tag(name="Inactive Tag", is_active=False)
    db_session.add(tag)
    db_session.commit()

    with pytest.raises(ApiError) as error:
        validate_active_tag_ids(db_session, [tag.id])

    assert error.value.status_code == 400
    assert error.value.code == "VALIDATION_ERROR"
    assert "tag_ids" in error.value.fields
