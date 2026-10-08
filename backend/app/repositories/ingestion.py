from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.ingestion import (
    IngestionJob,
    OCRBlock,
    QuestionSource,
    QuestionSourceOCRBlock,
)
from app.models.question import Question


def get_ingestion_job(session: Session, job_id: int) -> IngestionJob | None:
    return session.scalar(
        select(IngestionJob)
        .options(selectinload(IngestionJob.source_asset))
        .where(IngestionJob.id == job_id)
    )


def list_ocr_blocks(session: Session, job_id: int) -> list[OCRBlock]:
    return list(
        session.scalars(
            select(OCRBlock)
            .where(OCRBlock.ingestion_job_id == job_id)
            .order_by(OCRBlock.reading_order, OCRBlock.id)
        )
    )


def list_ingestion_candidates(
    session: Session, job_id: int, *, status_filter: str = "all"
) -> list[Question]:
    statement = (
        select(Question)
        .options(
            selectinload(Question.topic_links),
            selectinload(Question.tag_links),
            selectinload(Question.source_rows)
            .selectinload(QuestionSource.ocr_block_links)
            .selectinload(QuestionSourceOCRBlock.ocr_block),
        )
        .where(Question.origin_ingestion_job_id == job_id)
        .order_by(Question.id)
    )
    if status_filter == "pending_review":
        statement = statement.where(
            Question.ingestion_candidate_state == "pending_review",
            Question.archived_at.is_(None),
        )
    elif status_filter in {"confirmed", "rejected", "superseded"}:
        statement = statement.where(Question.ingestion_candidate_state == status_filter)
    elif status_filter == "archived":
        statement = statement.where(Question.archived_at.is_not(None))
    return list(session.scalars(statement))


def list_candidate_ids_by_parent(
    session: Session, job_id: int, parent_ids: list[int]
) -> dict[int, list[int]]:
    if not parent_ids:
        return {}
    rows = session.execute(
        select(Question.split_from_candidate_id, Question.id)
        .where(
            Question.origin_ingestion_job_id == job_id,
            Question.split_from_candidate_id.in_(parent_ids),
        )
        .order_by(Question.id)
    )
    result: dict[int, list[int]] = {}
    for parent_id, child_id in rows:
        result.setdefault(parent_id, []).append(child_id)
    return result
