from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from .taxonomy import utc_now


class PracticeSession(Base):
    __tablename__ = "practice_session"
    __table_args__ = (
        CheckConstraint("mode IN ('random', 'topic', 'tag', 'favorite', 'wrong', 'due')", name="ck_practice_session_mode"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mode: Mapped[str] = mapped_column(String(24), nullable=False)
    filters_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict, server_default=text("'{}'")
    )
    selector_version: Mapped[str] = mapped_column(
        String(24), nullable=False, default="v1", server_default="v1"
    )
    selection_seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.current_timestamp()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    items: Mapped[list[SessionItem]] = relationship(
        back_populates="session", order_by="SessionItem.ordinal"
    )


class SessionItem(Base):
    __tablename__ = "session_item"
    __table_args__ = (
        CheckConstraint("status IN ('shown', 'completed', 'skipped')", name="ck_session_item_status"),
        UniqueConstraint("session_id", "ordinal", name="uq_session_item_session_ordinal"),
        UniqueConstraint("session_id", "question_id", name="uq_session_item_session_question"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("practice_session.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    question_id: Mapped[int] = mapped_column(
        ForeignKey("question.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="shown", server_default="shown"
    )
    selection_reason: Mapped[str | None] = mapped_column(String(120), nullable=True)
    viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    session: Mapped[PracticeSession] = relationship(back_populates="items")
    question: Mapped["Question"] = relationship()
    practice_review: Mapped[PracticeReview | None] = relationship(
        back_populates="session_item", uselist=False
    )


class PracticeReview(Base):
    __tablename__ = "practice_review"
    __table_args__ = (
        CheckConstraint(
            "review_rating IN ('dont_know', 'vague', 'basic', 'proficient')",
            name="ck_practice_review_rating",
        ),
        UniqueConstraint("session_item_id", name="uq_practice_review_session_item"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    question_id: Mapped[int] = mapped_column(
        ForeignKey("question.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    session_item_id: Mapped[int] = mapped_column(
        ForeignKey("session_item.id", ondelete="RESTRICT"), nullable=False
    )
    review_rating: Mapped[str] = mapped_column(String(24), nullable=False)
    saved_answer_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("saved_answer_version.id", ondelete="RESTRICT"), nullable=True
    )
    reviewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.current_timestamp()
    )
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

    session_item: Mapped[SessionItem] = relationship(back_populates="practice_review")
    question: Mapped["Question"] = relationship()
