from __future__ import annotations

from sqlalchemy import Integer, Text, column, delete, select, table, text
from sqlalchemy.orm import Session, selectinload

from app.models.question import Question, QuestionState, QuestionTag, QuestionTopic


def _question_load_options():
    return (
        selectinload(Question.topic_links).selectinload(QuestionTopic.topic),
        selectinload(Question.tag_links).selectinload(QuestionTag.tag),
        selectinload(Question.state),
    )


def get_question(session: Session, question_id: int) -> Question | None:
    statement = select(Question).options(*_question_load_options()).where(Question.id == question_id)
    return session.scalar(statement)


def list_questions(
    session: Session,
    *,
    include_archived: bool = False,
    topic_ids: list[int] | None = None,
    tag_ids: list[int] | None = None,
    is_favorite: bool | None = None,
    is_wrong: bool | None = None,
) -> list[Question]:
    statement = _filtered_question_statement(
        include_archived=include_archived,
        topic_ids=topic_ids,
        tag_ids=tag_ids,
        is_favorite=is_favorite,
        is_wrong=is_wrong,
    )
    statement = statement.order_by(Question.updated_at.desc(), Question.id)
    return list(session.scalars(statement).all())


def search_question_rows(
    session: Session,
    *,
    fts_query: str | None,
    substring_terms: list[str],
    include_archived: bool = False,
    topic_ids: list[int] | None = None,
    tag_ids: list[int] | None = None,
    is_favorite: bool | None = None,
    is_wrong: bool | None = None,
) -> list[Question]:
    statement = _filtered_question_statement(
        include_archived=include_archived,
        topic_ids=topic_ids,
        tag_ids=tag_ids,
        is_favorite=is_favorite,
        is_wrong=is_wrong,
    )
    if fts_query:
        fts = table(
            "question_fts",
            column("question_id", Integer),
            column("search_text", Text),
        )
        statement = statement.join(fts, fts.c.question_id == Question.id)
        statement = statement.where(fts.c.search_text.match(fts_query))
        statement = statement.order_by(text("bm25(question_fts)"), Question.id)
    else:
        statement = statement.order_by(Question.updated_at.desc(), Question.id)

    for term in substring_terms:
        escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        statement = statement.where(Question.search_text.like(f"%{escaped}%", escape="\\"))
    return list(session.scalars(statement).all())


def _filtered_question_statement(
    *,
    include_archived: bool,
    topic_ids: list[int] | None,
    tag_ids: list[int] | None,
    is_favorite: bool | None,
    is_wrong: bool | None,
):
    statement = select(Question).options(*_question_load_options()).where(Question.status == "active")
    if not include_archived:
        statement = statement.where(Question.archived_at.is_(None))
    if topic_ids:
        matching_question_ids = select(QuestionTopic.question_id).where(QuestionTopic.topic_id.in_(topic_ids))
        statement = statement.where(Question.id.in_(matching_question_ids))
    if tag_ids:
        matching_question_ids = select(QuestionTag.question_id).where(QuestionTag.tag_id.in_(tag_ids))
        statement = statement.where(Question.id.in_(matching_question_ids))
    if is_favorite is not None:
        matching_question_ids = select(QuestionState.question_id).where(
            QuestionState.is_favorite.is_(is_favorite)
        )
        statement = statement.where(Question.id.in_(matching_question_ids))
    if is_wrong is not None:
        matching_question_ids = select(QuestionState.question_id).where(QuestionState.is_wrong.is_(is_wrong))
        statement = statement.where(Question.id.in_(matching_question_ids))
    return statement


def add_question(session: Session, question: Question, topic_ids: list[int], tag_ids: list[int]) -> Question:
    session.add(question)
    session.flush()
    session.add_all(
        [QuestionTopic(question_id=question.id, topic_id=topic_id) for topic_id in topic_ids]
    )
    session.add_all([QuestionTag(question_id=question.id, tag_id=tag_id) for tag_id in tag_ids])
    session.flush()
    return question


def replace_question_topics(session: Session, question_id: int, topic_ids: list[int]) -> None:
    session.execute(delete(QuestionTopic).where(QuestionTopic.question_id == question_id))
    session.add_all(
        [QuestionTopic(question_id=question_id, topic_id=topic_id) for topic_id in topic_ids]
    )


def replace_question_tags(session: Session, question_id: int, tag_ids: list[int]) -> None:
    session.execute(delete(QuestionTag).where(QuestionTag.question_id == question_id))
    session.add_all([QuestionTag(question_id=question_id, tag_id=tag_id) for tag_id in tag_ids])
