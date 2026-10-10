"""Read-only canonical previews and explicit, atomic user-confirmed merges."""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import re

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.models.ingestion import IngestionJob, OCRBlock, QuestionSource, QuestionSourceOCRBlock
from app.models.question import Question, QuestionRelation, QuestionTag, QuestionTopic
from app.models.taxonomy import Tag, Topic, utc_now
from app.models.saved_answer import SavedAnswer, SavedAnswerVersion
from app.repositories import questions as question_repository
from app.services.ingestion_candidates import _advance_candidate, _get_candidate_sources
from app.services.question_relations import _begin_write
from app.services.question_similarity import _is_active_canonical, _is_pending_ocr_candidate, _text_sha256


def _utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _conflict(message: str) -> ApiError:
    return ApiError(409, 'CONFLICT', message)


def _stale() -> ApiError:
    return ApiError(409, 'MERGE_PREVIEW_STALE', 'Merge preview changed; reload the preview and review again')


def _ids(value: object, field: str) -> list[int]:
    if (not isinstance(value, list) or any(type(item) is not int or item <= 0 for item in value)
            or len(value) != len(set(value))):
        raise ApiError(400, 'VALIDATION_ERROR', f'{field} must be unique positive integer IDs')
    return sorted(value)


def _validate_payload(canonical_id: int, payload: object) -> dict:
    required = {'canonical_id', 'source_question_id', 'relation_id', 'preview_token', 'topic_ids', 'tag_ids'}
    if not isinstance(payload, dict) or not required <= set(payload) or set(payload) - required - {'expected_candidate_revision', 'pinned_answer_id'}:
        raise ApiError(400, 'VALIDATION_ERROR', 'Expected canonical_id, source_question_id, relation_id, preview_token, topic_ids and tag_ids')
    for field in ('canonical_id', 'source_question_id', 'relation_id'):
        if type(payload[field]) is not int or payload[field] <= 0:
            raise ApiError(400, 'VALIDATION_ERROR', f'{field} must be a positive integer')
    if payload['canonical_id'] != canonical_id:
        raise ApiError(400, 'VALIDATION_ERROR', 'canonical_id must match the requested root')
    token = payload['preview_token']
    if not isinstance(token, str) or re.fullmatch(r'[0-9a-f]{64}', token) is None:
        raise ApiError(400, 'VALIDATION_ERROR', 'preview_token is required')
    if 'expected_candidate_revision' in payload:
        revision = payload['expected_candidate_revision']
        if type(revision) is not int or revision < 0:
            raise ApiError(400, 'VALIDATION_ERROR', 'expected_candidate_revision must be a non-negative integer')
    if 'pinned_answer_id' in payload and (type(payload['pinned_answer_id']) is not int or payload['pinned_answer_id'] <= 0):
        raise ApiError(400, 'VALIDATION_ERROR', 'pinned_answer_id must be a positive integer')
    return {**payload, 'topic_ids': _ids(payload['topic_ids'], 'topic_ids'), 'tag_ids': _ids(payload['tag_ids'], 'tag_ids')}


def _members(session: Session, root_id: int) -> list[Question]:
    return list(session.scalars(select(Question).where(or_(
        Question.id == root_id, Question.merged_into_question_id == root_id,
    )).order_by(Question.id)))


def _member_json(session: Session, question: Question) -> dict:
    return {
        'id': question.id, 'text': question.text, 'text_sha256': _text_sha256(question),
        'normalized_hash': question.normalized_hash, 'status': question.status,
        'merged_into_question_id': question.merged_into_question_id,
        'archived_at': _utc(question.archived_at), 'updated_at': _utc(question.updated_at),
        'created_at': _utc(question.created_at), 'answer_type': question.answer_type,
        'difficulty': question.difficulty, 'origin_ingestion_job_id': question.origin_ingestion_job_id,
        'candidate_state': question.ingestion_candidate_state, 'candidate_revision': question.candidate_revision,
        'topic_ids': list(session.scalars(select(QuestionTopic.topic_id).where(
            QuestionTopic.question_id == question.id).order_by(QuestionTopic.topic_id))),
        'tag_ids': list(session.scalars(select(QuestionTag.tag_id).where(
            QuestionTag.question_id == question.id).order_by(QuestionTag.tag_id))),
    }


