from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.models.taxonomy import Tag, Topic
from app.repositories import taxonomy as taxonomy_repository


def _validate_active_ids(
    session: Session,
    ids: Iterable[int] | None,
    *,
    model: type[Topic] | type[Tag],
    field_name: str,
    label: str,
) -> list[Topic] | list[Tag]:
    if ids is None:
        return []
    if not isinstance(ids, (list, tuple, set)):
        raise ApiError(400, "VALIDATION_ERROR", f"Invalid {label} selection", {field_name: "Must be a list of IDs"})

    ordered_ids: list[int] = []
    for value in ids:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ApiError(400, "VALIDATION_ERROR", f"Invalid {label} selection", {field_name: "Contains an invalid ID"})
        if value not in ordered_ids:
            ordered_ids.append(value)
    if not ordered_ids:
        return []

    if model is Topic:
        rows = taxonomy_repository.get_topics_by_ids(session, ordered_ids)
    else:
        rows = taxonomy_repository.get_tags_by_ids(session, ordered_ids)
    by_id = {row.id: row for row in rows}
    missing = [value for value in ordered_ids if value not in by_id]
    inactive = [value for value in ordered_ids if value in by_id and not by_id[value].is_active]
    problems: list[str] = []
    if missing:
        problems.append(f"Unknown {label} ID(s): {', '.join(map(str, missing))}")
    if inactive:
        problems.append(f"Inactive {label} ID(s): {', '.join(map(str, inactive))}")
    if problems:
        raise ApiError(400, "VALIDATION_ERROR", f"Invalid {label} selection", {field_name: "; ".join(problems)})
    return [by_id[value] for value in ordered_ids]


def validate_active_topic_ids(session: Session, ids: Iterable[int] | None) -> list[Topic]:
    return _validate_active_ids(session, ids, model=Topic, field_name="topic_ids", label="Topic")


def validate_active_tag_ids(session: Session, ids: Iterable[int] | None) -> list[Tag]:
    return _validate_active_ids(session, ids, model=Tag, field_name="tag_ids", label="Tag")


