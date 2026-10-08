from flask import Blueprint, jsonify


blueprint = Blueprint("health_v1", __name__, url_prefix="/api/v1")


@blueprint.get("/health")
def health():
    return jsonify({"status": "ok"})
