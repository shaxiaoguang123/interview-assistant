from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from .taxonomy import Tag, Topic, utc_now


class Question(Base):
    __tablename__ = "question"
    __table_args__ = (
        CheckConstraint("status IN ('pending_review', 'active', 'merged')", name="ck_question_status"),
        Index("ix_question_normalized_hash", "normalized_hash"),
        Index("ix_question_status_archived_at", "status", "archived_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_text: Mapped[str] = mapped_column(Text, nullable=False)
    search_text: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    answer_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    difficulty: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="active", server_default="active"
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.current_timestamp()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
        server_default=func.current_timestamp(),
    )

    topic_links: Mapped[list[QuestionTopic]] = relationship(back_populates="question")
    tag_links: Mapped[list[QuestionTag]] = relationship(back_populates="question")
    state: Mapped[QuestionState | None] = relationship(back_populates="question", uselist=False)


class QuestionTopic(Base):
    __tablename__ = "question_topic"

    question_id: Mapped[int] = mapped_column(
        ForeignKey("question.id", ondelete="RESTRICT"), primary_key=True
    )
    topic_id: Mapped[int] = mapped_column(
        ForeignKey("topic.id", ondelete="RESTRICT"), primary_key=True
    )

    question: Mapped[Question] = relationship(back_populates="topic_links")
    topic: Mapped[Topic] = relationship()


class QuestionTag(Base):
    __tablename__ = "question_tag"

    question_id: Mapped[int] = mapped_column(
        ForeignKey("question.id", ondelete="RESTRICT"), primary_key=True
    )
    tag_id: Mapped[int] = mapped_column(ForeignKey("tag.id", ondelete="RESTRICT"), primary_key=True)

    question: Mapped[Question] = relationship(back_populates="tag_links")
    tag: Mapped[Tag] = relationship()


class QuestionState(Base):
    __tablename__ = "question_state"

    question_id: Mapped[int] = mapped_column(
        ForeignKey("question.id", ondelete="RESTRICT"), primary_key=True
    )
    is_favorite: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    is_wrong: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    user_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
        server_default=func.current_timestamp(),
    )

    question: Mapped[Question] = relationship(back_populates="state")
