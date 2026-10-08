from datetime import datetime, timezone

from app.models.practice import PracticeReview, PracticeSession, SessionItem
from app.models.question import Question, QuestionState
from app.services.questions import prepare_question_text


def _add_question(session, text):
    raw, normalized, digest = prepare_question_text(text)
    question = Question(
        text=raw,
        normalized_text=normalized,
        search_text=normalized,
        normalized_hash=digest,
        state=QuestionState(is_favorite=False, is_wrong=False),
    )
    session.add(question)
    session.flush()
    return question


def _add_session(db_session, questions, *, first_status="shown"):
    practice_session = PracticeSession(mode="random", filters_json={}, selector_version="v1")
    db_session.add(practice_session)
    db_session.flush()
    items = []
    for ordinal, question in enumerate(questions, start=1):
        item = SessionItem(
            session_id=practice_session.id,
            question_id=question.id,
            ordinal=ordinal,
            status=first_status if ordinal == 1 else "shown",
            completed_at=datetime.now(timezone.utc) if first_status != "shown" and ordinal == 1 else None,
        )
        db_session.add(item)
        items.append(item)
    db_session.commit()
    return practice_session, items


def _create_question(client, text):
    response = client.post("/api/v1/questions", json={"text": text})
    assert response.status_code == 201
    return response.get_json()


def _create_session_item(client, question_text="Practice review question"):
    question = _create_question(client, question_text)
    session_response = client.post(
        "/api/v1/practice-sessions",
        json={"mode": "random", "filters": {}, "limit": 100, "selection_seed": 8},
    )
    assert session_response.status_code == 201
    session = session_response.get_json()
    item = next(item for item in session["items"] if item["question_id"] == question["id"])
    assert item["question_id"] == question["id"]
    return question, session, item


def _post_review(client, session_item_id, rating):
    response = client.post(
        f"/api/v1/session-items/{session_item_id}/review", json={"review_rating": rating}
    )
    assert response.status_code == 201
    return response.get_json()


def test_each_review_rating_is_accepted(client):
    for index, rating in enumerate(("dont_know", "vague", "basic", "proficient")):
        _, _, item = _create_session_item(client, f"Review rating question {index}")
        review = _post_review(client, item["id"], rating)
        assert review["review_rating"] == rating


def test_practice_completes_without_answer(client, db_session):
    _, session, item = _create_session_item(client, "No answer text needed")

    review = _post_review(client, item["id"], "basic")
    assert review["session_item_id"] == item["id"]
    db_session.expire_all()
    assert db_session.query(PracticeReview).filter_by(session_item_id=item["id"]).count() == 1
    assert db_session.get(PracticeSession, session["id"]).completed_at is not None


def test_invalid_rating_returns_400(client):
    _, _, item = _create_session_item(client, "Invalid rating question")

    response = client.post(
        f"/api/v1/session-items/{item['id']}/review", json={"review_rating": "excellent"}
    )

    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "VALIDATION_ERROR"
    assert "review_rating" in response.get_json()["error"]["fields"]


def test_missing_review_returns_404(client):
    response = client.patch("/api/v1/practice-reviews/999999", json={"review_rating": "basic"})

    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "NOT_FOUND"


def test_duplicate_review_returns_409(client):
    _, _, item = _create_session_item(client, "Duplicate review question")
    _post_review(client, item["id"], "basic")

    duplicate = client.post(
        f"/api/v1/session-items/{item['id']}/review", json={"review_rating": "vague"}
    )

    assert duplicate.status_code == 409
    assert duplicate.get_json()["error"]["code"] == "CONFLICT"


def test_skipped_item_cannot_be_reviewed(client):
    _, _, item = _create_session_item(client, "Skipped review question")
    skipped = client.post(f"/api/v1/session-items/{item['id']}/skip")
    assert skipped.status_code == 200

    response = client.post(
        f"/api/v1/session-items/{item['id']}/review", json={"review_rating": "basic"}
    )

    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "CONFLICT"


def test_completed_item_cannot_be_reviewed_again_or_skipped(client):
    _, _, item = _create_session_item(client, "Completed review question")
    _post_review(client, item["id"], "basic")

    duplicate = client.post(
        f"/api/v1/session-items/{item['id']}/review", json={"review_rating": "vague"}
    )
    skip = client.post(f"/api/v1/session-items/{item['id']}/skip")

    assert duplicate.status_code == 409
    assert skip.status_code == 409


