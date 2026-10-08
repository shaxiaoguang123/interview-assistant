from importlib import import_module, util
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.errors import ApiError
from app.models.question import Question, QuestionState, QuestionTag, QuestionTopic
from app.models.taxonomy import Tag, Topic
from app.services.questions import prepare_question_text


def _create_selector():
    module_path = Path(__file__).resolve().parents[2] / "app" / "services" / "practice_selector.py"
    assert module_path.is_file(), "missing feature: rule-based practice selector"
    assert util.find_spec("app.services.practice_selector") is not None
    return import_module("app.services.practice_selector").create_practice_session


def _add_question(session, text: str, *, topic: Topic | None = None, tag: Tag | None = None):
    raw, normalized, digest = prepare_question_text(text)
    question = Question(
        text=raw,
        normalized_text=normalized,
        search_text=normalized,
        normalized_hash=digest,
        archived_at=None,
        state=QuestionState(is_favorite=False, is_wrong=False),
    )
    session.add(question)
    session.flush()
    if topic is not None:
        session.add(QuestionTopic(question_id=question.id, topic_id=topic.id))
    if tag is not None:
        session.add(QuestionTag(question_id=question.id, tag_id=tag.id))
    session.commit()
    return question


def test_same_seed_replays_same_random_order(db_session):
    create_session = _create_selector()
    questions = [_add_question(db_session, f"Agent question {index}") for index in range(12)]

    first = create_session(db_session, "random", {}, 12, selection_seed=123456)
    second = create_session(db_session, "random", {}, 12, selection_seed=123456)

    first_ids = [item.question_id for item in first.items]
    second_ids = [item.question_id for item in second.items]
    assert first.selector_version == "v1"
    assert first.selection_seed == 123456
    assert first_ids == second_ids
    assert set(first_ids) == {question.id for question in questions}
    assert [item.ordinal for item in first.items] == list(range(1, 13))


def test_different_seed_can_change_random_order(db_session):
    create_session = _create_selector()
    for index in range(20):
        _add_question(db_session, f"Question about Agent memory {index}")

    first = create_session(db_session, "random", {}, 20, selection_seed=1)
    second = create_session(db_session, "random", {}, 20, selection_seed=2)

    assert [item.question_id for item in first.items] != [item.question_id for item in second.items]


def test_random_mode_generates_seed(db_session):
    create_session = _create_selector()
    _add_question(db_session, "One random question")

    practice_session = create_session(db_session, "random", {}, 10)

    assert 0 <= practice_session.selection_seed <= (2**32 - 1)


def test_topic_and_tag_filters(db_session):
    create_session = _create_selector()
    topic = Topic(track_key="agent_development", slug="practice-topic", name="Practice Topic")
    tag = Tag(name="Practice Tag")
    db_session.add_all([topic, tag])
    db_session.commit()
    expected = _add_question(db_session, "Question with topic and tag", topic=topic, tag=tag)
    _add_question(db_session, "Question without topic or tag")

    by_topic = create_session(db_session, "topic", {"topic_ids": [topic.id]}, 10)
    by_tag = create_session(db_session, "tag", {"tag_ids": [tag.id]}, 10)

    assert [item.question_id for item in by_topic.items] == [expected.id]
    assert [item.question_id for item in by_tag.items] == [expected.id]
    assert by_topic.selection_seed is None
    assert by_tag.selection_seed is None


def test_invalid_selector_mode_is_rejected(db_session):
    create_session = _create_selector()

    with pytest.raises(ApiError) as error:
        create_session(db_session, "llm", {}, 10)

    assert error.value.status_code == 400
    assert error.value.code == "VALIDATION_ERROR"
    assert "mode" in error.value.fields


def test_topic_selector_rejects_unknown_topic(db_session):
    create_session = _create_selector()

    with pytest.raises(ApiError) as error:
        create_session(db_session, "topic", {"topic_ids": [999999]}, 10)

    assert error.value.status_code == 400
    assert "topic_ids" in error.value.fields


def test_topic_selector_rejects_inactive_topic(db_session):
    create_session = _create_selector()
    topic = Topic(track_key="agent_development", slug="inactive-practice-topic", name="Inactive", is_active=False)
    db_session.add(topic)
    db_session.commit()

    with pytest.raises(ApiError) as error:
        create_session(db_session, "topic", {"topic_ids": [topic.id]}, 10)

    assert error.value.status_code == 400
    assert "topic_ids" in error.value.fields


def test_tag_selector_rejects_unknown_tag(db_session):
    create_session = _create_selector()

    with pytest.raises(ApiError) as error:
        create_session(db_session, "tag", {"tag_ids": [999999]}, 10)

    assert error.value.status_code == 400
    assert "tag_ids" in error.value.fields


def test_tag_selector_rejects_inactive_tag(db_session):
    create_session = _create_selector()
    tag = Tag(name="Inactive Practice Tag", is_active=False)
    db_session.add(tag)
    db_session.commit()

    with pytest.raises(ApiError) as error:
        create_session(db_session, "tag", {"tag_ids": [tag.id]}, 10)

    assert error.value.status_code == 400
    assert "tag_ids" in error.value.fields


def test_limit_is_validated(db_session):
    create_session = _create_selector()

    for value in (0, -1, 101, True, 2.5):
        with pytest.raises(ApiError) as error:
            create_session(db_session, "random", {}, value)
        assert error.value.status_code == 400
        assert "limit" in error.value.fields


def test_empty_pool_returns_completed_empty_session(db_session):
    create_session = _create_selector()

    practice_session = create_session(db_session, "random", {}, 10, selection_seed=7)

    assert practice_session.items == []
    assert practice_session.completed_at is not None


def test_random_session_has_no_duplicate_question(db_session):
    create_session = _create_selector()
    for index in range(15):
        _add_question(db_session, f"Unique question {index}")

    practice_session = create_session(db_session, "random", {}, 15, selection_seed=9)
    question_ids = [item.question_id for item in practice_session.items]

    assert len(question_ids) == len(set(question_ids))


def test_archived_question_is_excluded_from_new_session(db_session):
    create_session = _create_selector()
    active = _add_question(db_session, "Active practice question")
    archived = _add_question(db_session, "Archived practice question")
    archived.archived_at = datetime.now(timezone.utc)
    db_session.commit()

    practice_session = create_session(db_session, "random", {}, 10, selection_seed=3)

    assert [item.question_id for item in practice_session.items] == [active.id]
