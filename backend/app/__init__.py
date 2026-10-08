from __future__ import annotations

from pathlib import Path

from flask import Flask, abort, send_from_directory

from .api.v1.health import blueprint as health_blueprint
from .api.v1.practice_sessions import blueprint as practice_sessions_blueprint
from .api.v1.practice_reviews import blueprint as practice_reviews_blueprint
from .api.v1.questions import blueprint as questions_blueprint
from .api.v1.tags import blueprint as tags_blueprint
from .api.v1.topics import blueprint as topics_blueprint
from .config import Config
from .db import init_db
from .errors import register_error_handlers
from .local_security import register_local_security


def _register_frontend_routes(app: Flask) -> None:
    dist_dir = Path(app.config["FRONTEND_DIST_DIR"])
    if not (dist_dir / "index.html").is_file():
        return

    def serve_frontend(path: str = ""):
        if path == "api" or path.startswith("api/"):
            abort(404)
        candidate = dist_dir / path
        if path and candidate.is_file():
            return send_from_directory(dist_dir, path)
        return send_from_directory(dist_dir, "index.html")

    app.add_url_rule("/", defaults={"path": ""}, view_func=serve_frontend, endpoint="frontend_root")
    app.add_url_rule("/<path:path>", view_func=serve_frontend, endpoint="frontend_path")


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__, static_folder=None)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)

    register_error_handlers(app)
    init_db(app)
    register_local_security(app)
    app.register_blueprint(health_blueprint)
    app.register_blueprint(questions_blueprint)
    app.register_blueprint(practice_sessions_blueprint)
    app.register_blueprint(practice_reviews_blueprint)
    _register_frontend_routes(app)
    app.register_blueprint(topics_blueprint)
    app.register_blueprint(tags_blueprint)

    if app.config.get("SEED_TOPICS_ON_STARTUP", False):
        from .services.topic_seed import seed_initial_topics

        session_factory = app.extensions["sqlalchemy_session_factory"]
        with session_factory.begin() as session:
            seed_initial_topics(session)

    return app
