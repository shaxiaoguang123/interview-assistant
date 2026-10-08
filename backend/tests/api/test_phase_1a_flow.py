from app import create_app


def test_phase_1a_question_to_review_flow(app, client):
    topic_response = client.post(
        "/api/v1/topics", json={"slug": "agent-tools", "name": "Agent 工具"}
    )
    assert topic_response.status_code == 201
    topic = topic_response.get_json()
    tag_response = client.post("/api/v1/tags", json={"name": "MCP"})
    assert tag_response.status_code == 201
    tag = tag_response.get_json()

    created = client.post(
        "/api/v1/questions",
        json={
            "text": "MCP 通信协议如何支持 Agent 工具调用？",
            "topic_ids": [topic["id"]],
            "tag_ids": [tag["id"]],
        },
    )
    assert created.status_code == 201
    question = created.get_json()

    search = client.get("/api/v1/questions", query_string={"q": "MCP 通信协议"})
    assert [row["id"] for row in search.get_json()] == [question["id"]]

    state = client.patch(
        f"/api/v1/questions/{question['id']}/state",
        json={"is_favorite": True, "is_wrong": True},
    )
    assert state.status_code == 200
    filtered = client.get(
        "/api/v1/questions",
        query_string={
            "q": "MCP",
            "topic_ids": str(topic["id"]),
            "tag_ids": str(tag["id"]),
            "is_favorite": "true",
            "is_wrong": "true",
        },
    )
    assert [row["id"] for row in filtered.get_json()] == [question["id"]]

    random_session = client.post(
        "/api/v1/practice-sessions",
        json={"mode": "random", "filters": {}, "limit": 5, "selection_seed": 5},
    )
    topic_session = client.post(
        "/api/v1/practice-sessions",
        json={"mode": "topic", "filters": {"topic_ids": [topic["id"]]}, "limit": 5},
    )
    tag_session = client.post(
        "/api/v1/practice-sessions",
        json={"mode": "tag", "filters": {"tag_ids": [tag["id"]]}, "limit": 5},
    )
    assert random_session.status_code == topic_session.status_code == tag_session.status_code == 201
    random_item = random_session.get_json()["items"][0]
    assert topic_session.get_json()["items"][0]["question_id"] == question["id"]
    assert tag_session.get_json()["items"][0]["question_id"] == question["id"]

    reviewed = client.post(
        f"/api/v1/session-items/{random_item['id']}/review",
        json={"review_rating": "basic"},
    )
    assert reviewed.status_code == 201
    history = client.get(f"/api/v1/questions/{question['id']}/practice-reviews")
    assert history.status_code == 200
    assert len(history.get_json()) == 1
    assert history.get_json()[0]["review_rating"] == "basic"

    archived = client.post(f"/api/v1/questions/{question['id']}/archive")
    assert archived.status_code == 200
    assert client.get("/api/v1/questions").get_json() == []
    assert client.get("/api/v1/questions", query_string={"q": "MCP"}).get_json() == []
    old_session = client.get(
        f"/api/v1/practice-sessions/{random_session.get_json()['id']}"
    ).get_json()
    assert old_session["items"][0]["question"]["archived_at"] is not None
    empty_session = client.post(
        "/api/v1/practice-sessions",
        json={"mode": "random", "filters": {}, "limit": 5, "selection_seed": 5},
    ).get_json()
    assert empty_session["items"] == []

    database_url = app.config["DATABASE_URL"]
    data_dir = app.config["APP_DATA_DIR"]
    app.extensions["sqlalchemy_engine"].dispose()
    reopened = create_app(
        {
            "TESTING": True,
            "APP_DATA_DIR": data_dir,
            "DATABASE_URL": database_url,
            "SEED_TOPICS_ON_STARTUP": False,
        }
    )
    with reopened.test_client() as reopened_client:
        assert reopened_client.get(f"/api/v1/questions/{question['id']}").get_json()["archived_at"]
        persisted_history = reopened_client.get(
            f"/api/v1/questions/{question['id']}/practice-reviews"
        ).get_json()
        assert len(persisted_history) == 1
        assert persisted_history[0]["review_rating"] == "basic"
    reopened.extensions["sqlalchemy_engine"].dispose()
