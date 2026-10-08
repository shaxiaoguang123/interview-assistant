"""Add local screenshot sources, OCR runs, and question provenance."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0003_phase1b_sources"
down_revision = "0002_question_search"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "source_asset",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source_type", sa.String(length=32), nullable=False, server_default="image"),
        sa.Column("platform", sa.String(length=80), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("external_id", sa.String(length=240), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("author", sa.String(length=240), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("original_filename", sa.String(length=512), nullable=True),
        sa.Column("mime_type", sa.String(length=120), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("original_width", sa.Integer(), nullable=False),
        sa.Column("original_height", sa.Integer(), nullable=False),
        sa.Column("display_width", sa.Integer(), nullable=False),
        sa.Column("display_height", sa.Integer(), nullable=False),
        sa.Column("original_path", sa.String(length=512), nullable=False),
        sa.Column("display_preview_path", sa.String(length=512), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "metadata_json",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint("byte_size >= 0", name="ck_source_asset_byte_size"),
        sa.CheckConstraint(
            "original_width > 0 AND original_height > 0 "
            "AND display_width > 0 AND display_height > 0",
            name="ck_source_asset_dimensions",
        ),
    )
    op.create_index("ix_source_asset_sha256", "source_asset", ["sha256"], unique=False)
    op.create_index("ix_source_asset_archived_at", "source_asset", ["archived_at"])

    op.create_table(
        "ingestion_job",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "source_asset_id",
            sa.Integer(),
            sa.ForeignKey("source_asset.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="queued"),
        sa.Column("stage", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("failure_stage", sa.String(length=32), nullable=True),
        sa.Column("engine", sa.String(length=120), nullable=True),
        sa.Column("engine_version", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("candidate_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name="ck_ingestion_job_status",
        ),
        sa.CheckConstraint(
            "stage IN ('queued', 'initializing_adapter', 'recognizing', "
            "'building_candidates', 'persisting_results', 'completed')",
            name="ck_ingestion_job_stage",
        ),
        sa.CheckConstraint("candidate_count >= 0", name="ck_ingestion_job_candidate_count"),
    )
    op.create_index("ix_ingestion_job_source_asset_id", "ingestion_job", ["source_asset_id"])
    op.create_index(
        "ix_ingestion_job_source_status",
        "ingestion_job",
        ["source_asset_id", "status"],
    )

    op.create_table(
        "ocr_block",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "ingestion_job_id",
            sa.Integer(),
            sa.ForeignKey("ingestion_job.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("bbox_json", sa.JSON(), nullable=False),
        sa.Column("reading_order", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("block_type", sa.String(length=32), nullable=False, server_default="text"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_ocr_block_confidence",
        ),
    )
    op.create_index("ix_ocr_block_ingestion_job_id", "ocr_block", ["ingestion_job_id"])
    op.create_index(
        "ix_ocr_block_job_reading_order",
        "ocr_block",
        ["ingestion_job_id", "reading_order"],
    )

    op.create_table(
        "question_source",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "question_id",
            sa.Integer(),
            sa.ForeignKey("question.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "source_asset_id",
            sa.Integer(),
            sa.ForeignKey("source_asset.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("locator_type", sa.String(length=40), nullable=False, server_default="image_region"),
        sa.Column("locator_json", sa.JSON(), nullable=False),
        sa.Column("locator_correction_json", sa.JSON(), nullable=True),
        sa.Column("source_text_snapshot", sa.Text(), nullable=False),
        sa.Column("raw_ocr_text_snapshot", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_question_source_confidence",
        ),
    )
    op.create_index("ix_question_source_question_id", "question_source", ["question_id"])
    op.create_index(
        "ix_question_source_source_asset_id", "question_source", ["source_asset_id"]
    )

    op.create_table(
        "question_source_ocr_block",
        sa.Column(
            "question_source_id",
            sa.Integer(),
            sa.ForeignKey("question_source.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "ocr_block_id",
            sa.String(length=36),
            sa.ForeignKey("ocr_block.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "question_source_id",
            "ocr_block_id",
            name="pk_question_source_ocr_block",
        ),
    )
    op.create_index(
        "ix_question_source_ocr_block_ocr_block_id",
        "question_source_ocr_block",
        ["ocr_block_id"],
    )

    # SQLite permits adding nullable/referential columns without rebuilding the
    # Question table, so the existing FTS5 table and its triggers stay intact.
    op.execute(
        "ALTER TABLE question ADD COLUMN origin_ingestion_job_id INTEGER "
        "REFERENCES ingestion_job(id) ON DELETE RESTRICT"
    )
    op.execute(
        "ALTER TABLE question ADD COLUMN ingestion_candidate_state VARCHAR(24) "
        "CHECK (ingestion_candidate_state IS NULL OR ingestion_candidate_state IN "
        "('pending_review', 'confirmed', 'rejected', 'superseded'))"
    )
    op.execute(
        "ALTER TABLE question ADD COLUMN candidate_revision INTEGER NOT NULL "
        "DEFAULT 0 CHECK (candidate_revision >= 0)"
    )
    op.execute(
        "ALTER TABLE question ADD COLUMN split_from_candidate_id INTEGER "
        "REFERENCES question(id) ON DELETE RESTRICT "
        "CHECK (split_from_candidate_id IS NULL OR "
        "(origin_ingestion_job_id IS NOT NULL AND split_from_candidate_id <> id))"
    )
    op.execute(
        "ALTER TABLE question ADD COLUMN superseded_by_candidate_id INTEGER "
        "REFERENCES question(id) ON DELETE RESTRICT "
        "CHECK (superseded_by_candidate_id IS NULL OR "
        "(origin_ingestion_job_id IS NOT NULL AND superseded_by_candidate_id <> id))"
    )
    op.create_index(
        "ix_question_origin_ingestion_job_id", "question", ["origin_ingestion_job_id"]
    )
    op.create_index(
        "ix_question_split_from_candidate_id", "question", ["split_from_candidate_id"]
    )
    op.create_index(
        "ix_question_superseded_by_candidate_id",
        "question",
        ["superseded_by_candidate_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_question_superseded_by_candidate_id", table_name="question")
    op.drop_index("ix_question_split_from_candidate_id", table_name="question")
    op.drop_index("ix_question_origin_ingestion_job_id", table_name="question")
    op.drop_column("question", "superseded_by_candidate_id")
    op.drop_column("question", "split_from_candidate_id")
    op.drop_column("question", "candidate_revision")
    op.drop_column("question", "ingestion_candidate_state")
    op.drop_column("question", "origin_ingestion_job_id")

    op.drop_index(
        "ix_question_source_ocr_block_ocr_block_id",
        table_name="question_source_ocr_block",
    )
    op.drop_table("question_source_ocr_block")
    op.drop_index("ix_question_source_source_asset_id", table_name="question_source")
    op.drop_index("ix_question_source_question_id", table_name="question_source")
    op.drop_table("question_source")
    op.drop_index("ix_ocr_block_job_reading_order", table_name="ocr_block")
    op.drop_index("ix_ocr_block_ingestion_job_id", table_name="ocr_block")
    op.drop_table("ocr_block")
    op.drop_index("ix_ingestion_job_source_status", table_name="ingestion_job")
    op.drop_index("ix_ingestion_job_source_asset_id", table_name="ingestion_job")
    op.drop_table("ingestion_job")
    op.drop_index("ix_source_asset_archived_at", table_name="source_asset")
    op.drop_index("ix_source_asset_sha256", table_name="source_asset")
    op.drop_table("source_asset")
