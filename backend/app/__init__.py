from __future__ import annotations

from flask import Flask

from .api.v1.health import blueprint as health_blueprint
from .config import Config
from .db import init_db
from .errors import register_error_handlers
from .local_security import register_local_security


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__, static_folder=None)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)

    register_error_handlers(app)
    init_db(app)
    register_local_security(app)
    app.register_blueprint(health_blueprint)

    if app.config.get("SEED_TOPICS_ON_STARTUP", False):
        from .services.topic_seed import seed_initial_topics

        session_factory = app.extensions["sqlalchemy_session_factory"]
        with session_factory.begin() as session:
            seed_initial_topics(session)

    return app
