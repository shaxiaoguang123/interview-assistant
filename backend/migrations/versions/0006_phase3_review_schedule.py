"""Fixed review intervals and six practice modes, preserving historical IDs."""
from datetime import datetime, timedelta, timezone

from alembic import op
import sqlalchemy as sa

revision = "0006_phase3_review_schedule"
down_revision = "0005_saved_answers"
branch_labels = None
depends_on = None


def upgrade():
    for name, kind in (("last_reviewed_at", sa.DateTime(timezone=True)),
                       ("last_review_rating", sa.String(24)),
                       ("next_review_at", sa.DateTime(timezone=True))):
        op.add_column("question_state", sa.Column(name, kind, nullable=True))
    op.create_index("ix_question_state_next_review_at", "question_state", ["next_review_at"])
    # SQLite needs a copy for a CHECK change. env.py disables FK enforcement only
    # on the migration connection and checks every FK before committing the DDL.
    with op.batch_alter_table("practice_session", recreate="always") as batch:
        batch.drop_constraint("ck_practice_session_mode", type_="check")
        batch.create_check_constraint("ck_practice_session_mode",
            "mode IN ('random', 'topic', 'tag', 'favorite', 'wrong', 'due')")
    connection = op.get_bind()
    rows = connection.execute(sa.text("""SELECT COALESCE(q.merged_into_question_id,q.id) root_id,
        r.review_rating,r.reviewed_at,r.id FROM practice_review r
        JOIN question q ON q.id=r.question_id ORDER BY r.reviewed_at DESC,r.id DESC""")).mappings().all()
    seen = set()
    intervals = {"dont_know": 1, "vague": 2, "basic": 7, "proficient": 14}
    for row in rows:
        root = row["root_id"]
        if root in seen:
            continue
        seen.add(root)
        reviewed = datetime.fromisoformat(str(row["reviewed_at"]))
        if reviewed.tzinfo is not None:
            reviewed = reviewed.astimezone(timezone.utc).replace(tzinfo=None)
        due = reviewed + timedelta(days=intervals[row["review_rating"]])
        connection.execute(sa.text("INSERT INTO question_state(question_id) VALUES (:id) ON CONFLICT(question_id) DO NOTHING"), {"id": root})
        connection.execute(sa.text("""UPDATE question_state SET last_reviewed_at=:reviewed,
            last_review_rating=:rating,next_review_at=:due WHERE question_id=:id"""),
            {"id": root, "reviewed": reviewed.isoformat(sep=" "), "rating": row["review_rating"], "due": due.isoformat(sep=" ")})


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM practice_session WHERE mode IN ('favorite','wrong','due')")):
        raise RuntimeError("Cannot downgrade while Phase 3 practice sessions exist")
    with op.batch_alter_table("practice_session", recreate="always") as batch:
        batch.drop_constraint("ck_practice_session_mode", type_="check")
        batch.create_check_constraint("ck_practice_session_mode", "mode IN ('random', 'topic', 'tag')")
    op.drop_index("ix_question_state_next_review_at", table_name="question_state")
    for name in ("next_review_at", "last_review_rating", "last_reviewed_at"):
        op.drop_column("question_state", name)
