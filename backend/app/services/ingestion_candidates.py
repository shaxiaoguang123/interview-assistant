from __future__ import annotations

from datetime import datetime, timezone
import math
import re

from sqlalchemy import select, update
from sqlalchemy.orm import Session, selectinload

from app.errors import ApiError
from app.models.ingestion import (
    IngestionJob,
    OCRBlock,
    QuestionSource,
    QuestionSourceOCRBlock,
)
from app.models.question import (
    Question,
    QuestionState,
    QuestionTag,
    QuestionTopic,
)
from app.repositories import questions as question_repository
from app.services.questions import prepare_question_text
from app.services.question_similarity import (
    invalidate_unmerged_question_relations,
    refresh_rule_suggestions,
    unresolved_same_question_relations,
)
from app.services.taxonomy import validate_active_tag_ids, validate_active_topic_ids


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _validation(field: str, message: str) -> ApiError:
    return ApiError(400, "VALIDATION_ERROR", "Invalid OCR candidate", {field: message})


def _expected_revision(payload: dict) -> int:
    value = payload.get("expected_revision")
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _validation("expected_revision", "Must be a non-negative integer")
    return value


def _load_candidate(
    session: Session,
    candidate_id: int,
    *,
    job_id: int | None = None,
) -> Question:
    statement = (
        select(Question)
        .options(
            selectinload(Question.source_rows)
            .selectinload(QuestionSource.ocr_block_links)
            .selectinload(QuestionSourceOCRBlock.ocr_block)
        )
        .where(Question.id == candidate_id)
    )
    candidate = session.scalar(statement)
    if candidate is None or candidate.origin_ingestion_job_id is None:
        raise ApiError(404, "NOT_FOUND", "OCR candidate not found")
    if job_id is not None and candidate.origin_ingestion_job_id != job_id:
        raise _validation("job_id", "Candidate must belong to the requested ingestion job")
    return candidate


def _require_pending(candidate: Question, expected_revision: int) -> None:
    if (
        candidate.status != "pending_review"
        or candidate.ingestion_candidate_state != "pending_review"
        or candidate.archived_at is not None
        or candidate.candidate_revision != expected_revision
    ):
        raise ApiError(409, "CONFLICT", "OCR candidate changed; reload it before editing")


def _advance_candidate(
    session: Session,
    candidate: Question,
    expected_revision: int,
    *,
    values: dict | None = None,
) -> None:
    fields = {"candidate_revision": expected_revision + 1}
    if values:
        fields.update(values)
    result = session.execute(
        update(Question)
        .where(
            Question.id == candidate.id,
            Question.origin_ingestion_job_id == candidate.origin_ingestion_job_id,
            Question.status == "pending_review",
            Question.ingestion_candidate_state == "pending_review",
            Question.archived_at.is_(None),
            Question.candidate_revision == expected_revision,
        )
        .values(**fields)
        .execution_options(synchronize_session="fetch")
    )
    if result.rowcount != 1:
        raise ApiError(409, "CONFLICT", "OCR candidate changed; reload it before editing")
    session.flush()
    session.expire(candidate)


def _begin_confirmation_write_transaction(session: Session) -> None:
    """Serialize similarity validation with candidate promotion on SQLite.

    Python's sqlite3 legacy transaction mode does not begin a database
    transaction for SELECT statements. Acquiring the write reservation before
    reading the candidate and its relation targets prevents another
    confirmation from passing the same eligibility check concurrently.
    """
    connection = session.connection()
    if connection.dialect.name == "sqlite":
        connection.exec_driver_sql("BEGIN IMMEDIATE")


