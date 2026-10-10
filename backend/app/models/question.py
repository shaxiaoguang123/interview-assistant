from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
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
        CheckConstraint(
            "(status = 'merged' AND merged_into_question_id IS NOT NULL "
            "AND merged_into_question_id <> id) OR "
            "(status <> 'merged' AND merged_into_question_id IS NULL)",
            name="ck_question_merged_into_status",
        ),
        CheckConstraint(
            "ingestion_candidate_state IS NULL OR "
            "ingestion_candidate_state IN ('pending_review', 'confirmed', 'rejected', 'superseded')",
            name="ck_question_ingestion_candidate_state",
        ),
        CheckConstraint("candidate_revision >= 0", name="ck_question_candidate_revision"),
        CheckConstraint(
            "split_from_candidate_id IS NULL OR "
            "(origin_ingestion_job_id IS NOT NULL AND split_from_candidate_id <> id)",
            name="ck_question_split_from_candidate",
        ),
        CheckConstraint(
            "superseded_by_candidate_id IS NULL OR "
            "(origin_ingestion_job_id IS NOT NULL AND superseded_by_candidate_id <> id)",
            name="ck_question_superseded_by_candidate",
        ),
        Index("ix_question_normalized_hash", "normalized_hash"),
        Index("ix_question_status_archived_at", "status", "archived_at"),
        Index("ix_question_merged_into_question_id", "merged_into_question_id"),
        Index("ix_question_origin_ingestion_job_id", "origin_ingestion_job_id"),
        Index("ix_question_split_from_candidate_id", "split_from_candidate_id"),
        Index("ix_question_superseded_by_candidate_id", "superseded_by_candidate_id"),
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
    origin_ingestion_job_id: Mapped[int | None] = mapped_column(
        ForeignKey("ingestion_job.id", ondelete="RESTRICT"), nullable=True
    )
    ingestion_candidate_state: Mapped[str | None] = mapped_column(String(24), nullable=True)
    candidate_revision: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    split_from_candidate_id: Mapped[int | None] = mapped_column(
        ForeignKey("question.id", ondelete="RESTRICT"), nullable=True
    )
    superseded_by_candidate_id: Mapped[int | None] = mapped_column(
        ForeignKey("question.id", ondelete="RESTRICT"), nullable=True
    )
    merged_into_question_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "question.id",
            name="fk_question_merged_into_question_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
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
    origin_ingestion_job: Mapped["IngestionJob | None"] = relationship(
        "IngestionJob",
        back_populates="origin_questions",
        foreign_keys=[origin_ingestion_job_id],
    )
    split_from_candidate: Mapped["Question | None"] = relationship(
        "Question",
        remote_side=[id],
        foreign_keys=[split_from_candidate_id],
        back_populates="split_children",
    )
    split_children: Mapped[list["Question"]] = relationship(
        "Question",
        foreign_keys=[split_from_candidate_id],
        back_populates="split_from_candidate",
    )
    superseded_by_candidate: Mapped["Question | None"] = relationship(
        "Question",
        remote_side=[id],
        foreign_keys=[superseded_by_candidate_id],
        back_populates="superseded_candidates",
    )
    superseded_candidates: Mapped[list["Question"]] = relationship(
        "Question",
        foreign_keys=[superseded_by_candidate_id],
        back_populates="superseded_by_candidate",
    )
    merged_into_question: Mapped[Question | None] = relationship(
        "Question",
        remote_side=[id],
        foreign_keys=[merged_into_question_id],
        back_populates="merged_children",
    )
    merged_children: Mapped[list[Question]] = relationship(
        "Question",
        foreign_keys=[merged_into_question_id],
        back_populates="merged_into_question",
    )
    source_rows: Mapped[list["QuestionSource"]] = relationship(
        "QuestionSource", back_populates="question"
    )
    relations_as_question: Mapped[list["QuestionRelation"]] = relationship(
        "QuestionRelation",
        foreign_keys="QuestionRelation.question_id",
        back_populates="question",
    )
    relations_as_related_question: Mapped[list["QuestionRelation"]] = relationship(
        "QuestionRelation",
        foreign_keys="QuestionRelation.related_question_id",
        back_populates="related_question",
    )


class QuestionRelation(Base):
    __tablename__ = "question_relation"
    __table_args__ = (
        CheckConstraint(
            "question_id < related_question_id",
            name="ck_question_relation_ascending_pair",
        ),
        CheckConstraint(
            "relation_type IN ('same_question', 'related_question', 'different_question')",
            name="ck_question_relation_type",
        ),
        CheckConstraint(
            "decision_status IN ('suggested', 'accepted', 'rejected')",
            name="ck_question_relation_decision_status",
        ),
        CheckConstraint(
            "suggested_by IN ('rule', 'llm', 'user')",
            name="ck_question_relation_suggested_by",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_question_relation_confidence",
        ),
        CheckConstraint(
            "length(question_text_sha256_snapshot) = 64 AND "
            "question_text_sha256_snapshot NOT GLOB '*[^0-9a-f]*' AND "
            "length(related_question_text_sha256_snapshot) = 64 AND "
            "related_question_text_sha256_snapshot NOT GLOB '*[^0-9a-f]*'",
            name="ck_question_relation_text_sha256",
        ),
        UniqueConstraint(
            "question_id",
            "related_question_id",
            name="uq_question_relation_pair",
        ),
        Index(
            "ix_question_relation_related_question_id",
            "related_question_id",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    question_id: Mapped[int] = mapped_column(
        ForeignKey(
            "question.id",
            name="fk_question_relation_question_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    related_question_id: Mapped[int] = mapped_column(
        ForeignKey(
            "question.id",
            name="fk_question_relation_related_question_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    relation_type: Mapped[str] = mapped_column(String(32), nullable=False)
    decision_status: Mapped[str] = mapped_column(String(24), nullable=False)
    suggested_by: Mapped[str] = mapped_column(String(24), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    question_text_sha256_snapshot: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    related_question_text_sha256_snapshot: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=func.current_timestamp(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
        server_default=func.current_timestamp(),
    )

    question: Mapped[Question] = relationship(
        "Question",
        foreign_keys=[question_id],
        back_populates="relations_as_question",
    )
    related_question: Mapped[Question] = relationship(
        "Question",
        foreign_keys=[related_question_id],
        back_populates="relations_as_related_question",
    )


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
    last_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_review_rating: Mapped[str | None] = mapped_column(String(24))
    next_review_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    user_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
        server_default=func.current_timestamp(),
    )

    question: Mapped[Question] = relationship(back_populates="state")
