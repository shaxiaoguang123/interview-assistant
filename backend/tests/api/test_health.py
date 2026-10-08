def test_health_returns_ok(client):
    assert client is not None, "missing feature: Flask app factory"
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_404_uses_error_envelope(client):
    assert client is not None, "missing feature: Flask app factory"
    response = client.get("/api/v1/not-a-route")

    assert response.status_code == 404
    payload = response.get_json()
    assert set(payload) == {"error"}
    assert payload["error"]["code"] == "NOT_FOUND"
    assert isinstance(payload["error"]["message"], str)