def test_last_review_completes_session(client, db_session):
    first = _create_question(client, "First review in session")
    second = _create_question(client, "Last review in session")
    session, items = _add_session(
        db_session,
        [db_session.get(Question, first["id"]), db_session.get(Question, second["id"])],
    )

    first_review = client.post(
        f"/api/v1/session-items/{items[0].id}/review", json={"review_rating": "vague"}
    )
    assert first_review.status_code == 201
    db_session.expire_all()
    assert db_session.get(PracticeSession, session.id).completed_at is None

    last_review = client.post(
        f"/api/v1/session-items/{items[1].id}/review", json={"review_rating": "proficient"}
    )
    assert last_review.status_code == 201
    db_session.expire_all()
    assert db_session.get(PracticeSession, session.id).completed_at is not None


def test_review_with_shown_item_keeps_session_incomplete(client, db_session):
    first = _create_question(client, "Completed while another item remains")
    second = _create_question(client, "Still shown after the first review")
    session, items = _add_session(
        db_session,
        [db_session.get(Question, first["id"]), db_session.get(Question, second["id"])],
    )

    response = client.post(
        f"/api/v1/session-items/{items[0].id}/review", json={"review_rating": "basic"}
    )

    assert response.status_code == 201
    db_session.expire_all()
    assert db_session.get(PracticeSession, session.id).completed_at is None
    assert db_session.get(SessionItem, items[1].id).status == "shown"


def test_archived_question_in_existing_session_can_be_reviewed(client, db_session):
    question = _create_question(client, "Archive then review this question")
    session, items = _add_session(db_session, [db_session.get(Question, question["id"])])
    archived = client.post(f"/api/v1/questions/{question['id']}/archive")
    assert archived.status_code == 200

    response = client.post(
        f"/api/v1/session-items/{items[0].id}/review", json={"review_rating": "basic"}
    )

    assert response.status_code == 201
    assert response.get_json()["question_id"] == question["id"]
    db_session.expire_all()
    assert db_session.get(PracticeSession, session.id).completed_at is not None


def test_patch_changes_rating_without_new_review(client, db_session):
    question, _, item = _create_session_item(client, "Correct a past rating")
    created = _post_review(client, item["id"], "vague")
    original_created_at = created["created_at"]
    original_reviewed_at = created["reviewed_at"]
    review_id = created["id"]

    patched = client.patch(
        f"/api/v1/practice-reviews/{review_id}", json={"review_rating": "basic"}
    )

    assert patched.status_code == 200
    assert patched.get_json()["review_rating"] == "basic"
    assert patched.get_json()["created_at"] == original_created_at
    assert patched.get_json()["reviewed_at"] == original_reviewed_at
    db_session.expire_all()
    assert db_session.query(PracticeReview).filter_by(session_item_id=item["id"]).count() == 1
    assert client.get(f"/api/v1/questions/{question['id']}/practice-reviews").status_code == 200


def test_patch_rejects_immutable_fields(client):
    _, _, item = _create_session_item(client, "Reject immutable Review updates")
    review = _post_review(client, item["id"], "vague")

    response = client.patch(
        f"/api/v1/practice-reviews/{review['id']}",
        json={"review_rating": "basic", "question_id": 999},
    )

    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "VALIDATION_ERROR"


def test_patch_does_not_change_question_session_or_reviewed_time(client):
    question, session, item = _create_session_item(client, "Immutable Review provenance")
    review = _post_review(client, item["id"], "vague")

    response = client.patch(
        f"/api/v1/practice-reviews/{review['id']}", json={"review_rating": "proficient"}
    )

    assert response.status_code == 200
    changed = response.get_json()
    assert changed["question_id"] == question["id"]
    assert changed["session_item_id"] == item["id"]
    assert changed["reviewed_at"] == review["reviewed_at"]
    assert changed["created_at"] == review["created_at"]
    assert changed["updated_at"] != review["updated_at"]


def test_review_history_returns_updated_rating_for_archived_question(client):
    question, _, item = _create_session_item(client, "Archived Review history")
    review = _post_review(client, item["id"], "vague")
    assert client.post(f"/api/v1/questions/{question['id']}/archive").status_code == 200

    patched = client.patch(
        f"/api/v1/practice-reviews/{review['id']}", json={"review_rating": "basic"}
    )
    history = client.get(f"/api/v1/questions/{question['id']}/practice-reviews")

    assert patched.status_code == 200
    assert history.status_code == 200
    assert len(history.get_json()) == 1
    assert history.get_json()[0]["review_rating"] == "basic"
