"""Link saved interview answer turns to immutable SavedAnswer versions."""
from alembic import op
import sqlalchemy as sa


revision = "0009_mock_interview_answer_export"
down_revision = "0008_mock_interview"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "mock_interview_answer_export",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("mock_interview_turn_id", sa.Integer(), nullable=False),
        sa.Column("saved_answer_version_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["mock_interview_turn_id"], ["mock_interview_turn.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["saved_answer_version_id"], ["saved_answer_version.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("mock_interview_turn_id", name="uq_mock_interview_answer_export_turn"),
        sa.UniqueConstraint("saved_answer_version_id", name="uq_mock_interview_answer_export_version"),
    )
def downgrade():
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM mock_interview_answer_export")):
        raise RuntimeError("Cannot downgrade while mock-interview answer exports exist")
    op.drop_table("mock_interview_answer_export")