def _parse_locator(value: object, field: str) -> dict[str, float] | None:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {"x", "y", "width", "height"}:
        raise _validation(field, "Must contain x, y, width, and height")
    result: dict[str, float] = {}
    for key in ("x", "y", "width", "height"):
        number = value[key]
        if isinstance(number, bool) or not isinstance(number, (int, float)):
            raise _validation(field, "Coordinates must be finite numbers")
        number = float(number)
        if not math.isfinite(number):
            raise _validation(field, "Coordinates must be finite numbers")
        result[key] = number
    if (
        result["x"] < 0
        or result["y"] < 0
        or result["width"] <= 0
        or result["height"] <= 0
        or result["x"] > 1
        or result["y"] > 1
        or result["width"] > 1
        or result["height"] > 1
        or result["x"] + result["width"] > 1
        or result["y"] + result["height"] > 1
    ):
        raise _validation(field, "Coordinates must fit within normalized image bounds")
    return result


def _source_locator_text_is_cited(source_text: str, raw_text: str) -> bool:
    excerpt = re.sub(r"\s+", " ", source_text).strip()
    original = re.sub(r"\s+", " ", raw_text).strip()
    return bool(excerpt) and excerpt in original


def _get_candidate_sources(
    session: Session,
    candidate: Question,
    job: IngestionJob,
) -> list[QuestionSource]:
    sources = list(
        session.scalars(
            select(QuestionSource)
            .options(
                selectinload(QuestionSource.ocr_block_links)
                .selectinload(QuestionSourceOCRBlock.ocr_block)
            )
            .where(QuestionSource.question_id == candidate.id)
            .order_by(QuestionSource.id)
        )
    )
    for source in sources:
        if source.source_asset_id != job.source_asset_id:
            raise _validation(
                "source_locator_corrections",
                "QuestionSource does not belong to this candidate's source image",
            )
        for link in source.ocr_block_links:
            if link.ocr_block.ingestion_job_id != job.id:
                raise _validation(
                    "source_locator_corrections",
                    "QuestionSource contains an OCR block from another job",
                )
    return sources


def _source_row_for_candidate(
    sources: list[QuestionSource],
    source_id: object,
) -> QuestionSource:
    if isinstance(source_id, bool) or not isinstance(source_id, int):
        raise _validation("source_locator_corrections", "question_source_id must be an integer")
    source = next((row for row in sources if row.id == source_id), None)
    if source is None:
        raise _validation(
            "source_locator_corrections",
            "QuestionSource does not belong to this candidate, job, and source image",
        )
    return source


def _selection_matches_current(value: object, current_ids: set[int]) -> bool:
    if not isinstance(value, list):
        return False
    if any(isinstance(item, bool) or not isinstance(item, int) or item <= 0 for item in value):
        return False
    return len(value) == len(set(value)) and set(value) == current_ids


