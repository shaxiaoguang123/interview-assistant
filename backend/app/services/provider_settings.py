"""Persist local LLM settings without exposing or backing up credentials."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile

from flask import Flask


PUBLIC_KEYS = {"base_url": "LLM_BASE_URL", "model": "LLM_MODEL"}
ENV_NAMES = {"base_url": "LLM_BASE_URL", "model": "LLM_MODEL", "api_key": "LLM_API_KEY"}


def _environment_value(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None


def _paths(app: Flask) -> tuple[Path, Path, Path]:
    root = Path(app.config["APP_DATA_DIR"]).expanduser().resolve()
    directory = root / "provider"
    if directory.is_symlink():
        raise RuntimeError("Provider settings directory cannot be a symlink")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        directory.chmod(0o700)
    except OSError:
        pass
    return directory, directory / "settings.json", directory / "api-key"


def _read_settings(settings_path: Path) -> dict[str, str]:
    if not settings_path.is_file():
        return {}
    try:
        value = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    if not isinstance(value, dict):
        return {}
    return {key: value[key] for key in PUBLIC_KEYS if isinstance(value.get(key), str)}


def load_local_provider_settings(app: Flask, *, explicitly_configured: set[str] | None = None) -> None:
    """Resolve each setting in order: process environment, explicit app config, local file."""
    directory, settings_path, key_path = _paths(app)
    for path in (settings_path, key_path):
        if path.is_symlink():
            raise RuntimeError("Provider settings files cannot be symlinks")
        if path.is_file():
            try:
                path.chmod(0o600)
            except OSError:
                pass
    settings = _read_settings(settings_path)
    explicit = explicitly_configured or set()
    for public_name, config_name in PUBLIC_KEYS.items():
        env_value = _environment_value(ENV_NAMES[public_name])
        if env_value is not None:
            app.config[config_name] = env_value
            continue
        if config_name in explicit:
            continue
        app.config[config_name] = settings.get(public_name, "")
    env_key = _environment_value("LLM_API_KEY")
    if env_key is not None:
        app.config["LLM_API_KEY"] = env_key
    elif "LLM_API_KEY" not in explicit:
        app.config["LLM_API_KEY"] = key_path.read_text(encoding="utf-8") if key_path.is_file() else ""
    app.extensions["provider_settings_paths"] = (directory, settings_path, key_path)


def public_provider_settings(app: Flask) -> dict:
    directory, settings_path, key_path = app.extensions.get("provider_settings_paths") or _paths(app)
    sources = {
        name: "environment" if _environment_value(config_name) is not None else (
            "local" if name in _read_settings(settings_path) else "not_configured"
        )
        for name, config_name in PUBLIC_KEYS.items()
    }
    key_source = "environment" if _environment_value("LLM_API_KEY") is not None else (
        "local" if key_path.is_file() else "not_configured"
    )
    key_present = bool(app.config.get("LLM_API_KEY"))
    scope = "environment" if "environment" in (*sources.values(), key_source) else (
        "local" if "local" in (*sources.values(), key_source) else "not_configured"
    )
    return {
        "base_url": app.config.get("LLM_BASE_URL", ""),
        "model": app.config.get("LLM_MODEL", ""),
        "has_api_key": key_present,
        "configured": bool(
            app.config.get("LLM_PROVIDER_FACTORY")
            or app.config.get("LLM_BASE_URL") and key_present and app.config.get("LLM_MODEL")
        ),
        "configuration_scope": scope,
        "base_url_source": sources["base_url"],
        "model_source": sources["model"],
        "api_key_source": key_source,
        "editable": {
            "base_url": sources["base_url"] != "environment",
            "model": sources["model"] != "environment",
            "api_key": key_source != "environment",
        },
        "data_dir": str(Path(app.config["APP_DATA_DIR"]).expanduser().resolve()),
    }


def _atomic_private_write(directory: Path, destination: Path, payload: bytes) -> None:
    fd, temporary_name = tempfile.mkstemp(prefix=".provider-", dir=directory)
    temporary = Path(temporary_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
        try:
            destination.chmod(0o600)
        except OSError:
            pass
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def save_provider_settings(app: Flask, payload: dict) -> dict:
    directory, settings_path, key_path = app.extensions["provider_settings_paths"]
    settings = _read_settings(settings_path)
    effective = {}
    for public_name, config_name in PUBLIC_KEYS.items():
        if public_name not in payload:
            continue
        env_name = ENV_NAMES[public_name]
        if _environment_value(env_name) is not None:
            raise ValueError(f"{public_name} is controlled by the {env_name} environment variable")
        value = payload[public_name]
        settings[public_name] = value
        effective[config_name] = value

    if "api_key" in payload or payload.get("clear_api_key"):
        if _environment_value("LLM_API_KEY") is not None:
            raise ValueError("api_key is controlled by the LLM_API_KEY environment variable")
        if payload.get("clear_api_key") is True:
            key_path.unlink(missing_ok=True)
            effective["LLM_API_KEY"] = ""
        elif "api_key" in payload:
            key = payload["api_key"]
            _atomic_private_write(directory, key_path, key.encode("utf-8"))
            effective["LLM_API_KEY"] = key

    _atomic_private_write(
        directory,
        settings_path,
        json.dumps(settings, ensure_ascii=False, indent=2).encode("utf-8"),
    )
    app.config.update(effective)
    return public_provider_settings(app)
