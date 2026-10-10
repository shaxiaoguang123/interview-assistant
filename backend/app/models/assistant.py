"""Only explicitly saved assistant outputs and actual evidence snapshots."""
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, CheckConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base
from .taxonomy import utc_now


class AssistantOutput(Base):
    __tablename__ = 'assistant_output'
    __table_args__ = (CheckConstraint("output_type IN ('polish','reference_answer','analyze')",name='ck_assistant_output_type'),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    preview_key: Mapped[str] = mapped_column(String(36), unique=True)
    question_id: Mapped[int] = mapped_column(ForeignKey('question.id', ondelete='RESTRICT'), index=True)
    source_saved_answer_version_id: Mapped[int | None] = mapped_column(ForeignKey('saved_answer_version.id', ondelete='RESTRICT'))
    output_type: Mapped[str] = mapped_column(String(32))
    origin_kind: Mapped[str] = mapped_column(String(24))
    selected_context_json: Mapped[dict] = mapped_column(JSON)
    content_text: Mapped[str] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(String(80))
    model: Mapped[str] = mapped_column(String(120))
    prompt_version: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, server_default=func.current_timestamp())


class AssistantOutputSource(Base):
    __tablename__ = 'assistant_output_source'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    assistant_output_id: Mapped[int] = mapped_column(ForeignKey('assistant_output.id', ondelete='RESTRICT'), index=True)
    material_version_id: Mapped[int | None] = mapped_column(ForeignKey('material_version.id', ondelete='SET NULL'))
    material_id_snapshot: Mapped[int] = mapped_column(Integer)
    material_version_id_snapshot: Mapped[int] = mapped_column(Integer)
    project_id_snapshot: Mapped[int | None] = mapped_column(Integer)
    chunk_ids_json: Mapped[list | None] = mapped_column(JSON)
    source_title_snapshot: Mapped[str] = mapped_column(String(240))
    version_no_snapshot: Mapped[int] = mapped_column(Integer)
    sha256_snapshot: Mapped[str] = mapped_column(String(64))
    source_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
