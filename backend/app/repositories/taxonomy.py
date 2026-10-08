from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.taxonomy import Tag, Topic


def list_topics(session: Session) -> list[Topic]:
    return list(session.scalars(select(Topic).order_by(Topic.sort_order, Topic.slug)).all())


def get_topic(session: Session, topic_id: int) -> Topic | None:
    return session.get(Topic, topic_id)


def get_topics_by_ids(session: Session, topic_ids: list[int]) -> list[Topic]:
    if not topic_ids:
        return []
    rows = session.scalars(select(Topic).where(Topic.id.in_(topic_ids))).all()
    by_id = {topic.id: topic for topic in rows}
    return [by_id[topic_id] for topic_id in topic_ids if topic_id in by_id]


def topic_slug_exists(session: Session, slug: str, *, excluding_id: int | None = None) -> bool:
    statement = select(Topic.id).where(Topic.slug == slug)
    if excluding_id is not None:
        statement = statement.where(Topic.id != excluding_id)
    return session.scalar(statement) is not None


def list_tags(session: Session) -> list[Tag]:
    return list(session.scalars(select(Tag).order_by(Tag.name, Tag.id)).all())


def get_tag(session: Session, tag_id: int) -> Tag | None:
    return session.get(Tag, tag_id)


def get_tags_by_ids(session: Session, tag_ids: list[int]) -> list[Tag]:
    if not tag_ids:
        return []
    rows = session.scalars(select(Tag).where(Tag.id.in_(tag_ids))).all()
    by_id = {tag.id: tag for tag in rows}
    return [by_id[tag_id] for tag_id in tag_ids if tag_id in by_id]


def tag_name_exists(session: Session, name: str, *, excluding_id: int | None = None) -> bool:
    statement = select(Tag.id).where(Tag.name == name)
    if excluding_id is not None:
        statement = statement.where(Tag.id != excluding_id)
    return session.scalar(statement) is not None
