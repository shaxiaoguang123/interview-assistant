from app.errors import ApiError


def _assert_error(response, status_code, code):
    assert response.status_code == status_code
    body = response.get_json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == code
    assert isinstance(body["error"]["message"], str)
    assert isinstance(body["error"].get("fields", {}), dict)
    return body["error"]


def test_question_validation_uses_global_error_envelope(client):
    response = client.post("/api/v1/questions", json={"text": "   "})

    error = _assert_error(response, 400, "VALIDATION_ERROR")
    assert "text" in error["fields"]


def test_duplicate_review_uses_global_conflict_envelope(client):
    question = client.post(
        "/api/v1/questions", json={"text": "Error envelope review question"}
    ).get_json()
    session = client.post(
        "/api/v1/practice-sessions",
        json={"mode": "random", "filters": {}, "limit": 1, "selection_seed": 5},
    ).get_json()
    item = session["items"][0]
    first = client.post(
        f"/api/v1/session-items/{item['id']}/review", json={"review_rating": "basic"}
    )
    assert first.status_code == 201

    duplicate = client.post(
        f"/api/v1/session-items/{item['id']}/review", json={"review_rating": "vague"}
    )

    assert question["id"] == item["question_id"]
    _assert_error(duplicate, 409, "CONFLICT")


def test_unknown_api_route_uses_global_not_found_envelope(client):
    response = client.get("/api/v1/not-registered")

    _assert_error(response, 404, "NOT_FOUND")


def test_api_error_class_preserves_fields(app):
    @app.get("/__tests__/validation-error")
    def validation_error():
        raise ApiError(400, "VALIDATION_ERROR", "Invalid request", {"text": "Required"})

    with app.test_client() as client:
        response = client.get("/__tests__/validation-error")

    error = _assert_error(response, 400, "VALIDATION_ERROR")
    assert error["fields"] == {"text": "Required"}


def test_production_static_files_and_spa_fallback(app, tmp_path):
    dist = tmp_path / "frontend-dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (dist / "index.html").write_text("<html><body>Agent Assistant UI</body></html>")
    (assets / "app.js").write_text("window.ready = true;")
    database_url = app.config["DATABASE_URL"]
    data_dir = app.config["APP_DATA_DIR"]
    app.extensions["sqlalchemy_engine"].dispose()
    from app import create_app

    production_app = create_app(
        {
            "TESTING": True,
            "APP_DATA_DIR": data_dir,
            "DATABASE_URL": database_url,
            "SEED_TOPICS_ON_STARTUP": False,
            "FRONTEND_DIST_DIR": dist,
        }
    )
    with production_app.test_client() as client:
        root = client.get("/")
        asset = client.get("/assets/app.js")
        route = client.get("/questions/42")
        api_404 = client.get("/api/v1/not-registered")

    assert root.status_code == 200
    assert b"Agent Assistant UI" in root.data
    assert asset.status_code == 200
    assert b"window.ready = true" in asset.data
    assert route.status_code == 200
    assert b"Agent Assistant UI" in route.data
    _assert_error(api_404, 404, "NOT_FOUND")
    production_app.extensions["sqlalchemy_engine"].dispose()
