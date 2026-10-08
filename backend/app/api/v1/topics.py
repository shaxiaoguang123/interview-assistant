from flask import Blueprint, jsonify, request

from app.db import get_session
from app.repositories.taxonomy import list_topics
from app.services.taxonomy import create_topic, update_topic


blueprint = Blueprint("topics_v1", __name__, url_prefix="/api/v1")


def _topic_json(topic):
    return {
        "id": topic.id,
        "track_key": topic.track_key,
        "parent_id": topic.parent_id,
        "slug": topic.slug,
        "name": topic.name,
        "sort_order": topic.sort_order,
        "is_active": topic.is_active,
    }


@blueprint.get("/topics")
def get_topics():
    topics = list_topics(get_session())
    return jsonify([_topic_json(topic) for topic in topics])


@blueprint.post("/topics")
def post_topic():
    topic = create_topic(get_session(), request.get_json(silent=True))
    return jsonify(_topic_json(topic)), 201


@blueprint.patch("/topics/<int:topic_id>")
def patch_topic(topic_id: int):
    topic = update_topic(get_session(), topic_id, request.get_json(silent=True))
    return jsonify(_topic_json(topic))
