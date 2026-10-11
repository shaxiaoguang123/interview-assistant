from flask import Blueprint, jsonify, request

from app.db import get_session
from app.services import mock_interviews as service


blueprint = Blueprint("mock_interviews_v1", __name__, url_prefix="/api/v1")


@blueprint.get("/mock-interviews/options")
def get_options():
    return jsonify(service.options(get_session()))


@blueprint.post("/mock-interviews")
def post_start():
    return jsonify(service.start(get_session(), request.get_json(silent=True))), 201


@blueprint.get("/mock-interviews/saved")
def get_saved_list():
    return jsonify(service.list_saved(get_session()))


@blueprint.get("/mock-interviews/saved/<int:record_id>")
def get_saved_record(record_id: int):
    return jsonify(service.get_saved(get_session(), record_id))


@blueprint.get("/mock-interviews/<string:session_id>")
def get_temporary(session_id: str):
    return jsonify(service.read(session_id))


@blueprint.post("/mock-interviews/<string:session_id>/follow-up")
def post_follow_up(session_id: str):
    return jsonify(service.follow_up(get_session(), session_id, request.get_json(silent=True)))


@blueprint.post("/mock-interviews/<string:session_id>/next")
def post_next(session_id: str):
    return jsonify(service.next_question(session_id, request.get_json(silent=True)))


@blueprint.post("/mock-interviews/<string:session_id>/finish")
def post_finish(session_id: str):
    return jsonify(service.finish(session_id, request.get_json(silent=True)))


@blueprint.post("/mock-interviews/<string:session_id>/summary")
def post_summary(session_id: str):
    return jsonify(service.generate_summary(get_session(), session_id, request.get_json(silent=True)))


@blueprint.post("/mock-interviews/<string:session_id>/save")
def post_save(session_id: str):
    return jsonify(service.save(get_session(), session_id, request.get_json(silent=True))), 201
