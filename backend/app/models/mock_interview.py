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
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from .taxonomy import utc_now


class MockInterviewSession(Base):
    """A transcript created only after the user explicitly saves it."""

    __tablename__ = "mock_interview_session"
    __table_args__ = (
        CheckConstraint("question_count BETWEEN 1 AND 10", name="ck_mock_interview_question_count"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    draft_key: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    topic_id_snapshot: Mapped[int | None] = mapped_column(Integer, nullable=True)
    topic_name_snapshot: Mapped[str | None] = mapped_column(String(240), nullable=True)
    question_count: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.current_timestamp()
    )
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    context_selection_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict, server_default=text("'{}'")
    )
    summary_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    summary_sources_json: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    provider: Mapped[str | None] = mapped_column(String(80), nullable=True)
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.current_timestamp()
    )

    turns: Mapped[list[MockInterviewTurn]] = relationship(
        back_populates="session", order_by="MockInterviewTurn.ordinal"
    )


class MockInterviewTurn(Base):
    __tablename__ = "mock_interview_turn"
    __table_args__ = (
        CheckConstraint("kind IN ('question', 'answer', 'follow_up')", name="ck_mock_interview_turn_kind"),
        UniqueConstraint("session_id", "ordinal", name="uq_mock_interview_turn_ordinal"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("mock_interview_session.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    question_id: Mapped[int] = mapped_column(ForeignKey("question.id", ondelete="RESTRICT"), nullable=False, index=True)
    question_text_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    content_text: Mapped[str] = mapped_column(Text, nullable=False)
    source_refs_json: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.current_timestamp()
    )

    session: Mapped[MockInterviewSession] = relationship(back_populates="turns")
