"""Create Phase 1A taxonomy, question, and practice tables."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0001_phase1a_core"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "topic",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("track_key", sa.String(length=80), nullable=False, server_default="agent_development"),
        sa.Column("parent_id", sa.Integer(), nullable=True),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()),
        sa.ForeignKeyConstraint(["parent_id"], ["topic.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("slug", name="uq_topic_slug"),
    )
    op.create_index("ix_topic_parent_id", "topic", ["parent_id"])

    op.create_table(
        "tag",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()),
        sa.UniqueConstraint("name", name="uq_tag_name"),
    )

    op.create_table(
        "question",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("normalized_text", sa.Text(), nullable=False),
        sa.Column("search_text", sa.Text(), nullable=False),
        sa.Column("normalized_hash", sa.String(length=64), nullable=False),
        sa.Column("answer_type", sa.String(length=40), nullable=True),
        sa.Column("difficulty", sa.String(length=40), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="active"),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()),
        sa.CheckConstraint(
            "status IN ('pending_review', 'active', 'merged')", name="ck_question_status"
        ),
    )
    op.create_index("ix_question_normalized_hash", "question", ["normalized_hash"], unique=False)
    op.create_index("ix_question_status_archived_at", "question", ["status", "archived_at"])

    op.create_table(
        "question_topic",
        sa.Column("question_id", sa.Integer(), nullable=False),
        sa.Column("topic_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["question_id"], ["question.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["topic_id"], ["topic.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("question_id", "topic_id", name="pk_question_topic"),
    )
    op.create_index("ix_question_topic_topic_id", "question_topic", ["topic_id"])

    op.create_table(
        "question_tag",
        sa.Column("question_id", sa.Integer(), nullable=False),
        sa.Column("tag_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["question_id"], ["question.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tag_id"], ["tag.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("question_id", "tag_id", name="pk_question_tag"),
    )
    op.create_index("ix_question_tag_tag_id", "question_tag", ["tag_id"])

    op.create_table(
        "question_state",
        sa.Column("question_id", sa.Integer(), nullable=False),
        sa.Column("is_favorite", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("is_wrong", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("user_note", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()),
        sa.ForeignKeyConstraint(["question_id"], ["question.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("question_id", name="pk_question_state"),
    )

    op.create_table(
        "practice_session",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("mode", sa.String(length=24), nullable=False),
        sa.Column("filters_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("selector_version", sa.String(length=24), nullable=False, server_default="v1"),
        sa.Column("selection_seed", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("mode IN ('random', 'topic', 'tag')", name="ck_practice_session_mode"),
    )

    op.create_table(
        "session_item",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("question_id", sa.Integer(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="shown"),
        sa.Column("selection_reason", sa.String(length=120), nullable=True),
        sa.Column("viewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["session_id"], ["practice_session.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["question_id"], ["question.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("status IN ('shown', 'completed', 'skipped')", name="ck_session_item_status"),
        sa.UniqueConstraint("session_id", "ordinal", name="uq_session_item_session_ordinal"),
        sa.UniqueConstraint("session_id", "question_id", name="uq_session_item_session_question"),
    )
    op.create_index("ix_session_item_session_id", "session_item", ["session_id"])
    op.create_index("ix_session_item_question_id", "session_item", ["question_id"])

    op.create_table(
        "practice_review",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("question_id", sa.Integer(), nullable=False),
        sa.Column("session_item_id", sa.Integer(), nullable=False),
        sa.Column("review_rating", sa.String(length=24), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()),
        sa.ForeignKeyConstraint(["question_id"], ["question.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["session_item_id"], ["session_item.id"], ondelete="RESTRICT"),
        sa.CheckConstraint(
            "review_rating IN ('dont_know', 'vague', 'basic', 'proficient')",
            name="ck_practice_review_rating",
        ),
        sa.UniqueConstraint("session_item_id", name="uq_practice_review_session_item"),
    )
    op.create_index("ix_practice_review_question_id", "practice_review", ["question_id"])


def downgrade() -> None:
    op.drop_index("ix_practice_review_question_id", table_name="practice_review")
    op.drop_table("practice_review")
    op.drop_index("ix_session_item_question_id", table_name="session_item")
    op.drop_index("ix_session_item_session_id", table_name="session_item")
    op.drop_table("session_item")
    op.drop_table("practice_session")
    op.drop_table("question_state")
    op.drop_index("ix_question_tag_tag_id", table_name="question_tag")
    op.drop_table("question_tag")
    op.drop_index("ix_question_topic_topic_id", table_name="question_topic")
    op.drop_table("question_topic")
    op.drop_index("ix_question_status_archived_at", table_name="question")
    op.drop_index("ix_question_normalized_hash", table_name="question")
    op.drop_table("question")
    op.drop_table("tag")
    op.drop_index("ix_topic_parent_id", table_name="topic")
    op.drop_table("topic")
