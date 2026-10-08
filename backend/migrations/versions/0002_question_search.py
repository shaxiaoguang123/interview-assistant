"""Add SQLite FTS5 question search and synchronization triggers."""

from __future__ import annotations

from alembic import op
from sqlalchemy.exc import OperationalError


revision = "0002_question_search"
down_revision = "0001_phase1a_core"
branch_labels = None
depends_on = None


def upgrade() -> None:
    try:
        op.execute(
            "CREATE VIRTUAL TABLE question_fts "
            "USING fts5(question_id UNINDEXED, search_text, tokenize='unicode61')"
        )
    except OperationalError as error:
        raise RuntimeError(
            "SQLite FTS5 is required for question search; use a Python SQLite build with FTS5 enabled."
        ) from error

    op.execute(
        "INSERT INTO question_fts(rowid, question_id, search_text) "
        "SELECT id, id, search_text FROM question"
    )
    op.execute(
        """
        CREATE TRIGGER question_fts_after_insert AFTER INSERT ON question BEGIN
            INSERT INTO question_fts(rowid, question_id, search_text)
            VALUES (new.id, new.id, new.search_text);
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER question_fts_after_update AFTER UPDATE OF search_text ON question BEGIN
            DELETE FROM question_fts WHERE rowid = old.id;
            INSERT INTO question_fts(rowid, question_id, search_text)
            VALUES (new.id, new.id, new.search_text);
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER question_fts_after_delete AFTER DELETE ON question BEGIN
            DELETE FROM question_fts WHERE rowid = old.id;
        END
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS question_fts_after_delete")
    op.execute("DROP TRIGGER IF EXISTS question_fts_after_update")
    op.execute("DROP TRIGGER IF EXISTS question_fts_after_insert")
    op.execute("DROP TABLE IF EXISTS question_fts")
