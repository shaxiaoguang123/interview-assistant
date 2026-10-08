from __future__ import annotations

from datetime import datetime
from typing import Any
import uuid

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from .taxonomy import utc_now


def _new_ocr_block_id() -> str:
    return str(uuid.uuid4())


class SourceAsset(Base):
    __tablename__ = "source_asset"
    __table_args__ = (
        CheckConstraint("byte_size >= 0", name="ck_source_asset_byte_size"),
        CheckConstraint(
            "original_width > 0 AND original_height > 0 "
            "AND display_width > 0 AND display_height > 0",
            name="ck_source_asset_dimensions",
        ),
        Index("ix_source_asset_sha256", "sha256"),
        Index("ix_source_asset_archived_at", "archived_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="image", server_default="image"
    )
    platform: Mapped[str | None] = mapped_column(String(80), nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    external_id: Mapped[str | None] = mapped_column(String(240), nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    author: Mapped[str | None] = mapped_column(String(240), nullable=True)
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    original_filename: Mapped[str | None] = mapped_column(String(512), nullable=True)
    mime_type: Mapped[str] = mapped_column(String(120), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    original_width: Mapped[int] = mapped_column(Integer, nullable=False)
    original_height: Mapped[int] = mapped_column(Integer, nullable=False)
    display_width: Mapped[int] = mapped_column(Integer, nullable=False)
    display_height: Mapped[int] = mapped_column(Integer, nullable=False)
    original_path: Mapped[str] = mapped_column(String(512), nullable=False)
    display_preview_path: Mapped[str] = mapped_column(String(512), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict, server_default=text("'{}'")
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

    ingestion_jobs: Mapped[list[IngestionJob]] = relationship(back_populates="source_asset")
    question_sources: Mapped[list[QuestionSource]] = relationship(back_populates="source_asset")


class IngestionJob(Base):
    __tablename__ = "ingestion_job"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name="ck_ingestion_job_status",
        ),
        CheckConstraint(
            "stage IN ('queued', 'initializing_adapter', 'recognizing', "
            "'building_candidates', 'persisting_results', 'completed')",
            name="ck_ingestion_job_stage",
        ),
        CheckConstraint("candidate_count >= 0", name="ck_ingestion_job_candidate_count"),
        Index("ix_ingestion_job_source_status", "source_asset_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_asset_id: Mapped[int] = mapped_column(
        ForeignKey("source_asset.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="queued", server_default="queued"
    )
    stage: Mapped[str] = mapped_column(
        String(32), nullable=False, default="queued", server_default="queued"
    )
    failure_stage: Mapped[str | None] = mapped_column(String(32), nullable=True)
    engine: Mapped[str | None] = mapped_column(String(120), nullable=True)
    engine_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    candidate_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.current_timestamp()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
        server_default=func.current_timestamp(),
    )

    source_asset: Mapped[SourceAsset] = relationship(back_populates="ingestion_jobs")
    ocr_blocks: Mapped[list[OCRBlock]] = relationship(back_populates="ingestion_job")
    origin_questions: Mapped[list["Question"]] = relationship(
        "Question",
        back_populates="origin_ingestion_job",
        foreign_keys="Question.origin_ingestion_job_id",
    )


class OCRBlock(Base):
    __tablename__ = "ocr_block"
    __table_args__ = (
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_ocr_block_confidence",
        ),
        Index("ix_ocr_block_job_reading_order", "ingestion_job_id", "reading_order"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=_new_ocr_block_id
    )
    ingestion_job_id: Mapped[int] = mapped_column(
        ForeignKey("ingestion_job.id", ondelete="RESTRICT"), nullable=False
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    bbox_json: Mapped[dict[str, float]] = mapped_column(JSON, nullable=False)
    reading_order: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    block_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="text", server_default="text"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.current_timestamp()
    )

    ingestion_job: Mapped[IngestionJob] = relationship(back_populates="ocr_blocks")
    question_source_links: Mapped[list[QuestionSourceOCRBlock]] = relationship(
        back_populates="ocr_block"
    )


class QuestionSource(Base):
    __tablename__ = "question_source"
    __table_args__ = (
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_question_source_confidence",
        ),
        Index("ix_question_source_question_id", "question_id"),
        Index("ix_question_source_source_asset_id", "source_asset_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    question_id: Mapped[int] = mapped_column(
        ForeignKey("question.id", ondelete="RESTRICT"), nullable=False
    )
    source_asset_id: Mapped[int] = mapped_column(
        ForeignKey("source_asset.id", ondelete="RESTRICT"), nullable=False
    )
    locator_type: Mapped[str] = mapped_column(
        String(40), nullable=False, default="image_region", server_default="image_region"
    )
    locator_json: Mapped[dict[str, float]] = mapped_column(JSON, nullable=False)
    locator_correction_json: Mapped[dict[str, float] | None] = mapped_column(JSON, nullable=True)
    source_text_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    raw_ocr_text_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.current_timestamp()
    )

    question: Mapped["Question"] = relationship("Question", back_populates="source_rows")
    source_asset: Mapped[SourceAsset] = relationship(back_populates="question_sources")
    ocr_block_links: Mapped[list[QuestionSourceOCRBlock]] = relationship(
        back_populates="question_source"
    )


class QuestionSourceOCRBlock(Base):
    __tablename__ = "question_source_ocr_block"

    question_source_id: Mapped[int] = mapped_column(
        ForeignKey("question_source.id", ondelete="RESTRICT"), primary_key=True
    )
    ocr_block_id: Mapped[str] = mapped_column(
        ForeignKey("ocr_block.id", ondelete="RESTRICT"), primary_key=True
    )

    question_source: Mapped[QuestionSource] = relationship(back_populates="ocr_block_links")
    ocr_block: Mapped[OCRBlock] = relationship(back_populates="question_source_links")
