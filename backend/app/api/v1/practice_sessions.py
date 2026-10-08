from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.db import get_session
from app.errors import ApiError
from app.repositories.practice import get_practice_session
from app.services.practice_selector import create_practice_session
from app.services.practice_session import skip_session_item


blueprint = Blueprint("practice_sessions_v1", __name__, url_prefix="/api/v1")


def _timestamp(value):
    return value.isoformat() if value is not None else None


def _item_json(item):
    question = item.question
    return {
        "id": item.id,
        "session_id": item.session_id,
        "question_id": item.question_id,
        "ordinal": item.ordinal,
        "status": item.status,
        "selection_reason": item.selection_reason,
        "viewed_at": _timestamp(item.viewed_at),
        "completed_at": _timestamp(item.completed_at),
        "question": {
            "id": question.id,
            "text": question.text,
            "status": question.status,
            "archived_at": _timestamp(question.archived_at),
        },
    }


def _session_json(practice_session):
    return {
        "id": practice_session.id,
        "mode": practice_session.mode,
        "filters_json": practice_session.filters_json,
        "selector_version": practice_session.selector_version,
        "selection_seed": practice_session.selection_seed,
        "started_at": _timestamp(practice_session.started_at),
        "completed_at": _timestamp(practice_session.completed_at),
        "items": [_item_json(item) for item in practice_session.items],
    }


@blueprint.post("/practice-sessions")
def post_practice_session():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise ApiError(400, "VALIDATION_ERROR", "Invalid practice session", {"body": "Expected a JSON object"})
    allowed = {"mode", "filters", "limit", "selection_seed"}
    unknown = set(payload) - allowed
    if unknown:
        raise ApiError(400, "VALIDATION_ERROR", "Invalid practice session", {"body": f"Unsupported fields: {', '.join(sorted(unknown))}"})
    filters = payload.get("filters", {})
    practice_session = create_practice_session(
        get_session(),
        payload.get("mode"),
        filters,
        payload.get("limit", 10),
        payload.get("selection_seed"),
    )
    return jsonify(_session_json(practice_session)), 201


@blueprint.get("/practice-sessions/<int:session_id>")
def get_practice_session_by_id(session_id: int):
    practice_session = get_practice_session(get_session(), session_id)
    if practice_session is None:
        raise ApiError(404, "NOT_FOUND", "Practice session not found")
    return jsonify(_session_json(practice_session))


@blueprint.post("/session-items/<int:session_item_id>/skip")
def post_skip_session_item(session_item_id: int):
    item, practice_session = skip_session_item(get_session(), session_item_id)
    return jsonify({"item": _item_json(item), "session": _session_json(practice_session)})
