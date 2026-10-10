from __future__ import annotations

from flask import Blueprint, jsonify, request
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db import get_session
from app.repositories import questions as question_repository
from app.services.question_history import get_canonical_history
from .serializers import source_json, review_json, session_item_json
from app.services.review_schedule import schedule_json
from app.services.question_relations import (
    get_similar_candidates,
    review_question_relation,
    scan_similar_candidates,
)
from app.errors import ApiError
from app.models.ingestion import QuestionSource, QuestionSourceOCRBlock
from app.models.question import Question
from app.services.questions import (
    archive_question,
    create_question,
    get_question,
    list_questions,
    update_question,
    update_question_state,
)
from app.services.search import search_questions
from app.services.question_merge import merge_question, preview_question_merge


blueprint = Blueprint("questions_v1", __name__, url_prefix="/api/v1")


def _question_json(question, flags=None):
    state = question.state
    topics = [
        {
            "id": link.topic.id,
            "parent_id": link.topic.parent_id,
            "slug": link.topic.slug,
            "name": link.topic.name,
            "is_active": link.topic.is_active,
        }
        for link in question.topic_links
    ]
    tags = [
        {"id": link.tag.id, "name": link.tag.name, "is_active": link.tag.is_active}
        for link in question.tag_links
    ]
    return {
        "id": question.id,
        "text": question.text,
        "normalized_text": question.normalized_text,
        "search_text": question.search_text,
        "normalized_hash": question.normalized_hash,
        "answer_type": question.answer_type,
        "difficulty": question.difficulty,
        "status": question.status,
        "canonical_question_id": question.merged_into_question_id or (
            question.id if question.status == "active" else None
        ),
        "canonical_member_count": flags["member_count"] if flags else None,
        "archived_at": question.archived_at.isoformat() if question.archived_at else None,
        "created_at": question.created_at.isoformat() if question.created_at else None,
        "updated_at": question.updated_at.isoformat() if question.updated_at else None,
        "topics": topics,
        "tags": tags,
        "state": {
            "is_favorite": flags["is_favorite"] if flags else (state.is_favorite if state else False),
            "is_wrong": flags["is_wrong"] if flags else (state.is_wrong if state else False),
            "user_note": state.user_note if state else None,
            **schedule_json(state),
        },
    }


def _question_response(question):
    flags = None
    if question.status == 'active' and question.merged_into_question_id is None:
        flags = question_repository.group_states(get_session(), [question.id]).get(question.id)
    return _question_json(question, flags)


def _parse_id_filters(field: str) -> list[int] | None:
    values = request.args.getlist(field)
    if not values:
        return None
    try:
        ids = [int(value) for value in values]
    except ValueError as error:
        raise ApiError(400, "VALIDATION_ERROR", "Invalid question filter", {field: "IDs must be integers"}) from error
    if any(value <= 0 for value in ids):
        raise ApiError(400, "VALIDATION_ERROR", "Invalid question filter", {field: "IDs must be positive"})
    return ids


def _parse_bool_arg(field: str, default: bool | None) -> bool | None:
    value = request.args.get(field)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"true", "1"}:
        return True
    if normalized in {"false", "0"}:
        return False
    raise ApiError(400, "VALIDATION_ERROR", "Invalid question filter", {field: "Must be true or false"})


@blueprint.get("/questions")
def get_questions():
    session = get_session()
    filters = {
        "include_archived": _parse_bool_arg("include_archived", False) or False,
        "topic_ids": _parse_id_filters("topic_ids"),
        "tag_ids": _parse_id_filters("tag_ids"),
        "is_favorite": _parse_bool_arg("is_favorite", None),
        "is_wrong": _parse_bool_arg("is_wrong", None),
    }
    query = request.args.get("q")
    if query is not None:
        questions = search_questions(session, query, filters)
    else:
        questions = list_questions(session, **filters)
    flags = question_repository.group_states(session, [question.id for question in questions])
    return jsonify([_question_json(question, flags.get(question.id)) for question in questions])


@blueprint.post("/questions")
def post_question():
    question = create_question(get_session(), request.get_json(silent=True))
    return jsonify(_question_response(question)), 201


@blueprint.get("/questions/<int:question_id>")
def get_question_by_id(question_id: int):
    return jsonify(_question_response(get_question(get_session(), question_id)))


@blueprint.get("/questions/<int:question_id>/similar-candidates")
def get_question_similar_candidates(question_id: int):
    return jsonify(get_similar_candidates(get_session(), question_id))


@blueprint.post("/questions/<int:question_id>/similar-candidates/scan")
def post_question_similarity_scan(question_id: int):
    return jsonify(scan_similar_candidates(get_session(), question_id))


@blueprint.patch("/question-relations/<int:relation_id>")
def patch_question_relation(relation_id: int):
    return jsonify(review_question_relation(
        get_session(), relation_id, request.get_json(silent=True)
    ))


@blueprint.get("/questions/<int:canonical_id>/merge-preview")
def get_question_merge_preview(canonical_id: int):
    values = request.args.getlist("source_question_id")
    if len(values) != 1 or not values[0].isascii() or not values[0].isdecimal() or int(values[0]) <= 0:
        raise ApiError(400, "VALIDATION_ERROR", "source_question_id must be one positive integer")
    return jsonify(preview_question_merge(get_session(), canonical_id, int(values[0])))


@blueprint.post("/questions/<int:canonical_id>/merge")
def post_question_merge(canonical_id: int):
    result = merge_question(get_session(), canonical_id, request.get_json(silent=True))
    return jsonify(_question_response(result))


@blueprint.patch("/questions/<int:question_id>")
def patch_question(question_id: int):
    question = update_question(get_session(), question_id, request.get_json(silent=True))
    return jsonify(_question_response(question))


@blueprint.post("/questions/<int:question_id>/archive")
def post_archive_question(question_id: int):
    question = archive_question(get_session(), question_id)
    return jsonify(_question_response(question))


@blueprint.patch("/questions/<int:question_id>/state")
def patch_question_state(question_id: int):
    state = update_question_state(get_session(), question_id, request.get_json(silent=True))
    flags = question_repository.group_states(get_session(), [state.question_id])[state.question_id]
    return jsonify(
        {
            **schedule_json(state),
            "question_id": state.question_id,
            "is_favorite": flags["is_favorite"],
            "is_wrong": flags["is_wrong"],
            "user_note": state.user_note,
            "updated_at": state.updated_at.isoformat() if state.updated_at else None,
        }
    )


@blueprint.get("/questions/<int:question_id>/sources")
def get_question_sources(question_id: int):
    session = get_session()
    if session.get(Question, question_id) is None:
        raise ApiError(404, "NOT_FOUND", "Question not found")
    sources = list(
        session.scalars(
            select(QuestionSource)
            .options(
                selectinload(QuestionSource.source_asset),
                selectinload(QuestionSource.ocr_block_links).selectinload(
                    QuestionSourceOCRBlock.ocr_block
                ),
            )
            .where(QuestionSource.question_id == question_id)
            .order_by(QuestionSource.id)
        )
    )
    return jsonify([source_json(source) for source in sources])


@blueprint.get("/questions/<int:question_id>/history")
def get_question_history(question_id: int):
    history = get_canonical_history(get_session(), question_id)
    return jsonify({
        'canonical_question_id': history['canonical_question_id'],
        'member_question_ids': history['member_question_ids'],
        'sources': [source_json(row) for row in history['sources']],
        'practice_reviews': [review_json(row) for row in history['practice_reviews']],
        'session_items': [session_item_json(row) for row in history['session_items']],
        'saved_answers': history['saved_answers'],
    })