def create_candidate_from_ocr_blocks(
    session: Session,
    job_id: int,
    payload: object,
) -> Question:
    if not isinstance(payload, dict):
        raise _validation("body", "Expected a JSON object")
    allowed = {"ocr_block_ids", "text"}
    unknown = set(payload) - allowed
    if unknown:
        raise _validation("body", f"Unsupported fields: {', '.join(sorted(unknown))}")
    block_ids = payload.get("ocr_block_ids")
    if (
        not isinstance(block_ids, list)
        or not block_ids
        or any(not isinstance(block_id, str) for block_id in block_ids)
        or len(set(block_ids)) != len(block_ids)
    ):
        raise _validation("ocr_block_ids", "Must be a non-empty list of unique OCR block IDs")

    with session.begin():
        job = session.get(IngestionJob, job_id)
        if job is None:
            raise ApiError(404, "NOT_FOUND", "Ingestion job not found")
        if job.status != "succeeded" or job.stage != "completed":
            raise ApiError(409, "CONFLICT", "Candidates can only be added to a completed OCR job")

        blocks = list(
            session.scalars(
                select(OCRBlock)
                .where(
                    OCRBlock.ingestion_job_id == job_id,
                    OCRBlock.id.in_(block_ids),
                )
                .order_by(OCRBlock.reading_order, OCRBlock.id)
            )
        )
        if len(blocks) != len(block_ids):
            raise _validation("ocr_block_ids", "Every OCR block must belong to this ingestion job")
        source_text = "\n".join(block.text for block in blocks)
        prepared_text = prepare_question_text(payload.get("text", source_text))

        boxes = [block.bbox_json for block in blocks]
        left = min(box["x"] for box in boxes)
        top = min(box["y"] for box in boxes)
        right = max(box["x"] + box["width"] for box in boxes)
        bottom = max(box["y"] + box["height"] for box in boxes)
        confidences = [block.confidence for block in blocks if block.confidence is not None]
        question = Question(
            text=prepared_text[0],
            normalized_text=prepared_text[1],
            search_text=prepared_text[1],
            normalized_hash=prepared_text[2],
            status="pending_review",
            origin_ingestion_job_id=job_id,
            ingestion_candidate_state="pending_review",
            candidate_revision=0,
        )
        session.add(question)
        session.flush()

        source = QuestionSource(
            question_id=question.id,
            source_asset_id=job.source_asset_id,
            locator_type="image_region",
            locator_json={
                "x": left,
                "y": top,
                "width": right - left,
                "height": bottom - top,
            },
            source_text_snapshot=source_text,
            raw_ocr_text_snapshot=source_text,
            confidence=sum(confidences) / len(confidences) if confidences else None,
        )
        session.add(source)
        session.flush()
        session.add_all(
            [
                QuestionSourceOCRBlock(
                    question_source_id=source.id,
                    ocr_block_id=block.id,
                )
                for block in blocks
            ]
        )
        session.flush()
        refresh_rule_suggestions(session, question.id)
        candidate_id = question.id

    return question_repository.get_question(session, candidate_id)


def patch_ingestion_candidate(
    session: Session,
    candidate_id: int,
    payload: object,
) -> Question:
    if not isinstance(payload, dict) or not payload:
        raise _validation("body", "Expected a non-empty JSON object")
    allowed = {
        "expected_revision",
        "text",
        "topic_ids",
        "tag_ids",
        "source_locator_corrections",
    }
    unknown = set(payload) - allowed
    if unknown:
        raise _validation("body", f"Unsupported fields: {', '.join(sorted(unknown))}")
    expected_revision = _expected_revision(payload)
    corrections = payload.get("source_locator_corrections", [])
    if not isinstance(corrections, list):
        raise _validation("source_locator_corrections", "Must be a list")

    with session.begin():
        candidate = _load_candidate(session, candidate_id)
        _require_pending(candidate, expected_revision)
        job = session.get(IngestionJob, candidate.origin_ingestion_job_id)
        if job is None:
            raise ApiError(404, "NOT_FOUND", "Candidate ingestion job not found")
        sources = _get_candidate_sources(session, candidate, job)

        parsed_corrections: list[tuple[QuestionSource, dict | None]] = []
        correction_source_ids: set[int] = set()
        for index, correction in enumerate(corrections):
            if not isinstance(correction, dict) or set(correction) != {
                "question_source_id",
                "locator_correction_json",
            }:
                raise _validation(
                    f"source_locator_corrections[{index}]",
                    "Expected question_source_id and locator_correction_json",
                )
            source = _source_row_for_candidate(sources, correction["question_source_id"])
            if source.id in correction_source_ids:
                raise _validation(
                    f"source_locator_corrections[{index}].question_source_id",
                    "QuestionSource may be corrected only once per request",
                )
            correction_source_ids.add(source.id)
            locator = _parse_locator(
                correction["locator_correction_json"],
                f"source_locator_corrections[{index}].locator_correction_json",
            )
            parsed_corrections.append((source, locator))

        topics = None
        tags = None
        if "topic_ids" in payload:
            current_topic_ids = {link.topic_id for link in candidate.topic_links}
            if not _selection_matches_current(payload["topic_ids"], current_topic_ids):
                topics = validate_active_topic_ids(session, payload["topic_ids"])
                if {topic.id for topic in topics} == current_topic_ids:
                    topics = None
        if "tag_ids" in payload:
            current_tag_ids = {link.tag_id for link in candidate.tag_links}
            if not _selection_matches_current(payload["tag_ids"], current_tag_ids):
                tags = validate_active_tag_ids(session, payload["tag_ids"])
                if {tag.id for tag in tags} == current_tag_ids:
                    tags = None
        prepared_text = None
        if "text" in payload:
            prepared_text = prepare_question_text(payload["text"])
            current_text = (
                candidate.text,
                candidate.normalized_text,
                candidate.normalized_hash,
            )
            if prepared_text == current_text and candidate.search_text == prepared_text[1]:
                prepared_text = None
        parsed_corrections = [
            (source, locator)
            for source, locator in parsed_corrections
            if locator != source.locator_correction_json
            and not (source.locator_correction_json is None and locator == source.locator_json)
        ]

        if prepared_text is None and topics is None and tags is None and not parsed_corrections:
            return question_repository.get_question(session, candidate_id)

        text_changed = prepared_text is not None
        _advance_candidate(session, candidate, expected_revision)
        candidate = session.get(Question, candidate_id)
        if prepared_text is not None:
            candidate.text, candidate.normalized_text, candidate.normalized_hash = prepared_text
            candidate.search_text = candidate.normalized_text
        if topics is not None:
            question_repository.replace_question_topics(
                session, candidate.id, [topic.id for topic in topics]
            )
            session.expire(candidate, ["topic_links"])
        if tags is not None:
            question_repository.replace_question_tags(
                session, candidate.id, [tag.id for tag in tags]
            )
            session.expire(candidate, ["tag_links"])
        for source, locator in parsed_corrections:
            source.locator_correction_json = locator
        session.flush()
        if text_changed:
            refresh_rule_suggestions(session, candidate.id)
        session.expire(candidate)

    return question_repository.get_question(session, candidate_id)


