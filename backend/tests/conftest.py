import importlib
import sys
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import URL


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def load_app_factory():
    package_init = BACKEND_ROOT / "app" / "__init__.py"
    if not package_init.is_file():
        return None

    app_module = importlib.import_module("app")
    factory = getattr(app_module, "create_app", None)
    if not callable(factory):
        return None
    return factory


@pytest.fixture
def app(tmp_path):
    factory = load_app_factory()
    if factory is None:
        return None
    data_dir = tmp_path / "isolated-app-data"
    database_path = tmp_path / "test.sqlite3"
    config = {
        "TESTING": False,
        "PROPAGATE_EXCEPTIONS": False,
        "APP_DATA_DIR": data_dir,
        "DATABASE_URL": f"sqlite:///{database_path}",
        "SEED_TOPICS_ON_STARTUP": False,
        "ALLOWED_ORIGINS": ["http://localhost:5173", "http://127.0.0.1:5173"],
    }
    database_url = URL.create("sqlite", database=str(database_path)).render_as_string(
        hide_password=False
    )
    config["DATABASE_URL"] = database_url
    alembic_ini = BACKEND_ROOT / "alembic.ini"
    if alembic_ini.is_file():
        alembic_config = Config(str(alembic_ini))
        alembic_config.set_main_option("sqlalchemy.url", database_url)
        command.upgrade(alembic_config, "head")
    app = factory(config)
    app.config.update(config)
    yield app
    app.extensions["sqlalchemy_engine"].dispose()


@pytest.fixture
def client(app):
    return app.test_client() if app is not None else None


@pytest.fixture
def db_session(app):
    assert app is not None, "missing feature: Flask app factory"
    session_factory = app.extensions["sqlalchemy_session_factory"]
    session = session_factory()
    try:
        yield session
    finally:
        if session.in_transaction():
            session.rollback()
        session.close()


def assert_error_envelope(response, status_code, error_code):
    assert response.status_code == status_code
    payload = response.get_json()
    assert set(payload) == {"error"}
    error = payload["error"]
    assert error["code"] == error_code
    assert isinstance(error["message"], str)
    assert "fields" not in error or isinstance(error["fields"], dict)
    return error
