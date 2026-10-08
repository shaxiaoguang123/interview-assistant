from __future__ import annotations

from urllib.parse import urlsplit

from flask import Flask, current_app, request

from .errors import ApiError


LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _hostname(value: str) -> str | None:
    try:
        return urlsplit(f"//{value}").hostname
    except ValueError:
        return None


def validate_local_request() -> None:
    host = request.host
    host_name = _hostname(host)
    if host_name is None or host_name.lower() not in LOOPBACK_HOSTS:
        raise ApiError(
            400,
            "VALIDATION_ERROR",
            "Request Host must be local",
            {"host": "Only localhost and loopback addresses are allowed"},
        )

    origin = request.headers.get("Origin")
    if origin is None:
        return

    origin = origin.rstrip("/")
    origin_parts = urlsplit(origin)
    origin_host = origin_parts.hostname
    if origin_parts.scheme not in {"http", "https"} or origin_host is None or origin_host.lower() not in LOOPBACK_HOSTS:
        raise ApiError(
            400,
            "VALIDATION_ERROR",
            "Request Origin must be local",
            {"origin": "Only configured local origins are allowed"},
        )

    same_origin = origin == request.host_url.rstrip("/")
    allowed_origins = {str(item).rstrip("/") for item in current_app.config.get("ALLOWED_ORIGINS", [])}
    if not same_origin and origin not in allowed_origins:
        raise ApiError(
            400,
            "VALIDATION_ERROR",
            "Request Origin is not allowed",
            {"origin": "Origin is not in ALLOWED_ORIGINS"},
        )


def register_local_security(app: Flask) -> None:
    app.before_request(validate_local_request)
