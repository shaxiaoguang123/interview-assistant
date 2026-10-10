"""Explicitly saved answers and append-only content versions."""
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from .taxonomy import utc_now


class SavedAnswer(Base):
    __tablename__ = "saved_answer"
    __table_args__ = (
        Index("uq_saved_answer_pinned_question", "question_id", unique=True,
              sqlite_where=text("is_pinned = 1 AND archived_at IS NULL")),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("question.id", ondelete="RESTRICT"), index=True)
    source_session_item_id: Mapped[int | None] = mapped_column(ForeignKey("session_item.id", ondelete="RESTRICT"))
    is_pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("0"))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, server_default=func.current_timestamp())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, server_default=func.current_timestamp())


class SavedAnswerVersion(Base):
    __tablename__ = "saved_answer_version"
    __table_args__ = (
        UniqueConstraint("saved_answer_id", "version_no", name="uq_saved_answer_version_no"),
        CheckConstraint("version_no > 0", name="ck_saved_answer_version_no"),
        CheckConstraint("length(trim(content)) > 0", name="ck_saved_answer_content"),
        CheckConstraint("self_rating IS NULL OR self_rating BETWEEN 1 AND 5", name="ck_saved_answer_rating"),
        CheckConstraint("origin_kind IN ('user_written', 'ai_assisted', 'ai_generated')", name="ck_saved_answer_origin"),
        CheckConstraint("(source_session_item_id IS NULL) = (source_practice_review_id IS NULL)", name="ck_saved_answer_source_pair"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    saved_answer_id: Mapped[int] = mapped_column(ForeignKey("saved_answer.id", ondelete="RESTRICT"), index=True)
    version_no: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    self_rating: Mapped[int | None] = mapped_column(Integer)
    self_rating_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    origin_kind: Mapped[str] = mapped_column(String(24), default="user_written", server_default="user_written")
    source_session_item_id: Mapped[int | None] = mapped_column(ForeignKey("session_item.id", ondelete="RESTRICT"))
    source_practice_review_id: Mapped[int | None] = mapped_column(ForeignKey("practice_review.id", ondelete="RESTRICT"))
    based_on_version_id: Mapped[int | None] = mapped_column(ForeignKey("saved_answer_version.id", ondelete="RESTRICT"))
    # Reserved nullable identifier; AssistantOutput is outside Phase 2.
    assistant_output_id: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, server_default=func.current_timestamp())
