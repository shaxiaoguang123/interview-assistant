from __future__ import annotations

from flask import Blueprint, jsonify, request
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db import get_session
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


blueprint = Blueprint("questions_v1", __name__, url_prefix="/api/v1")


def _question_json(question):
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
        "archived_at": question.archived_at.isoformat() if question.archived_at else None,
        "created_at": question.created_at.isoformat() if question.created_at else None,
        "updated_at": question.updated_at.isoformat() if question.updated_at else None,
        "topics": topics,
        "tags": tags,
        "state": {
            "is_favorite": state.is_favorite if state else False,
            "is_wrong": state.is_wrong if state else False,
            "user_note": state.user_note if state else None,
        },
    }


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
    return jsonify([_question_json(question) for question in questions])


@blueprint.post("/questions")
def post_question():
    question = create_question(get_session(), request.get_json(silent=True))
    return jsonify(_question_json(question)), 201


@blueprint.get("/questions/<int:question_id>")
def get_question_by_id(question_id: int):
    return jsonify(_question_json(get_question(get_session(), question_id)))


@blueprint.patch("/questions/<int:question_id>")
def patch_question(question_id: int):
    question = update_question(get_session(), question_id, request.get_json(silent=True))
    return jsonify(_question_json(question))


@blueprint.post("/questions/<int:question_id>/archive")
def post_archive_question(question_id: int):
    question = archive_question(get_session(), question_id)
    return jsonify(_question_json(question))


@blueprint.patch("/questions/<int:question_id>/state")
def patch_question_state(question_id: int):
    state = update_question_state(get_session(), question_id, request.get_json(silent=True))
    return jsonify(
        {
            "question_id": state.question_id,
            "is_favorite": state.is_favorite,
            "is_wrong": state.is_wrong,
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
    return jsonify(
        [
            {
                "question_source_id": source.id,
                "question_id": source.question_id,
                "source_asset_id": source.source_asset_id,
                "source_type": source.source_asset.source_type,
                "source_title": source.source_asset.title,
                "original_filename": source.source_asset.original_filename,
                "mime_type": source.source_asset.mime_type,
                "locator_type": source.locator_type,
                "locator_json": source.locator_json,
                "locator_correction_json": source.locator_correction_json,
                "source_text_snapshot": source.source_text_snapshot,
                "raw_ocr_text_snapshot": source.raw_ocr_text_snapshot,
                "confidence": source.confidence,
                "ocr_block_ids": [
                    link.ocr_block.id
                    for link in sorted(
                        source.ocr_block_links,
                        key=lambda item: (
                            item.ocr_block.reading_order,
                            item.ocr_block.id,
                        ),
                    )
                ],
                "ocr_blocks": [
                    {
                        "id": link.ocr_block.id,
                        "text": link.ocr_block.text,
                        "bbox": link.ocr_block.bbox_json,
                        "reading_order": link.ocr_block.reading_order,
                        "confidence": link.ocr_block.confidence,
                    }
                    for link in sorted(
                        source.ocr_block_links,
                        key=lambda item: (
                            item.ocr_block.reading_order,
                            item.ocr_block.id,
                        ),
                    )
                ],
                "original_image_url": f"/api/v1/sources/{source.source_asset_id}/original",
                "display_image_url": f"/api/v1/sources/{source.source_asset_id}/display",
            }
            for source in sources
        ]
    )