def _block_map_for_candidate(
    session: Session, candidate: Question, job: IngestionJob
) -> tuple[dict[str, OCRBlock], set[str]]:
    source_rows = _get_candidate_sources(session, candidate, job)
    cited_ids = {
        link.ocr_block_id
        for source in source_rows
        for link in source.ocr_block_links
    }
    blocks = list(
        session.scalars(
            select(OCRBlock).where(
                OCRBlock.ingestion_job_id == job.id,
                OCRBlock.id.in_(cited_ids) if cited_ids else False,
            )
        )
    )
    return {block.id: block for block in blocks}, cited_ids


def _parse_split_parts(
    raw_parts: object,
    block_map: dict[str, OCRBlock],
    cited_ids: set[str],
) -> list[dict]:
    if not isinstance(raw_parts, list) or len(raw_parts) < 2:
        raise _validation("parts", "Split requires at least two parts")
    parts = []
    for index, part in enumerate(raw_parts):
        field = f"parts[{index}]"
        if not isinstance(part, dict):
            raise _validation(field, "Must be an object")
        allowed = {
            "text",
            "ocr_block_ids",
            "source_text_snapshot",
            "locator_correction_json",
        }
        if set(part) - allowed:
            raise _validation(field, "Contains unsupported fields")
        question_text, normalized_text, normalized_hash = prepare_question_text(part.get("text"))
        block_ids = part.get("ocr_block_ids")
        if (
            not isinstance(block_ids, list)
            or not block_ids
            or any(not isinstance(block_id, str) for block_id in block_ids)
            or len(set(block_ids)) != len(block_ids)
        ):
            raise _validation(f"{field}.ocr_block_ids", "Must be a non-empty list of unique OCR block IDs")
        if any(block_id not in cited_ids or block_id not in block_map for block_id in block_ids):
            raise _validation(f"{field}.ocr_block_ids", "OCR block must be cited by this candidate and job")
        source_text = part.get("source_text_snapshot")
        if not isinstance(source_text, str):
            raise _validation(f"{field}.source_text_snapshot", "Must be text from the source OCR blocks")
        raw_text = "\n".join(block_map[block_id].text for block_id in block_ids)
        if not _source_locator_text_is_cited(source_text, raw_text):
            raise _validation(f"{field}.source_text_snapshot", "Excerpt is not present in selected OCR blocks")

        boxes = [block_map[block_id].bbox_json for block_id in block_ids]
        left = min(box["x"] for box in boxes)
        top = min(box["y"] for box in boxes)
        right = max(box["x"] + box["width"] for box in boxes)
        bottom = max(box["y"] + box["height"] for box in boxes)
        locator = {
            "x": left,
            "y": top,
            "width": right - left,
            "height": bottom - top,
        }
        correction = (
            _parse_locator(part.get("locator_correction_json"), f"{field}.locator_correction_json")
            if "locator_correction_json" in part
            else None
        )
        confidence_values = [
            block_map[block_id].confidence
            for block_id in block_ids
            if block_map[block_id].confidence is not None
        ]
        parts.append(
            {
                "text": question_text,
                "normalized_text": normalized_text,
                "normalized_hash": normalized_hash,
                "block_ids": block_ids,
                "source_text_snapshot": source_text,
                "raw_ocr_text_snapshot": raw_text,
                "locator": locator,
                "locator_correction_json": correction,
                "confidence": (
                    sum(confidence_values) / len(confidence_values)
                    if confidence_values
                    else None
                ),
            }
        )
    return parts


