from flask import Blueprint, jsonify

from app.db import get_session
from app.services.dashboard import get_dashboard


blueprint = Blueprint("dashboard_v1", __name__, url_prefix="/api/v1")


@blueprint.get("/dashboard")
def dashboard():
    return jsonify(get_dashboard(get_session()))
