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


def default_source_storage_dir() -> Path:
    return default_data_dir() / "sources"


def default_ocr_model_dir() -> Path:
    configured = os.environ.get("OCR_MODEL_DIR")
    if configured:
        return Path(configured).expanduser()
    return default_data_dir() / "ocr-models" / "rapidocr-3.9.2" / "ppocrv6-small"


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
    SOURCE_STORAGE_DIR = default_source_storage_dir()
    DATABASE_URL = default_database_url()
    ALLOWED_ORIGINS = allowed_origins_from_environment()
    FRONTEND_DIST_DIR = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    SEED_TOPICS_ON_STARTUP = True
    MAX_UPLOAD_FILES = 10
    SOURCE_MAX_FILE_BYTES = 20 * 1024 * 1024
    SOURCE_MAX_DECODED_PIXELS = 40_000_000
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024
    OCR_ENGINE = os.environ.get("OCR_ENGINE", "rapidocr_onnx")
    OCR_RAPIDOCR_VERSION = "3.9.2"
    OCR_ONNXRUNTIME_VERSION = "1.30.0"
    OCR_MODEL_DIR = default_ocr_model_dir()
    OCR_MODEL_MANIFEST_PATH = Path(
        os.environ.get("OCR_MODEL_MANIFEST_PATH", str(OCR_MODEL_DIR / "manifest.json"))
    ).expanduser()
    OCR_DETECTION_MODEL_PATH = Path(
        os.environ.get(
            "OCR_DETECTION_MODEL_PATH",
            str(OCR_MODEL_DIR / "PP-OCRv6_det_small.onnx"),
        )
    ).expanduser()
    OCR_RECOGNITION_MODEL_PATH = Path(
        os.environ.get(
            "OCR_RECOGNITION_MODEL_PATH",
            str(OCR_MODEL_DIR / "PP-OCRv6_rec_small.onnx"),
        )
    ).expanduser()
    OCR_CLASSIFICATION_MODEL_PATH = Path(
        os.environ.get(
            "OCR_CLASSIFICATION_MODEL_PATH",
            str(OCR_MODEL_DIR / "ch_ppocr_mobile_v2.0_cls_mobile.onnx"),
        )
    ).expanduser()
    OCR_ADAPTER_FACTORY = None
    LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "")
    LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
    LLM_MODEL = os.environ.get("LLM_MODEL", "")
    LLM_TIMEOUT_SECONDS = 60
    LLM_PROVIDER_FACTORY = None
    DEBUG = os.environ.get("APP_DEBUG", "").strip().lower() in {"1", "true", "yes"}
