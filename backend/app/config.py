from __future__ import annotations

import os
from pathlib import Path

from platformdirs import user_data_dir
from sqlalchemy.engine import URL


def default_data_dir() -> Path:
    configured = os.environ.get("APP_DATA_DIR")
    if configured:
        return Path(configured).expanduser()
    return Path(user_data_dir("AgentInterviewAssistant", "Local"))


def default_database_url() -> str:
    configured = os.environ.get("DATABASE_URL")
    if configured:
        return configured
    database_path = default_data_dir() / "interview_assistant.sqlite3"
    return URL.create("sqlite", database=str(database_path)).render_as_string(hide_password=False)


def allowed_origins_from_environment() -> list[str]:
    value = os.environ.get("APP_ALLOWED_ORIGINS", "")
    return [origin.strip().rstrip("/") for origin in value.split(",") if origin.strip()]


class Config:
    APP_DATA_DIR = default_data_dir()
    DATABASE_URL = default_database_url()
    ALLOWED_ORIGINS = allowed_origins_from_environment()
    FRONTEND_DIST_DIR = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    SEED_TOPICS_ON_STARTUP = True
    MAX_CONTENT_LENGTH = 2 * 1024 * 1024