def _taxonomy_json(row: Topic | Tag) -> dict:
    result = {'id': row.id, 'name': row.name, 'is_active': row.is_active}
    if isinstance(row, Topic):
        result.update(parent_id=row.parent_id, slug=row.slug, track_key=row.track_key, sort_order=row.sort_order)
    return result


def _candidate_state(session: Session, source: Question) -> dict | None:
    if source.origin_ingestion_job_id is None:
        return None
    job = session.get(IngestionJob, source.origin_ingestion_job_id)
    # Evidence fingerprints are part of the token, never rewritten or exposed as paths.
    evidence = []
    for row in session.scalars(select(QuestionSource).where(QuestionSource.question_id == source.id).order_by(QuestionSource.id)):
        blocks = list(session.execute(select(OCRBlock.id, OCRBlock.ingestion_job_id, OCRBlock.text, OCRBlock.bbox_json)
            .join(QuestionSourceOCRBlock, QuestionSourceOCRBlock.ocr_block_id == OCRBlock.id)
            .where(QuestionSourceOCRBlock.question_source_id == row.id).order_by(OCRBlock.id)))
        evidence.append({
            'id': row.id, 'source_asset_id': row.source_asset_id, 'locator_type': row.locator_type,
            'locator': row.locator_json, 'locator_correction': row.locator_correction_json,
            'source_text_digest': sha256(row.source_text_snapshot.encode()).hexdigest(),
            'raw_ocr_digest': sha256(row.raw_ocr_text_snapshot.encode()).hexdigest(),
            'blocks': [{'id': b.id, 'job_id': b.ingestion_job_id, 'digest': sha256(b.text.encode()).hexdigest(), 'bbox': b.bbox_json} for b in blocks],
        })
    return {'job': {'id': job.id, 'status': job.status, 'stage': job.stage, 'source_asset_id': job.source_asset_id} if job else None,
            'evidence': evidence}