def split_ingestion_candidate(
    session: Session,
    job_id: int,
    candidate_id: int,
    payload: object,
) -> list[int]:
    if not isinstance(payload, dict):
        raise _validation("body", "Expected a JSON object")
    expected_revision = _expected_revision(payload)
    allowed = {"expected_revision", "parts"}
    if set(payload) - allowed:
        raise _validation("body", "Contains unsupported fields")
    with session.begin():
        candidate = _load_candidate(session, candidate_id, job_id=job_id)
        _require_pending(candidate, expected_revision)
        job = session.get(IngestionJob, job_id)
        if job is None:
            raise ApiError(404, "NOT_FOUND", "Candidate ingestion job not found")
        block_map, cited_ids = _block_map_for_candidate(session, candidate, job)
        parts = _parse_split_parts(payload.get("parts"), block_map, cited_ids)

        _advance_candidate(
            session,
            candidate,
            expected_revision,
            values={
                "archived_at": _now(),
                "ingestion_candidate_state": "superseded",
            },
        )
        invalidate_unmerged_question_relations(session, candidate.id)

        children: list[Question] = []
        for part in parts:
            child = Question(
                text=part["text"],
                normalized_text=part["normalized_text"],
                search_text=part["normalized_text"],
                normalized_hash=part["normalized_hash"],
                status="pending_review",
                origin_ingestion_job_id=job_id,
                ingestion_candidate_state="pending_review",
                candidate_revision=0,
                split_from_candidate_id=candidate_id,
            )
            session.add(child)
            session.flush()
            question_source = QuestionSource(
                question_id=child.id,
                source_asset_id=job.source_asset_id,
                locator_type="image_region",
                locator_json=part["locator"],
                locator_correction_json=part["locator_correction_json"],
                source_text_snapshot=part["source_text_snapshot"],
                raw_ocr_text_snapshot=part["raw_ocr_text_snapshot"],
                confidence=part["confidence"],
            )
            session.add(question_source)
            session.flush()
            session.add_all(
                [
                    QuestionSourceOCRBlock(
                        question_source_id=question_source.id,
                        ocr_block_id=block_id,
                    )
                    for block_id in part["block_ids"]
                ]
            )
            session.flush()
            refresh_rule_suggestions(session, child.id)
            children.append(child)
        session.flush()
        return [child.id for child in children]


