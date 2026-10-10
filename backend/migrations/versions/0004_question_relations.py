"""Add canonical Question pointers and user-reviewed relation candidates."""

from __future__ import annotations

import hashlib

from alembic import op
import sqlalchemy as sa


revision = "0004_question_relations"
down_revision = "0003_phase1b_sources"
branch_labels = None
depends_on = None


def _check_legacy_merged_questions(bind) -> None:
    legacy = bind.execute(
        sa.text(
            "SELECT id FROM question "
            "WHERE status = 'merged' ORDER BY id LIMIT 1"
        )
    ).first()
    if legacy is not None:
        raise RuntimeError(
            "Cannot apply 0004_question_relations: Question "
            f"id={legacy[0]} has status=merged but no canonical pointer. "
            "No Phase 1C schema changes were applied; identify a canonical "
            "target before retrying the upgrade."
        )


def _text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _backfill_exact_hash_suggestions(bind) -> None:
    pairs = bind.execute(
        sa.text(
            """
            SELECT left_question.id AS left_id,
                   left_question.text AS left_text,
                   right_question.id AS right_id,
                   right_question.text AS right_text
            FROM question AS left_question
            JOIN question AS right_question
              ON right_question.normalized_hash = left_question.normalized_hash
             AND right_question.id > left_question.id
            WHERE left_question.status = 'active'
              AND left_question.archived_at IS NULL
              AND right_question.status = 'active'
              AND right_question.archived_at IS NULL
            ORDER BY left_question.id, right_question.id
            """
        )
    ).mappings().all()
    if not pairs:
        return

    insert_relation = sa.text(
        """
        INSERT INTO question_relation (
            question_id,
            related_question_id,
            relation_type,
            decision_status,
            suggested_by,
            confidence,
            question_text_sha256_snapshot,
            related_question_text_sha256_snapshot
        ) VALUES (
            :question_id,
            :related_question_id,
            'same_question',
            'suggested',
            'rule',
            1.0,
            :question_text_sha256_snapshot,
            :related_question_text_sha256_snapshot
        )
        """
    )
    bind.execute(
        insert_relation,
        [
            {
                "question_id": pair["left_id"],
                "related_question_id": pair["right_id"],
                "question_text_sha256_snapshot": _text_sha256(pair["left_text"]),
                "related_question_text_sha256_snapshot": _text_sha256(
                    pair["right_text"]
                ),
            }
            for pair in pairs
        ],
    )


def _create_canonical_pointer_triggers() -> None:
    op.execute(
        """
        CREATE TRIGGER question_merged_pointer_insert
        BEFORE INSERT ON question
        WHEN NEW.merged_into_question_id IS NOT NULL
        BEGIN
            SELECT RAISE(ABORT, 'merged target must be an active canonical root')
            WHERE NOT EXISTS (
                SELECT 1 FROM question AS target
                WHERE target.id = NEW.merged_into_question_id
                  AND target.status = 'active'
                  AND target.merged_into_question_id IS NULL
                  AND target.archived_at IS NULL
            );
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER question_merged_pointer_update
        BEFORE UPDATE OF merged_into_question_id, status ON question
        WHEN NEW.merged_into_question_id IS NOT NULL
        BEGIN
            SELECT RAISE(ABORT, 'merged target must be an active canonical root')
            WHERE NOT EXISTS (
                SELECT 1 FROM question AS target
                WHERE target.id = NEW.merged_into_question_id
                  AND target.status = 'active'
                  AND target.merged_into_question_id IS NULL
                  AND target.archived_at IS NULL
            );
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER question_merge_target_stays_root
        BEFORE UPDATE OF status, merged_into_question_id, archived_at ON question
        WHEN (
                NEW.status <> 'active'
                OR NEW.merged_into_question_id IS NOT NULL
                OR NEW.archived_at IS NOT NULL
             )
         AND EXISTS (
                SELECT 1 FROM question AS child
                WHERE child.merged_into_question_id = OLD.id
            )
        BEGIN
            SELECT RAISE(
                ABORT,
                'repoint merged children before changing their canonical root'
            );
        END
        """
    )


