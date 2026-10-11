from flask import Blueprint, current_app, jsonify

from app.services.system_status import get_system_status


blueprint = Blueprint("system_v1", __name__, url_prefix="/api/v1")


@blueprint.get("/system/status")
def system_status():
    return jsonify(get_system_status(current_app._get_current_object()))
