def assert_error_envelope(response, status_code, error_code):
    assert response.status_code == status_code
    payload = response.get_json()
    assert set(payload) == {"error"}
    error = payload["error"]
    assert error["code"] == error_code
    assert isinstance(error["message"], str)
    assert "fields" not in error or isinstance(error["fields"], dict)
    return error


def test_409_413_and_500_use_error_envelope(app, client):
    errors_module_path = app.root_path
    assert errors_module_path, "test app must be created before exercising error handlers"
    from app.errors import ApiError

    def conflict():
        raise ApiError(409, "CONFLICT", "Duplicate operation", {"item_id": "already reviewed"})

    def oversized_body():
        from flask import request

        return request.get_data()

    def internal_error():
        raise RuntimeError("private diagnostic text")

    app.add_url_rule("/__tests__/conflict", view_func=conflict)
    app.add_url_rule("/__tests__/payload", view_func=oversized_body, methods=["POST"])
    app.add_url_rule("/__tests__/internal", view_func=internal_error)

    conflict_response = client.get("/__tests__/conflict")
    conflict_error = assert_error_envelope(conflict_response, 409, "CONFLICT")
    assert conflict_error["fields"] == {"item_id": "already reviewed"}

    app.config["MAX_CONTENT_LENGTH"] = 1
    payload_response = client.post("/__tests__/payload", data=b"too large")
    assert_error_envelope(payload_response, 413, "PAYLOAD_TOO_LARGE")

    internal_response = client.get("/__tests__/internal")
    internal_error_body = assert_error_envelope(internal_response, 500, "INTERNAL_ERROR")
    assert "private diagnostic text" not in internal_error_body["message"]
