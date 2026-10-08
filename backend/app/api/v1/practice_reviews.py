from flask import Blueprint, jsonify, request
from datetime import timezone

from app.db import get_session
from app.errors import ApiError
from app.services.practice_review import (
    get_question_practice_reviews,
    record_practice_review,
    update_practice_review_rating,
)


blueprint = Blueprint("practice_reviews_v1", __name__, url_prefix="/api/v1")


def _review_json(review):
    def as_utc(value):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()

    return {
        "id": review.id,
        "question_id": review.question_id,
        "session_item_id": review.session_item_id,
        "review_rating": review.review_rating,
        "reviewed_at": as_utc(review.reviewed_at),
        "created_at": as_utc(review.created_at),
        "updated_at": as_utc(review.updated_at),
    }


@blueprint.post("/session-items/<int:session_item_id>/review")
def post_practice_review(session_item_id: int):
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or set(payload) != {"review_rating"}:
        raise ApiError(
            400,
            "VALIDATION_ERROR",
            "Invalid PracticeReview",
            {"body": "Expected only review_rating"},
        )
    review = record_practice_review(get_session(), session_item_id, payload["review_rating"])
    return jsonify(_review_json(review)), 201


@blueprint.patch("/practice-reviews/<int:review_id>")
def patch_practice_review(review_id: int):
    review = update_practice_review_rating(
        get_session(), review_id, request.get_json(silent=True)
    )
    return jsonify(_review_json(review))


@blueprint.get("/questions/<int:question_id>/practice-reviews")
def get_practice_review_history(question_id: int):
    reviews = get_question_practice_reviews(get_session(), question_id)
    return jsonify([_review_json(review) for review in reviews])
