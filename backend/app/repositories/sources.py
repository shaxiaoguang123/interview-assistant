from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.ingestion import IngestionJob, SourceAsset


def add_source_asset(session: Session, source_asset: SourceAsset) -> SourceAsset:
    session.add(source_asset)
    session.flush()
    return source_asset


def add_ingestion_job(session: Session, source_asset_id: int) -> IngestionJob:
    job = IngestionJob(source_asset_id=source_asset_id, status="queued", stage="queued")
    session.add(job)
    session.flush()
    return job


def get_source_asset(session: Session, source_asset_id: int) -> SourceAsset | None:
    return session.scalar(
        select(SourceAsset)
        .options(selectinload(SourceAsset.ingestion_jobs))
        .where(SourceAsset.id == source_asset_id)
    )


def list_source_assets(
    session: Session, *, include_archived: bool = False
) -> list[SourceAsset]:
    statement = select(SourceAsset).options(selectinload(SourceAsset.ingestion_jobs))
    if not include_archived:
        statement = statement.where(SourceAsset.archived_at.is_(None))
    return list(
        session.scalars(statement.order_by(SourceAsset.created_at.desc(), SourceAsset.id.desc()))
    )