def _copy_question_source(
    session: Session,
    source: QuestionSource,
    survivor_id: int,
    job: IngestionJob,
) -> None:
    links = list(
        session.scalars(
            select(QuestionSourceOCRBlock)
            .join(OCRBlock, OCRBlock.id == QuestionSourceOCRBlock.ocr_block_id)
            .where(
                QuestionSourceOCRBlock.question_source_id == source.id,
                OCRBlock.ingestion_job_id == job.id,
            )
        )
    )
    all_links = list(
        session.scalars(
            select(QuestionSourceOCRBlock).where(
                QuestionSourceOCRBlock.question_source_id == source.id
            )
        )
    )
    if len(links) != len(all_links):
        raise _validation("candidates", "A source row contains an OCR block from another job")
    copied = QuestionSource(
        question_id=survivor_id,
        source_asset_id=source.source_asset_id,
        locator_type=source.locator_type,
        locator_json=dict(source.locator_json),
        locator_correction_json=(
            dict(source.locator_correction_json)
            if source.locator_correction_json is not None
            else None
        ),
        source_text_snapshot=source.source_text_snapshot,
        raw_ocr_text_snapshot=source.raw_ocr_text_snapshot,
        confidence=source.confidence,
    )
    session.add(copied)
    session.flush()
    session.add_all(
        [
            QuestionSourceOCRBlock(
                question_source_id=copied.id,
                ocr_block_id=link.ocr_block_id,
            )
            for link in links
        ]
    )


def merge_ingestion_candidates(
    session: Session,
    job_id: int,
    payload: object,
) -> tuple[int, list[int]]:
    if not isinstance(payload, dict):
        raise _validation("body", "Expected a JSON object")
    survivor_id = payload.get("survivor_id")
    participants = payload.get("candidates")
    if isinstance(survivor_id, bool) or not isinstance(survivor_id, int):
        raise _validation("survivor_id", "Must be a candidate ID")
    if not isinstance(participants, list) or len(participants) < 2:
        raise _validation("candidates", "Merge requires a survivor and at least one candidate")
    if set(payload) != {"survivor_id", "candidates", "final_text"}:
        raise _validation("body", "Expected survivor_id, candidates, and final_text")
    final_text, final_normalized, final_hash = prepare_question_text(payload["final_text"])
    revisions: dict[int, int] = {}
    for index, item in enumerate(participants):
        if not isinstance(item, dict) or set(item) != {"id", "expected_revision"}:
            raise _validation(f"candidates[{index}]", "Expected id and expected_revision")
        candidate_id = item["id"]
        if isinstance(candidate_id, bool) or not isinstance(candidate_id, int):
            raise _validation(f"candidates[{index}].id", "Must be an integer")
        revision = item["expected_revision"]
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
            raise _validation(f"candidates[{index}].expected_revision", "Must be non-negative")
        if candidate_id in revisions:
            raise _validation("candidates", "Candidate IDs must be unique")
        revisions[candidate_id] = revision
    if survivor_id not in revisions:
        raise _validation("candidates", "The survivor must include its expected_revision")

    with session.begin():
        candidates = {
            candidate_id: _load_candidate(session, candidate_id, job_id=job_id)
            for candidate_id in revisions
        }
        for candidate_id, candidate in candidates.items():
            _require_pending(candidate, revisions[candidate_id])
        survivor = candidates[survivor_id]
        job = session.get(IngestionJob, job_id)
        if job is None:
            raise ApiError(404, "NOT_FOUND", "Candidate ingestion job not found")

        sources_by_candidate: dict[int, list[QuestionSource]] = {}
        for candidate_id, candidate in candidates.items():
            source_rows = _get_candidate_sources(session, candidate, job)
            sources_by_candidate[candidate_id] = source_rows
            for source in source_rows:
                if source.source_asset_id != job.source_asset_id:
                    raise _validation("candidates", "Candidate source image does not belong to this job")

        now = _now()
        for candidate_id in sorted(candidates):
            candidate = candidates[candidate_id]
            revision = revisions[candidate_id]
            if candidate_id == survivor_id:
                _advance_candidate(session, candidate, revision)
            else:
                _advance_candidate(
                    session,
                    candidate,
                    revision,
                    values={
                        "archived_at": now,
                        "ingestion_candidate_state": "superseded",
                        "superseded_by_candidate_id": survivor_id,
                    },
                )
                invalidate_unmerged_question_relations(session, candidate_id)
                for source in sources_by_candidate[candidate_id]:
                    _copy_question_source(session, source, survivor_id, job)

        survivor = session.get(Question, survivor_id)
        survivor.text = final_text
        survivor.normalized_text = final_normalized
        survivor.search_text = final_normalized
        survivor.normalized_hash = final_hash
        session.flush()
        refresh_rule_suggestions(session, survivor.id)
        return survivor_id, [candidate_id for candidate_id in candidates if candidate_id != survivor_id]


