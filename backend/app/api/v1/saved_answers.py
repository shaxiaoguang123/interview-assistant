from flask import Blueprint, jsonify, request

from app.db import get_session
from app.services import saved_answers as service
from app.services.mock_interview_exports import answer_source_for_version, answer_sources_for_versions

blueprint = Blueprint("saved_answers_v1", __name__, url_prefix="/api/v1")


@blueprint.post("/questions/<int:question_id>/saved-answers")
def create(question_id):
    session = get_session()
    answer = service.create_answer(session, question_id, request.get_json(silent=True))
    return jsonify(service.answer_json(session, answer)), 201


@blueprint.get("/questions/<int:question_id>/saved-answers")
def index(question_id):
    session = get_session()
    answers = service.list_answers(session, question_id, request.args.get("include_archived") == "1")
    sources = answer_sources_for_versions(
        session, [row["current_version"]["id"] for row in answers]
    )
    for row in answers:
        version_id = row["current_version"]["id"]
        if version_id in sources:
            row["current_version"]["mock_interview_source"] = sources[version_id]
    return jsonify(answers)


@blueprint.get("/saved-answers/<int:answer_id>/versions")
def versions(answer_id):
    session = get_session()
    rows = service.list_versions(session, answer_id)
    sources = answer_sources_for_versions(session, [row.id for row in rows])
    return jsonify([
        ({**service.version_json(row), "mock_interview_source": sources[row.id]}
         if row.id in sources else service.version_json(row))
        for row in rows
    ])


@blueprint.get("/saved-answer-versions/<int:version_id>/mock-interview-source")
def mock_interview_source(version_id):
    source = answer_source_for_version(get_session(), version_id)
    if source is None:
        from app.errors import ApiError

        raise ApiError(404, "NOT_FOUND", "This answer version has no mock-interview source")
    return jsonify(source)


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