def upgrade() -> None:
    bind = op.get_bind()

    # The 0001 status check allowed 'merged' before Phase 1C had a pointer.
    # Refuse that ambiguous state before any DDL because no target can be inferred.
    _check_legacy_merged_questions(bind)

    # SQLite can add this nullable self-FK and row-local status/self checks
    # without rebuilding Question, so question_fts and its triggers stay intact.
    op.execute(
        """
        ALTER TABLE question
        ADD COLUMN merged_into_question_id INTEGER
            CONSTRAINT fk_question_merged_into_question_id
                REFERENCES question(id) ON DELETE RESTRICT
            CONSTRAINT ck_question_merged_into_status
                CHECK (
                    (status = 'merged'
                     AND merged_into_question_id IS NOT NULL
                     AND merged_into_question_id <> id)
                    OR
                    (status <> 'merged' AND merged_into_question_id IS NULL)
                )
        """
    )
    op.create_index(
        "ix_question_merged_into_question_id",
        "question",
        ["merged_into_question_id"],
    )

    op.create_table(
        "question_relation",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("question_id", sa.Integer(), nullable=False),
        sa.Column("related_question_id", sa.Integer(), nullable=False),
        sa.Column("relation_type", sa.String(length=32), nullable=False),
        sa.Column("decision_status", sa.String(length=24), nullable=False),
        sa.Column("suggested_by", sa.String(length=24), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column(
            "question_text_sha256_snapshot",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "related_question_text_sha256_snapshot",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.ForeignKeyConstraint(
            ["question_id"],
            ["question.id"],
            name="fk_question_relation_question_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["related_question_id"],
            ["question.id"],
            name="fk_question_relation_related_question_id",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "question_id < related_question_id",
            name="ck_question_relation_ascending_pair",
        ),
        sa.CheckConstraint(
            "relation_type IN "
            "('same_question', 'related_question', 'different_question')",
            name="ck_question_relation_type",
        ),
        sa.CheckConstraint(
            "decision_status IN ('suggested', 'accepted', 'rejected')",
            name="ck_question_relation_decision_status",
        ),
        sa.CheckConstraint(
            "suggested_by IN ('rule', 'llm', 'user')",
            name="ck_question_relation_suggested_by",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_question_relation_confidence",
        ),
        sa.CheckConstraint(
            "length(question_text_sha256_snapshot) = 64 "
            "AND question_text_sha256_snapshot NOT GLOB '*[^0-9a-f]*' "
            "AND length(related_question_text_sha256_snapshot) = 64 "
            "AND related_question_text_sha256_snapshot NOT GLOB '*[^0-9a-f]*'",
            name="ck_question_relation_text_sha256",
        ),
        sa.UniqueConstraint(
            "question_id",
            "related_question_id",
            name="uq_question_relation_pair",
        ),
    )
    op.create_index(
        "ix_question_relation_related_question_id",
        "question_relation",
        ["related_question_id"],
    )

    _create_canonical_pointer_triggers()
    _backfill_exact_hash_suggestions(bind)


def downgrade() -> None:
    bind = op.get_bind()
    relation_count = bind.scalar(
        sa.text("SELECT count(*) FROM question_relation")
    )
    merged_count = bind.scalar(
        sa.text(
            "SELECT count(*) FROM question "
            "WHERE merged_into_question_id IS NOT NULL"
        )
    )
    if relation_count or merged_count:
        raise RuntimeError(
            "Cannot downgrade 0004_question_relations while relation or "
            "canonical merge data exists."
        )

    op.execute("DROP TRIGGER IF EXISTS question_merge_target_stays_root")
    op.execute("DROP TRIGGER IF EXISTS question_merged_pointer_update")
    op.execute("DROP TRIGGER IF EXISTS question_merged_pointer_insert")
    op.drop_index(
        "ix_question_relation_related_question_id",
        table_name="question_relation",
    )
    op.drop_table("question_relation")
    op.drop_index(
        "ix_question_merged_into_question_id",
        table_name="question",
    )
    op.drop_column("question", "merged_into_question_id")
