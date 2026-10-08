from __future__ import annotations

import importlib
from pathlib import Path

from werkzeug.datastructures import MultiDict

from app.models.question import Question, QuestionState, QuestionTag, QuestionTopic
from app.models.taxonomy import Tag, Topic
from app.services.questions import prepare_question_text


def _add_question(
    session,
    text_value: str,
    *,
    topics: tuple[Topic, ...] = (),
    tags: tuple[Tag, ...] = (),
    is_favorite: bool = False,
    is_wrong: bool = False,
) -> Question:
    question_text, normalized, digest = prepare_question_text(text_value)
    question = Question(
        text=question_text,
        normalized_text=normalized,
        search_text=normalized,
        normalized_hash=digest,
        status="active",
        state=QuestionState(is_favorite=is_favorite, is_wrong=is_wrong),
    )
    session.add(question)
    session.flush()
    session.add_all(
        [QuestionTopic(question_id=question.id, topic_id=topic.id) for topic in topics]
    )
    session.add_all([QuestionTag(question_id=question.id, tag_id=tag.id) for tag in tags])
    session.commit()
    return question


def _create_topic(session, slug: str) -> Topic:
    topic = Topic(track_key="agent_development", slug=slug, name=slug)
    session.add(topic)
    session.commit()
    return topic


def _create_tag(session, name: str) -> Tag:
    tag = Tag(name=name)
    session.add(tag)
    session.commit()
    return tag


def test_mixed_chinese_english_queries(client, db_session):
    expected = {
        "LangGraph 持久化": _add_question(db_session, "LangGraph 如何实现持久化？").id,
        "MCP 通信协议": _add_question(db_session, "MCP 通信协议是什么？").id,
        "Function Calling": _add_question(db_session, "Function Calling 的工作流程是什么？").id,
        "RAG 检索重排": _add_question(db_session, "RAG 检索重排如何实现？").id,
    }
    _add_question(db_session, "Python Flask 后端服务如何部署？")

    for query, expected_id in expected.items():
        response = client.get("/api/v1/questions", query_string={"q": query})
        assert response.status_code == 200
        result_ids = [item["id"] for item in response.get_json()]
        assert expected_id in result_ids[:10]
        assert result_ids == [expected_id]


def test_case_insensitive_english(client, db_session):
    expected = _add_question(db_session, "Use LangGraph to implement memory.")
    _add_question(db_session, "Use RAG to improve search.")

    response = client.get("/api/v1/questions", query_string={"q": "LANGGRAPH"})

    assert [item["id"] for item in response.get_json()] == [expected.id]


def test_mcp_and_rag_short_term_fallback(client, db_session):
    mcp = _add_question(db_session, "MCP 通信协议是什么？")
    rag = _add_question(db_session, "RAG 检索重排如何实现？")

    mcp_results = client.get("/api/v1/questions", query_string={"q": "MCP"}).get_json()
    rag_results = client.get("/api/v1/questions", query_string={"q": "RAG"}).get_json()

    assert [item["id"] for item in mcp_results] == [mcp.id]
    assert [item["id"] for item in rag_results] == [rag.id]


def test_short_term_fallback_does_not_require_trigram():
    search_path = Path(__file__).resolve().parents[2] / "app" / "services" / "search.py"
    assert search_path.is_file(), "missing feature: search service"
    search = importlib.import_module("app.services.search")

    fts_terms, substring_terms = search.split_search_terms("MCP RAG 持久化")

    assert fts_terms == []
    assert substring_terms == ["mcp", "rag", "持久化"]


def test_archived_question_excluded_by_default_search(client, db_session):
    active = _add_question(db_session, "LangGraph persistence architecture")
    archived = _add_question(db_session, "LangGraph persistence archive")
    assert client.post(f"/api/v1/questions/{archived.id}/archive").status_code == 200

    response = client.get("/api/v1/questions", query_string={"q": "LangGraph"})

    assert [item["id"] for item in response.get_json()] == [active.id]


def test_topic_tag_favorite_wrong_filters_combine_with_query(client, db_session):
    wanted_topic = _create_topic(db_session, "wanted-topic")
    other_topic = _create_topic(db_session, "other-topic")
    wanted_tag = _create_tag(db_session, "wanted-tag")
    other_tag = _create_tag(db_session, "other-tag")
    wanted = _add_question(
        db_session,
        "LangGraph memory question",
        topics=(wanted_topic,),
        tags=(wanted_tag,),
        is_favorite=True,
        is_wrong=True,
    )
    _add_question(
        db_session,
        "LangGraph memory question with another topic",
        topics=(other_topic,),
        tags=(wanted_tag,),
        is_favorite=True,
        is_wrong=True,
    )
    _add_question(
        db_session,
        "LangGraph memory question with another tag",
        topics=(wanted_topic,),
        tags=(other_tag,),
        is_favorite=True,
        is_wrong=True,
    )
    _add_question(
        db_session,
        "RAG unrelated but same filters",
        topics=(wanted_topic,),
        tags=(wanted_tag,),
        is_favorite=True,
        is_wrong=True,
    )
    _add_question(
        db_session,
        "LangGraph memory question not favorited",
        topics=(wanted_topic,),
        tags=(wanted_tag,),
        is_favorite=False,
        is_wrong=True,
    )

    query = MultiDict(
        [
            ("q", "LangGraph"),
            ("topic_ids", str(wanted_topic.id)),
            ("tag_ids", str(wanted_tag.id)),
            ("is_favorite", "true"),
            ("is_wrong", "true"),
        ]
    )
    response = client.get("/api/v1/questions", query_string=query)

    assert [item["id"] for item in response.get_json()] == [wanted.id]


def test_inactive_or_unknown_search_filter_is_rejected(client, db_session):
    inactive = _create_topic(db_session, "inactive-topic")
    inactive.is_active = False
    db_session.commit()

    unknown_response = client.get(
        "/api/v1/questions", query_string={"q": "MCP", "topic_ids": "999999"}
    )
    inactive_response = client.get(
        "/api/v1/questions", query_string={"q": "MCP", "topic_ids": str(inactive.id)}
    )

    for response in (unknown_response, inactive_response):
        assert response.status_code == 400
        assert response.get_json()["error"]["code"] == "VALIDATION_ERROR"
        assert "topic_ids" in response.get_json()["error"]["fields"]


def test_many_to_many_filters_do_not_duplicate_question(client, db_session):
    topic_a = _create_topic(db_session, "topic-a")
    topic_b = _create_topic(db_session, "topic-b")
    tag_a = _create_tag(db_session, "tag-a")
    tag_b = _create_tag(db_session, "tag-b")
    question = _add_question(
        db_session,
        "MCP question with many taxonomy links",
        topics=(topic_a, topic_b),
        tags=(tag_a, tag_b),
    )
    query = MultiDict(
        [
            ("q", "MCP"),
            ("topic_ids", str(topic_a.id)),
            ("topic_ids", str(topic_b.id)),
            ("tag_ids", str(tag_a.id)),
            ("tag_ids", str(tag_b.id)),
        ]
    )

    response = client.get("/api/v1/questions", query_string=query)
    result_ids = [item["id"] for item in response.get_json()]

    assert result_ids == [question.id]
