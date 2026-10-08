from flask import Blueprint, jsonify, request

from app.db import get_session
from app.repositories.taxonomy import list_tags
from app.services.taxonomy import create_tag, update_tag


blueprint = Blueprint("tags_v1", __name__, url_prefix="/api/v1")


def _tag_json(tag):
    return {"id": tag.id, "name": tag.name, "is_active": tag.is_active}


@blueprint.get("/tags")
def get_tags():
    tags = list_tags(get_session())
    return jsonify([_tag_json(tag) for tag in tags])


@blueprint.post("/tags")
def post_tag():
    tag = create_tag(get_session(), request.get_json(silent=True))
    return jsonify(_tag_json(tag)), 201


@blueprint.patch("/tags/<int:tag_id>")
def patch_tag(tag_id: int):
    tag = update_tag(get_session(), tag_id, request.get_json(silent=True))
    return jsonify(_tag_json(tag))
