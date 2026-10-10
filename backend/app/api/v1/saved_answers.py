from flask import Blueprint, jsonify, request

from app.db import get_session
from app.services import saved_answers as service

blueprint = Blueprint("saved_answers_v1", __name__, url_prefix="/api/v1")


@blueprint.post("/questions/<int:question_id>/saved-answers")
def create(question_id):
    session = get_session()
    answer = service.create_answer(session, question_id, request.get_json(silent=True))
    return jsonify(service.answer_json(session, answer)), 201


@blueprint.get("/questions/<int:question_id>/saved-answers")
def index(question_id):
    return jsonify(service.list_answers(get_session(), question_id, request.args.get("include_archived") == "1"))


@blueprint.get("/saved-answers/<int:answer_id>/versions")
def versions(answer_id):
    return jsonify([service.version_json(v) for v in service.list_versions(get_session(), answer_id)])


@blueprint.post("/saved-answers/<int:answer_id>/versions")
def append(answer_id):
    return jsonify(service.version_json(service.append_version(get_session(), answer_id, request.get_json(silent=True)))), 201


@blueprint.patch("/saved-answer-versions/<int:version_id>/rating")
def rating(version_id):
    return jsonify(service.version_json(service.set_rating(get_session(), version_id, request.get_json(silent=True))))


@blueprint.patch("/saved-answers/<int:answer_id>/pin")
def pin(answer_id):
    session = get_session()
    return jsonify(service.answer_json(session, service.set_pin(session, answer_id, request.get_json(silent=True))))


@blueprint.post("/saved-answers/<int:answer_id>/archive")
def archive(answer_id):
    session = get_session()
    return jsonify(service.answer_json(session, service.archive_answer(session, answer_id)))
