"""Canonical history is an aggregate read; stored question IDs stay original."""
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.errors import ApiError
from app.models.ingestion import QuestionSource, QuestionSourceOCRBlock
from app.models.practice import PracticeReview, SessionItem
from app.models.question import Question
from app.repositories.questions import canonical_member_ids


def get_canonical_history(session: Session, question_id: int) -> dict:
    # SQLite legacy SELECT does not start a physical transaction. Hold one
    # coherent snapshot across membership, sources, reviews and session reads.
    connection = session.connection()
    if connection.dialect.name == 'sqlite' and not connection.connection.driver_connection.in_transaction:
        connection.exec_driver_sql('BEGIN')
    question = session.get(Question, question_id)
    if question is None:
        raise ApiError(404, 'NOT_FOUND', 'Question not found')
    canonical_id = question.merged_into_question_id or question.id
    if question.merged_into_question_id is not None:
        root = session.get(Question, canonical_id)
        if root is None or root.status != 'active' or root.merged_into_question_id is not None:
            raise ApiError(409, 'CONFLICT', 'Invalid canonical Question')
    members = canonical_member_ids(session, canonical_id)
    sources = list(session.scalars(select(QuestionSource)
        .options(selectinload(QuestionSource.source_asset),
                 selectinload(QuestionSource.ocr_block_links).selectinload(QuestionSourceOCRBlock.ocr_block))
        .where(QuestionSource.question_id.in_(members)).order_by(QuestionSource.id)))
    reviews = list(session.scalars(select(PracticeReview)
        .where(PracticeReview.question_id.in_(members))
        .order_by(PracticeReview.reviewed_at.desc(), PracticeReview.id.desc())))
    items = list(session.scalars(select(SessionItem).options(selectinload(SessionItem.question))
        .where(SessionItem.question_id.in_(members)).order_by(SessionItem.session_id, SessionItem.ordinal, SessionItem.id)))
    return {'canonical_question_id': canonical_id, 'member_question_ids': members,
            'sources': sources, 'practice_reviews': reviews, 'session_items': items}