def _collect(session: Session, canonical_id: int, source_id: int, relation_id: int | None = None):
    target, source = session.get(Question, canonical_id), session.get(Question, source_id)
    if target is None or source is None:
        raise ApiError(404, 'NOT_FOUND', 'Merge Question not found')
    target_group, source_group = _members(session, canonical_id), _members(session, source_id)
    if relation_id is None:
        left, right = sorted((canonical_id, source_id))
        relation = session.scalar(select(QuestionRelation).where(
            QuestionRelation.question_id == left, QuestionRelation.related_question_id == right))
    else:
        relation = session.get(QuestionRelation, relation_id)
    target_members = [_member_json(session, row) for row in target_group]
    source_members = [_member_json(session, row) for row in source_group]
    all_members = target_members + source_members
    topic_ids = {item for row in all_members for item in row['topic_ids']}
    tag_ids = {item for row in all_members for item in row['tag_ids']}
    topics = [_taxonomy_json(t) for t in session.scalars(select(Topic).order_by(Topic.id))]
    tags = [_taxonomy_json(t) for t in session.scalars(select(Tag).order_by(Tag.id))]
    state = {
        'canonical_id': canonical_id, 'source_question_id': source_id,
        'canonical_question': next(q for q in target_members if q['id'] == canonical_id),
        'source_question': next(q for q in source_members if q['id'] == source_id),
        'target_members': target_members, 'source_members': source_members,
        'topic_union': [t for t in topics if t['id'] in topic_ids],
        'tag_union': [t for t in tags if t['id'] in tag_ids],
        # Include the selectable catalogue too: a label/active change cannot hide
        # behind a selection that was outside the initial union.
        'available_topics': [t for t in topics if t['is_active'] or t['id'] in topic_ids],
        'available_tags': [t for t in tags if t['is_active'] or t['id'] in tag_ids],
        'expected_candidate_revision': source.candidate_revision if _is_pending_ocr_candidate(source) else None,
        'relation': {
            'id': relation.id, 'question_id': relation.question_id, 'related_question_id': relation.related_question_id,
            'relation_type': relation.relation_type, 'decision_status': relation.decision_status,
            'suggested_by': relation.suggested_by, 'confidence': relation.confidence,
            'question_text_sha256_snapshot': relation.question_text_sha256_snapshot,
            'related_question_text_sha256_snapshot': relation.related_question_text_sha256_snapshot,
            'created_at': _utc(relation.created_at), 'updated_at': _utc(relation.updated_at),
        } if relation else None,
        'candidate_provenance': _candidate_state(session, source),
    }
    pinned = list(session.scalars(select(SavedAnswer).where(
        SavedAnswer.question_id.in_([q['id'] for q in all_members]),
        SavedAnswer.is_pinned.is_(True), SavedAnswer.archived_at.is_(None)).order_by(SavedAnswer.id)))
    state['pinned_answers'] = []
    for answer in pinned:
        version = session.scalar(select(SavedAnswerVersion).where(SavedAnswerVersion.saved_answer_id == answer.id)
                                 .order_by(SavedAnswerVersion.version_no.desc()).limit(1))
        state['pinned_answers'].append({'id': answer.id, 'question_id': answer.question_id,
            'content': version.content, 'version_no': version.version_no, 'updated_at': _utc(answer.updated_at)})
    return state, target, source, relation, source_group


