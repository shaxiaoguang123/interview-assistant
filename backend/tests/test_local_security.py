def assert_error_envelope(response, status_code, error_code):
    assert response.status_code == status_code
    payload = response.get_json()
    assert set(payload) == {"error"}
    error = payload["error"]
    assert error["code"] == error_code
    assert isinstance(error["message"], str)
    assert "fields" not in error or isinstance(error["fields"], dict)
    return error


def test_non_local_host_is_rejected_with_error_envelope(client):
    assert client is not None, "missing feature: Flask app factory"
    response = client.get("/api/v1/health", base_url="http://attacker.example")

    error = assert_error_envelope(response, 400, "VALIDATION_ERROR")
    assert "host" in error.get("fields", {})


def test_no_origin_localhost_is_allowed(client):
    assert client is not None, "missing feature: Flask app factory"
    response = client.get("/api/v1/health", base_url="http://localhost")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_same_origin_local_request_is_allowed(client):
    assert client is not None, "missing feature: Flask app factory"
    response = client.get(
        "/api/v1/health",
        base_url="http://localhost:5000",
        headers={"Origin": "http://localhost:5000"},
    )

    assert response.status_code == 200


def test_configured_local_origin_is_allowed(client):
    assert client is not None, "missing feature: Flask app factory"
    response = client.get(
        "/api/v1/health",
        base_url="http://127.0.0.1:5000",
        headers={"Origin": "http://localhost:5173"},
    )

    assert response.status_code == 200


def test_ipv6_loopback_host_is_allowed(client):
    assert client is not None, "missing feature: Flask app factory"
    response = client.get("/api/v1/health", base_url="http://[::1]")

    assert response.status_code == 200


def test_external_origin_is_rejected_with_error_envelope(client):
    assert client is not None, "missing feature: Flask app factory"
    response = client.get(
        "/api/v1/health",
        base_url="http://localhost:5000",
        headers={"Origin": "https://attacker.example"},
    )

    error = assert_error_envelope(response, 400, "VALIDATION_ERROR")
    assert "origin" in error.get("fields", {})