def _required_text(payload: dict, field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ApiError(400, "VALIDATION_ERROR", f"Invalid {field}", {field: "This field is required"})
    return value.strip()


def _optional_bool(payload: dict, field: str, current: bool) -> bool:
    if field not in payload:
        return current
    value = payload[field]
    if not isinstance(value, bool):
        raise ApiError(400, "VALIDATION_ERROR", f"Invalid {field}", {field: "Must be a boolean"})
    return value


def _validated_parent_id(session: Session, parent_id: object, *, topic_id: int | None = None) -> int | None:
    if parent_id is None:
        return None
    if isinstance(parent_id, bool) or not isinstance(parent_id, int) or parent_id <= 0:
        raise ApiError(400, "VALIDATION_ERROR", "Invalid parent", {"parent_id": "Must be a valid Topic ID"})
    parent = taxonomy_repository.get_topic(session, parent_id)
    if parent is None:
        raise ApiError(400, "VALIDATION_ERROR", "Invalid parent", {"parent_id": "Topic does not exist"})

    seen: set[int] = set()
    cursor: Topic | None = parent
    while cursor is not None:
        if cursor.id == topic_id:
            raise ApiError(400, "VALIDATION_ERROR", "Invalid parent", {"parent_id": "Topic hierarchy cannot contain a cycle"})
        if cursor.id in seen:
            raise ApiError(409, "CONFLICT", "Existing Topic hierarchy contains a cycle")
        seen.add(cursor.id)
        cursor = taxonomy_repository.get_topic(session, cursor.parent_id) if cursor.parent_id else None
    return parent.id


def create_topic(session: Session, payload: dict) -> Topic:
    if not isinstance(payload, dict):
        raise ApiError(400, "VALIDATION_ERROR", "Invalid Topic", {"body": "Expected a JSON object"})
    slug = _required_text(payload, "slug")
    name = _required_text(payload, "name")
    try:
        with session.begin():
            if taxonomy_repository.topic_slug_exists(session, slug):
                raise ApiError(409, "CONFLICT", "Topic slug already exists", {"slug": "Already in use"})
            parent_id = _validated_parent_id(session, payload.get("parent_id"))
            sort_order = payload.get("sort_order", 0)
            if isinstance(sort_order, bool) or not isinstance(sort_order, int):
                raise ApiError(400, "VALIDATION_ERROR", "Invalid sort order", {"sort_order": "Must be an integer"})
            topic = Topic(
                track_key="agent_development",
                parent_id=parent_id,
                slug=slug,
                name=name,
                sort_order=sort_order,
                is_active=True,
            )
            session.add(topic)
            session.flush()
        return topic
    except IntegrityError as error:
        raise ApiError(409, "CONFLICT", "Topic conflicts with an existing record", {"slug": "Already in use"}) from error


def update_topic(session: Session, topic_id: int, payload: dict) -> Topic:
    if not isinstance(payload, dict) or not payload:
        raise ApiError(400, "VALIDATION_ERROR", "Invalid Topic update", {"body": "Expected a non-empty JSON object"})
    if "slug" in payload:
        raise ApiError(400, "VALIDATION_ERROR", "Topic slug cannot be changed", {"slug": "Immutable after creation"})
    allowed = {"name", "parent_id", "sort_order", "is_active"}
    unknown = set(payload) - allowed
    if unknown:
        raise ApiError(400, "VALIDATION_ERROR", "Invalid Topic update", {"body": f"Unsupported fields: {', '.join(sorted(unknown))}"})
    try:
        with session.begin():
            topic = taxonomy_repository.get_topic(session, topic_id)
            if topic is None:
                raise ApiError(404, "NOT_FOUND", "Topic not found")
            if "name" in payload:
                topic.name = _required_text(payload, "name")
            if "parent_id" in payload:
                topic.parent_id = _validated_parent_id(session, payload["parent_id"], topic_id=topic_id)
            if "sort_order" in payload:
                sort_order = payload["sort_order"]
                if isinstance(sort_order, bool) or not isinstance(sort_order, int):
                    raise ApiError(400, "VALIDATION_ERROR", "Invalid sort order", {"sort_order": "Must be an integer"})
                topic.sort_order = sort_order
            topic.is_active = _optional_bool(payload, "is_active", topic.is_active)
            session.flush()
        return topic
    except IntegrityError as error:
        raise ApiError(409, "CONFLICT", "Topic conflicts with an existing record", {"slug": "Already in use"}) from error


def create_tag(session: Session, payload: dict) -> Tag:
    if not isinstance(payload, dict):
        raise ApiError(400, "VALIDATION_ERROR", "Invalid Tag", {"body": "Expected a JSON object"})
    name = _required_text(payload, "name")
    try:
        with session.begin():
            if taxonomy_repository.tag_name_exists(session, name):
                raise ApiError(409, "CONFLICT", "Tag name already exists", {"name": "Already in use"})
            tag = Tag(name=name, is_active=True)
            session.add(tag)
            session.flush()
        return tag
    except IntegrityError as error:
        raise ApiError(409, "CONFLICT", "Tag conflicts with an existing record", {"name": "Already in use"}) from error


def update_tag(session: Session, tag_id: int, payload: dict) -> Tag:
    if not isinstance(payload, dict) or not payload:
        raise ApiError(400, "VALIDATION_ERROR", "Invalid Tag update", {"body": "Expected a non-empty JSON object"})
    allowed = {"name", "is_active"}
    unknown = set(payload) - allowed
    if unknown:
        raise ApiError(400, "VALIDATION_ERROR", "Invalid Tag update", {"body": f"Unsupported fields: {', '.join(sorted(unknown))}"})
    try:
        with session.begin():
            tag = taxonomy_repository.get_tag(session, tag_id)
            if tag is None:
                raise ApiError(404, "NOT_FOUND", "Tag not found")
            if "name" in payload:
                name = _required_text(payload, "name")
                if taxonomy_repository.tag_name_exists(session, name, excluding_id=tag_id):
                    raise ApiError(409, "CONFLICT", "Tag name already exists", {"name": "Already in use"})
                tag.name = name
            tag.is_active = _optional_bool(payload, "is_active", tag.is_active)
            session.flush()
        return tag
    except IntegrityError as error:
        raise ApiError(409, "CONFLICT", "Tag conflicts with an existing record", {"name": "Already in use"}) from error
