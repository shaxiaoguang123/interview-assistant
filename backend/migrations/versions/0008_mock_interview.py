"""Saved text mock-interview transcripts, isolated from practice reviews."""
from alembic import op
import sqlalchemy as sa

revision = "0008_mock_interview"
down_revision = "0007_project_material_assistant"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "mock_interview_session",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("draft_key", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("topic_id_snapshot", sa.Integer(), nullable=True),
        sa.Column("topic_name_snapshot", sa.String(length=240), nullable=True),
        sa.Column("question_count", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("context_selection_json", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("summary_json", sa.JSON(), nullable=True),
        sa.Column("summary_sources_json", sa.JSON(), nullable=True),
        sa.Column("provider", sa.String(length=80), nullable=True),
        sa.Column("model", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("question_count BETWEEN 1 AND 10", name="ck_mock_interview_question_count"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("draft_key"),
    )
    op.create_table(
        "mock_interview_turn",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("question_id", sa.Integer(), nullable=False),
        sa.Column("question_text_snapshot", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("content_text", sa.Text(), nullable=False),
        sa.Column("source_refs_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("kind IN ('question', 'answer', 'follow_up')", name="ck_mock_interview_turn_kind"),
        sa.ForeignKeyConstraint(["question_id"], ["question.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["session_id"], ["mock_interview_session.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "ordinal", name="uq_mock_interview_turn_ordinal"),
    )
    op.create_index("ix_mock_interview_turn_session_id", "mock_interview_turn", ["session_id"])
    op.create_index("ix_mock_interview_turn_question_id", "mock_interview_turn", ["question_id"])


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM mock_interview_session")):
        raise RuntimeError("Cannot downgrade while saved mock-interview history exists")
    op.drop_index("ix_mock_interview_turn_question_id", table_name="mock_interview_turn")
    op.drop_index("ix_mock_interview_turn_session_id", table_name="mock_interview_turn")
    op.drop_table("mock_interview_turn")
    op.drop_table("mock_interview_session")
