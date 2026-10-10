from flask import Blueprint, jsonify, request

from app.db import get_session
from app.errors import ApiError
from app.services.progress import get_progress

blueprint = Blueprint("progress_v1", __name__, url_prefix="/api/v1")


@blueprint.get("/progress")
def progress():
    raw = request.args.get("window_days", "30")
    if not raw.isascii() or not raw.isdecimal() or not 1 <= int(raw) <= 365:
        raise ApiError(400, "VALIDATION_ERROR", "window_days must be an integer from 1 to 365")
    return jsonify(get_progress(get_session(), window_days=int(raw)))