def _token(state: dict) -> str:
    return sha256(json.dumps(state, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def _validate_state(session: Session, state: dict, target: Question, source: Question, relation: QuestionRelation | None) -> None:
    if target.id == source.id:
        raise _conflict('Cannot merge a Question into itself')
    if not _is_active_canonical(target):
        raise _conflict('Target must be an active, unarchived canonical root')
    if not (_is_active_canonical(source) or _is_pending_ocr_candidate(source)) or source.merged_into_question_id is not None:
        raise _conflict('Source must be an active canonical root or pending OCR candidate')
    target_ids = {q['id'] for q in state['target_members']}
    source_ids = {q['id'] for q in state['source_members']}
    if target_ids & source_ids:
        raise _conflict('Canonical groups must not overlap or form a cycle')
    for group, root in ((state['target_members'], target.id), (state['source_members'], source.id)):
        if any(q['id'] != root and (q['status'] != 'merged' or q['merged_into_question_id'] != root) for q in group):
            raise _conflict('Invalid canonical group')
    if relation is None or {relation.question_id, relation.related_question_id} != {target.id, source.id}:
        raise _conflict('Merge requires a relation connecting the selected roots')
    if (relation.relation_type, relation.decision_status, relation.suggested_by) != ('same_question', 'accepted', 'user'):
        raise _conflict('Merge requires an explicitly user-accepted same_question relation')
    left, right = (target, source) if target.id < source.id else (source, target)
    if (relation.question_text_sha256_snapshot != _text_sha256(left)
            or relation.related_question_text_sha256_snapshot != _text_sha256(right)):
        raise _conflict('Relation text snapshots changed; rescan and review again')
    if _is_pending_ocr_candidate(source):
        job = session.get(IngestionJob, source.origin_ingestion_job_id)
        if job is None or job.status != 'succeeded' or job.stage != 'completed':
            raise _conflict('OCR merge requires a completed successful job')
        sources = _get_candidate_sources(session, source, job)
        if not sources or any(not row.ocr_block_links for row in sources):
            raise _conflict('OCR merge requires original source and block evidence')


def preview_question_merge(session: Session, canonical_id: int, source_question_id: int) -> dict:
    # Obtain a coherent read snapshot even with sqlite3's legacy SELECT behavior.
    # Join a caller's transaction if already active; never nest Session.begin().
    connection = session.connection()
    if connection.dialect.name == 'sqlite' and not connection.connection.driver_connection.in_transaction:
        connection.exec_driver_sql('BEGIN')
    state, target, source, relation, _ = _collect(session, canonical_id, source_question_id)
    _validate_state(session, state, target, source, relation)
    return {**state, 'preview_token': _token(state)}


def _validate_selection(session: Session, model, selected: list[int], union: list[dict], field: str) -> None:
    union_ids = {row['id'] for row in union}
    rows = list(session.scalars(select(model).where(model.id.in_(selected))))
    if len(rows) != len(selected) or any(not row.is_active and row.id not in union_ids for row in rows):
        raise ApiError(400, 'VALIDATION_ERROR', 'New classifications must be active; inactive union labels may be kept or omitted', {field: 'Invalid or inactive IDs'})


def merge_question(session: Session, canonical_id: int, payload: object) -> Question:
    data = _validate_payload(canonical_id, payload)
    try:
        with session.begin():
            _begin_write(session)  # Before every state-dependent SELECT.
            state, target, source, relation, source_group = _collect(session, canonical_id, data['source_question_id'], data['relation_id'])
            if _token(state) != data['preview_token']:
                raise _stale()
            _validate_state(session, state, target, source, relation)
            pending = _is_pending_ocr_candidate(source)
            if pending:
                if 'expected_candidate_revision' not in data:
                    raise ApiError(400, 'VALIDATION_ERROR', 'expected_candidate_revision is required for OCR candidates')
                if data['expected_candidate_revision'] != source.candidate_revision:
                    raise _stale()
            elif 'expected_candidate_revision' in data:
                raise ApiError(400, 'VALIDATION_ERROR', 'expected_candidate_revision only applies to a pending OCR candidate')
            _validate_selection(session, Topic, data['topic_ids'], state['topic_union'], 'topic_ids')
            _validate_selection(session, Tag, data['tag_ids'], state['tag_union'], 'tag_ids')
            pinned_ids = {a['id'] for a in state['pinned_answers']}
            selected_pin = data.get('pinned_answer_id')
            if len(pinned_ids) > 1 and selected_pin is None:
                raise ApiError(400, 'VALIDATION_ERROR', 'Select one pinned answer to keep before merging')
            if selected_pin is not None and selected_pin not in pinned_ids:
                raise ApiError(400, 'VALIDATION_ERROR', 'Selected pinned answer is not in this preview')
            if selected_pin is not None:
                for answer in session.scalars(select(SavedAnswer).where(SavedAnswer.id.in_(pinned_ids - {selected_pin}))):
                    answer.is_pinned = False
                    answer.updated_at = utc_now()
                session.flush()
            question_repository.replace_question_topics(session, target.id, data['topic_ids'])
            question_repository.replace_question_tags(session, target.id, data['tag_ids'])
            session.flush()
            # 0004 forbids a root changing until every old child is repointed.
            child_ids = [row.id for row in source_group if row.id != source.id]
            if child_ids:
                session.execute(update(Question).where(Question.id.in_(child_ids)).values(
                    merged_into_question_id=target.id).execution_options(synchronize_session='fetch'))
            if pending:
                _advance_candidate(session, source, data['expected_candidate_revision'], values={
                    'status': 'merged', 'merged_into_question_id': target.id, 'ingestion_candidate_state': 'confirmed',
                })
            else:
                source.status = 'merged'
                source.merged_into_question_id = target.id
            target.updated_at = utc_now()
            session.flush()
            session.expire(target, ['topic_links', 'tag_links'])
            result = question_repository.get_question(session, target.id)
        return result
    except IntegrityError as error:
        raise _conflict('Canonical merge could not be saved; reload before retrying') from error
