from __future__ import annotations

from sqlalchemy import Integer, Text, column, delete, exists, func, or_, select, table
from sqlalchemy.orm import Session, aliased, selectinload

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


def canonical_member_ids(session: Session, canonical_id: int) -> list[int]:
    return list(session.scalars(select(Question.id).where(or_(
        Question.id == canonical_id,
        Question.merged_into_question_id == canonical_id,
    )).order_by(Question.id)))


def group_states(session: Session, canonical_ids: list[int]) -> dict[int, dict]:
    """Read OR flags without mutating the persisted per-Question state rows."""
    if not canonical_ids:
        return {}
    canonical = func.coalesce(Question.merged_into_question_id, Question.id)
    rows = session.execute(select(
        canonical.label('canonical_id'),
        func.max(QuestionState.is_favorite), func.max(QuestionState.is_wrong),
        func.count(Question.id),
    ).outerjoin(QuestionState, QuestionState.question_id == Question.id)
      .where(canonical.in_(canonical_ids)).group_by(canonical))
    return {qid: {'is_favorite': bool(favorite), 'is_wrong': bool(wrong), 'member_count': count}
            for qid, favorite, wrong, count in rows}


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
    member = aliased(Question)
    matches = select(func.coalesce(member.merged_into_question_id, member.id)).where(
        or_(member.status == 'active', member.status == 'merged')
    )
    if fts_query:
        fts = table(
            "question_fts",
            column("question_id", Integer),
            column("search_text", Text),
        )
        matches = matches.join(fts, fts.c.question_id == member.id)
        matches = matches.where(fts.c.search_text.match(fts_query))

    for term in substring_terms:
        escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        matches = matches.where(member.search_text.like(f"%{escaped}%", escape="\\"))
    statement = statement.where(Question.id.in_(matches)).order_by(Question.updated_at.desc(), Question.id)
    return list(session.scalars(statement).all())


def _filtered_question_statement(
    *,
    include_archived: bool,
    topic_ids: list[int] | None,
    tag_ids: list[int] | None,
    is_favorite: bool | None,
    is_wrong: bool | None,
):
    statement = select(Question).options(*_question_load_options()).where(
        Question.status == "active", Question.merged_into_question_id.is_(None)
    )
    if not include_archived:
        statement = statement.where(Question.archived_at.is_(None))
    if topic_ids:
        matching_question_ids = select(QuestionTopic.question_id).where(QuestionTopic.topic_id.in_(topic_ids))
        statement = statement.where(Question.id.in_(matching_question_ids))
    if tag_ids:
        matching_question_ids = select(QuestionTag.question_id).where(QuestionTag.tag_id.in_(tag_ids))
        statement = statement.where(Question.id.in_(matching_question_ids))
    member = aliased(Question)
    for field, value in (('is_favorite', is_favorite), ('is_wrong', is_wrong)):
        if value is not None:
            has_mark = exists(select(QuestionState.question_id)
                .join(member, member.id == QuestionState.question_id)
                .where(or_(member.id == Question.id, member.merged_into_question_id == Question.id),
                       getattr(QuestionState, field).is_(True)))
            statement = statement.where(has_mark if value else ~has_mark)
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
