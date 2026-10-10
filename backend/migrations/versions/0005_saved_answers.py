"""Saved answers, immutable versions and optional practice linkage."""
from alembic import op
import sqlalchemy as sa

revision = "0005_saved_answers"
down_revision = "0004_question_relations"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("saved_answer",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("question_id", sa.Integer(), sa.ForeignKey("question.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("source_session_item_id", sa.Integer(), sa.ForeignKey("session_item.id", ondelete="RESTRICT")),
        sa.Column("is_pinned", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()))
    op.create_index("ix_saved_answer_question_id", "saved_answer", ["question_id"])
    op.create_index("uq_saved_answer_pinned_question", "saved_answer", ["question_id"], unique=True,
                    sqlite_where=sa.text("is_pinned = 1 AND archived_at IS NULL"))
    op.create_table("saved_answer_version",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("saved_answer_id", sa.Integer(), sa.ForeignKey("saved_answer.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("self_rating", sa.Integer()),
        sa.Column("self_rating_updated_at", sa.DateTime(timezone=True)),
        sa.Column("origin_kind", sa.String(24), nullable=False, server_default="user_written"),
        sa.Column("source_session_item_id", sa.Integer(), sa.ForeignKey("session_item.id", ondelete="RESTRICT")),
        sa.Column("source_practice_review_id", sa.Integer(), sa.ForeignKey("practice_review.id", ondelete="RESTRICT")),
        sa.Column("based_on_version_id", sa.Integer(), sa.ForeignKey("saved_answer_version.id", ondelete="RESTRICT")),
        sa.Column("assistant_output_id", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()),
        sa.UniqueConstraint("saved_answer_id", "version_no", name="uq_saved_answer_version_no"),
        sa.CheckConstraint("version_no > 0", name="ck_saved_answer_version_no"),
        sa.CheckConstraint("length(trim(content)) > 0", name="ck_saved_answer_content"),
        sa.CheckConstraint("self_rating IS NULL OR self_rating BETWEEN 1 AND 5", name="ck_saved_answer_rating"),
        sa.CheckConstraint("origin_kind IN ('user_written', 'ai_assisted', 'ai_generated')", name="ck_saved_answer_origin"),
        sa.CheckConstraint("(source_session_item_id IS NULL) = (source_practice_review_id IS NULL)", name="ck_saved_answer_source_pair"))
    op.create_index("ix_saved_answer_version_saved_answer_id", "saved_answer_version", ["saved_answer_id"])
    # ADD COLUMN preserves the existing table, triggers, FTS and all historical IDs.
    op.execute("ALTER TABLE practice_review ADD COLUMN saved_answer_version_id INTEGER REFERENCES saved_answer_version(id) ON DELETE RESTRICT")
    immutable = ["saved_answer_id", "version_no", "content", "origin_kind", "source_session_item_id",
                 "source_practice_review_id", "based_on_version_id", "assistant_output_id", "created_at"]
    condition = " OR ".join(f"NEW.{field} IS NOT OLD.{field}" for field in immutable)
    op.execute(f"CREATE TRIGGER saved_answer_version_immutable BEFORE UPDATE ON saved_answer_version WHEN {condition} BEGIN SELECT RAISE(ABORT, 'Saved answer content versions are immutable'); END")
    # Partial index handles a single question; these triggers also enforce a canonical group.
    for action in ("INSERT", "UPDATE"):
        op.execute(f"""CREATE TRIGGER saved_answer_group_pin_{action.lower()}
            BEFORE {action} ON saved_answer
            WHEN NEW.is_pinned = 1 AND NEW.archived_at IS NULL AND EXISTS (
                SELECT 1 FROM saved_answer a JOIN question q ON q.id = a.question_id
                JOIN question n ON n.id = NEW.question_id
                WHERE a.id != NEW.id AND a.is_pinned = 1 AND a.archived_at IS NULL
                AND COALESCE(q.merged_into_question_id, q.id) = COALESCE(n.merged_into_question_id, n.id))
            BEGIN SELECT RAISE(ABORT, 'Canonical group already has a pinned answer'); END""")
    op.execute("""CREATE TRIGGER question_saved_answer_pin_merge BEFORE UPDATE OF merged_into_question_id ON question
        WHEN NEW.merged_into_question_id IS NOT NULL AND NEW.merged_into_question_id IS NOT OLD.merged_into_question_id
        AND EXISTS (SELECT 1 FROM saved_answer a WHERE a.question_id = OLD.id AND a.is_pinned = 1 AND a.archived_at IS NULL)
        AND EXISTS (SELECT 1 FROM saved_answer a JOIN question q ON q.id = a.question_id
                    WHERE COALESCE(q.merged_into_question_id, q.id) = NEW.merged_into_question_id
                    AND a.is_pinned = 1 AND a.archived_at IS NULL)
        BEGIN SELECT RAISE(ABORT, 'Select one pinned answer before merging'); END""")


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM saved_answer")):
        raise RuntimeError("Cannot downgrade while saved answer history exists")
    for name in ("question_saved_answer_pin_merge", "saved_answer_group_pin_insert", "saved_answer_group_pin_update", "saved_answer_version_immutable"):
        op.execute(f"DROP TRIGGER {name}")
    op.drop_column("practice_review", "saved_answer_version_id")
    op.drop_table("saved_answer_version")
    op.drop_table("saved_answer")
