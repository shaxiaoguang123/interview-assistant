from app import create_app
from app.models.practice import PracticeReview, SessionItem


def _create_question(client, text):
    response = client.post("/api/v1/questions", json={"text": text})
    assert response.status_code == 201
    return response.get_json()


def _create_session(client, *, limit=10, seed=123, mode="random", filters=None):
    response = client.post(
        "/api/v1/practice-sessions",
        json={
            "mode": mode,
            "filters": filters or {},
            "limit": limit,
            "selection_seed": seed if mode == "random" else None,
        },
    )
    assert response.status_code == 201
    return response


def test_create_and_read_session(client):
    first = _create_question(client, "First Agent question")
    second = _create_question(client, "Second Agent question")

    created = _create_session(client, limit=2)

    assert created.status_code == 201
    session = created.get_json()
    assert session["selector_version"] == "v1"
    assert session["selection_seed"] == 123
    assert [item["ordinal"] for item in session["items"]] == [1, 2]
    assert {item["question_id"] for item in session["items"]} == {first["id"], second["id"]}
    assert all(item["status"] == "shown" for item in session["items"])

    read = client.get(f"/api/v1/practice-sessions/{session['id']}")
    assert read.status_code == 200
    assert [item["id"] for item in read.get_json()["items"]] == [
        item["id"] for item in session["items"]
    ]


def test_open_session_can_resume_after_app_restart(app, client):
    _create_question(client, "Resume session question one")
    _create_question(client, "Resume session question two")
    created = _create_session(client, limit=2)
    assert created.status_code == 201
    session_id = created.get_json()["id"]
    expected_ids = [item["id"] for item in created.get_json()["items"]]
    database_url = app.config["DATABASE_URL"]
    data_dir = app.config["APP_DATA_DIR"]
    app.extensions["sqlalchemy_engine"].dispose()

    reopened_app = create_app(
        {
            "TESTING": True,
            "APP_DATA_DIR": data_dir,
            "DATABASE_URL": database_url,
            "SEED_TOPICS_ON_STARTUP": False,
        }
    )
    with reopened_app.test_client() as reopened_client:
        resumed = reopened_client.get(f"/api/v1/practice-sessions/{session_id}")
    assert resumed.status_code == 200
    assert resumed.get_json()["completed_at"] is None
    assert [item["id"] for item in resumed.get_json()["items"]] == expected_ids
    reopened_app.extensions["sqlalchemy_engine"].dispose()


def test_created_order_survives_question_edit(client):
    question_one = _create_question(client, "Question one")
    question_two = _create_question(client, "Question two")
    created = _create_session(client, limit=2)
    session = created.get_json()
    original_order = [item["question_id"] for item in session["items"]]

    changed = client.patch(
        f"/api/v1/questions/{question_one['id']}",
        json={"text": "Question one edited after selection"},
    )
    assert changed.status_code == 200
    reread = client.get(f"/api/v1/practice-sessions/{session['id']}").get_json()

    assert [item["question_id"] for item in reread["items"]] == original_order
    assert set(original_order) == {question_one["id"], question_two["id"]}


def test_archived_question_remains_in_existing_session_and_not_new_session(client):
    question_one = _create_question(client, "Question to archive")
    question_two = _create_question(client, "Question remains active")
    created = _create_session(client, limit=2)
    session_id = created.get_json()["id"]

    archived = client.post(f"/api/v1/questions/{question_one['id']}/archive")
    assert archived.status_code == 200
    old_session = client.get(f"/api/v1/practice-sessions/{session_id}").get_json()
    new_session = _create_session(client, limit=10).get_json()

    assert question_one["id"] in [item["question_id"] for item in old_session["items"]]
    assert question_one["id"] not in [item["question_id"] for item in new_session["items"]]
    assert [item["question_id"] for item in new_session["items"]] == [question_two["id"]]


def test_skip_marks_item_without_review(client, db_session):
    _create_question(client, "Skip without Review")
    created = _create_session(client, limit=1)
    item = created.get_json()["items"][0]

    skipped = client.post(f"/api/v1/session-items/{item['id']}/skip")

    assert skipped.status_code == 200
    assert skipped.get_json()["item"]["status"] == "skipped"
    db_session.expire_all()
    assert db_session.query(PracticeReview).filter_by(session_item_id=item["id"]).count() == 0


def test_last_skip_completes_session(client):
    _create_question(client, "Skip first item")
    _create_question(client, "Skip final item")
    session = _create_session(client, limit=2).get_json()

    first_skip = client.post(f"/api/v1/session-items/{session['items'][0]['id']}/skip")
    assert first_skip.status_code == 200
    assert first_skip.get_json()["session"]["completed_at"] is None

    final_skip = client.post(f"/api/v1/session-items/{session['items'][1]['id']}/skip")
    assert final_skip.status_code == 200
    assert final_skip.get_json()["session"]["completed_at"] is not None


def test_session_with_shown_item_stays_incomplete(client):
    _create_question(client, "First incomplete question")
    _create_question(client, "Second incomplete question")
    session = _create_session(client, limit=2).get_json()

    response = client.post(f"/api/v1/session-items/{session['items'][0]['id']}/skip")

    assert response.status_code == 200
    assert response.get_json()["session"]["completed_at"] is None
    assert response.get_json()["session"]["items"][1]["status"] == "shown"


def test_skipped_item_cannot_be_skipped_again(client):
    _create_question(client, "Repeated skip question")
    item = _create_session(client, limit=1).get_json()["items"][0]
    assert client.post(f"/api/v1/session-items/{item['id']}/skip").status_code == 200

    repeated = client.post(f"/api/v1/session-items/{item['id']}/skip")

    assert repeated.status_code == 409
    assert repeated.get_json()["error"]["code"] == "CONFLICT"