def reject_ingestion_candidate(
    session: Session,
    candidate_id: int,
    payload: object,
) -> Question:
    if not isinstance(payload, dict) or set(payload) != {"expected_revision"}:
        raise _validation("body", "Expected expected_revision")
    revision = _expected_revision(payload)
    with session.begin():
        candidate = _load_candidate(session, candidate_id)
        _require_pending(candidate, revision)
        _advance_candidate(
            session,
            candidate,
            revision,
            values={
                "archived_at": _now(),
                "ingestion_candidate_state": "rejected",
            },
        )
        invalidate_unmerged_question_relations(session, candidate.id)
    return session.get(Question, candidate_id)


def confirm_ingestion_candidate(
    session: Session,
    candidate_id: int,
    payload: object,
) -> Question:
    if not isinstance(payload, dict) or set(payload) != {"expected_revision"}:
        raise _validation("body", "Expected expected_revision")
    revision = _expected_revision(payload)
    blocked_by_same_question = False
    with session.begin():
        _begin_confirmation_write_transaction(session)
        candidate = _load_candidate(session, candidate_id)
        _require_pending(candidate, revision)
        job = session.get(IngestionJob, candidate.origin_ingestion_job_id)
        if job is None:
            raise ApiError(404, "NOT_FOUND", "Candidate ingestion job not found")
        if job.status != "succeeded":
            raise ApiError(409, "CONFLICT", "Only candidates from a completed OCR job can be confirmed")
        refresh_rule_suggestions(session, candidate.id)
        blocked_by_same_question = bool(
            unresolved_same_question_relations(session, candidate.id)
        )
        if not blocked_by_same_question:
            prepare_question_text(candidate.text)
            topic_ids = list(
                session.scalars(
                    select(QuestionTopic.topic_id).where(
                        QuestionTopic.question_id == candidate_id
                    )
                )
            )
            tag_ids = list(
                session.scalars(
                    select(QuestionTag.tag_id).where(
                        QuestionTag.question_id == candidate_id
                    )
                )
            )
            validate_active_topic_ids(session, topic_ids)
            validate_active_tag_ids(session, tag_ids)
            _advance_candidate(
                session,
                candidate,
                revision,
                values={
                    "status": "active",
                    "ingestion_candidate_state": "confirmed",
                },
            )
            if session.get(QuestionState, candidate_id) is None:
                session.add(QuestionState(question_id=candidate_id, is_favorite=False, is_wrong=False))
            session.flush()
    if blocked_by_same_question:
        raise ApiError(
            409,
            "CONFLICT",
            "Review same-question suggestions before confirming this OCR candidate",
            {"similar_questions": "Reject or reclassify the relation, or merge the candidate into a canonical Question"},
        )
    return question_repository.get_question(session, candidate_id)
