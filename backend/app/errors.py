from __future__ import annotations

import logging
from typing import Any

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException
from sqlalchemy.exc import SQLAlchemyError


logger = logging.getLogger(__name__)


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        fields: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.fields = fields or {}


def _error_response(
    status_code: int,
    code: str,
    message: str,
    fields: dict[str, Any] | None = None,
):
    return jsonify({"error": {"code": code, "message": message, "fields": fields or {}}}), status_code


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(ApiError)
    def handle_api_error(error: ApiError):
        return _error_response(error.status_code, error.code, error.message, error.fields)

    @app.errorhandler(HTTPException)
    def handle_http_error(error: HTTPException):
        status_code = error.code or 500
        code_by_status = {
            400: "VALIDATION_ERROR",
            404: "NOT_FOUND",
            405: "METHOD_NOT_ALLOWED",
            409: "CONFLICT",
            413: "PAYLOAD_TOO_LARGE",
        }
        if status_code >= 500:
            return _error_response(500, "INTERNAL_ERROR", "Internal server error")
        code = code_by_status.get(status_code, "HTTP_ERROR")
        return _error_response(status_code, code, error.name)

    @app.errorhandler(SQLAlchemyError)
    def handle_database_error(error: SQLAlchemyError):
        logger.error("Database request failed (error_type=%s)", type(error).__name__)
        return _error_response(500, "INTERNAL_ERROR", "Internal server error")

    @app.errorhandler(Exception)
    def handle_unexpected_error(error: Exception):
        logger.error("Unhandled API error (error_type=%s)", type(error).__name__)
        return _error_response(500, "INTERNAL_ERROR", "Internal server error")
