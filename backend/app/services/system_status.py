"""Read-only local runtime status for the workspace and setup diagnostics."""
from __future__ import annotations

from importlib import metadata
from pathlib import Path
import platform

from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from flask import Flask
from platformdirs import user_data_dir
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from app.ocr.adapter import OCRAdapterInitializationError
from app.ocr.rapidocr_adapter import _model_paths
from app.services.provider_settings import public_provider_settings


def migration_heads() -> list[str]:
    backend_root = Path(__file__).resolve().parents[2]
    config = AlembicConfig(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "migrations"))
    return ScriptDirectory.from_config(config).get_heads()


def _database_status(engine: Engine) -> dict:
    heads = migration_heads()
    url = engine.url
    if url.get_backend_name() == "sqlite" and url.database not in (None, ":memory:"):
        if not Path(url.database).expanduser().exists():
            return {
                "ready": False,
                "state": "not_initialized",
                "current_revision": None,
                "latest_revision": heads[0] if len(heads) == 1 else heads,
                "migration_required": True,
            }

    try:
        with engine.connect() as connection:
            if not inspect(connection).has_table("alembic_version"):
                return {
                    "ready": False,
                    "state": "not_initialized",
                    "current_revision": None,
                    "latest_revision": heads[0] if len(heads) == 1 else heads,
                    "migration_required": True,
                }
            current = sorted(
                row[0]
                for row in connection.execute(text("SELECT version_num FROM alembic_version"))
            )
        ready = bool(heads) and set(current) == set(heads)
        return {
            "ready": ready,
            "state": "ready" if ready else "upgrade_required",
            "current_revision": current[0] if len(current) == 1 else current,
            "latest_revision": heads[0] if len(heads) == 1 else heads,
            "migration_required": not ready,
        }
    except SQLAlchemyError:
        return {
            "ready": False,
            "state": "unavailable",
            "current_revision": None,
            "latest_revision": heads[0] if len(heads) == 1 else heads,
            "migration_required": True,
        }


def _ocr_status(config: dict) -> dict:
    try:
        _model_paths(config)
        rapidocr_version = metadata.version("rapidocr")
        onnxruntime_version = metadata.version("onnxruntime")
    except OCRAdapterInitializationError as error:
        if error.code == "OCR_MODEL_MISSING":
            return {
                "ready": False,
                "state": "missing",
                "message": "OCR 模型尚未准备。请按 README“本地 OCR 模型”章节手动安装并校验；应用不会自动下载。题库、练习和项目功能仍可使用。",
            }
        if error.code == "OCR_MODEL_INVALID":
            return {
                "ready": False,
                "state": "invalid",
                "message": "OCR 模型文件校验未通过。请按 README“本地 OCR 模型”章节重新校验；其他功能仍可使用。",
            }
        return {
            "ready": False,
            "state": "unavailable",
            "message": "OCR 运行环境暂不可用；题库、练习和项目功能仍可使用。",
        }
    except metadata.PackageNotFoundError:
        return {
            "ready": False,
            "state": "runtime_missing",
            "message": "OCR 运行依赖尚未安装。请再次运行本机安装脚本；题库、练习和项目功能仍可使用。",
        }
    except Exception:
        return {
            "ready": False,
            "state": "unavailable",
            "message": "暂时无法检查 OCR 模型；题库、练习和项目功能仍可使用。",
        }

    if (
        rapidocr_version != str(config.get("OCR_RAPIDOCR_VERSION", ""))
        or onnxruntime_version != str(config.get("OCR_ONNXRUNTIME_VERSION", ""))
    ):
        return {
            "ready": False,
            "state": "runtime_mismatch",
            "message": "OCR 运行依赖版本与模型要求不匹配。",
        }
    return {"ready": True, "state": "ready", "message": "OCR 模型文件校验通过。"}


def get_system_status(app: Flask) -> dict:
    engine: Engine = app.extensions["sqlalchemy_engine"]
    configured_data_dir = Path(app.config["APP_DATA_DIR"]).expanduser().resolve()
    default_data_dir = Path(user_data_dir("AgentInterviewAssistant", "Local")).resolve()
    provider = public_provider_settings(app)

    result = {
        "application": "agent-interview-assistant",
        "backend": {"ready": True, "state": "ready"},
        "python": {
            "version": platform.python_version(),
            "supported": platform.python_version_tuple()[:2] == ("3", "12"),
        },
        "database": _database_status(engine),
        "ocr": _ocr_status(app.config),
        "llm": {"configured": bool(provider.get("configured"))},
        "storage": {
            "configured": True,
            "location": "default" if configured_data_dir == default_data_dir else "custom",
        },
    }
    instance_id = str(app.config.get("APP_INSTANCE_ID") or "")
    if instance_id:
        result["launcher"] = {"instance_id": instance_id}
    return result
