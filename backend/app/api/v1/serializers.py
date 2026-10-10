"""Shared exact historical payloads for legacy and canonical endpoints."""
from datetime import timezone


def source_json(source):
    return {
        "question_source_id": source.id,
        "question_id": source.question_id,
        "source_asset_id": source.source_asset_id,
        "source_type": source.source_asset.source_type,
        "source_title": source.source_asset.title,
        "original_filename": source.source_asset.original_filename,
        "mime_type": source.source_asset.mime_type,
        "display_width": source.source_asset.display_width,
        "display_height": source.source_asset.display_height,
        "locator_type": source.locator_type,
        "locator_json": source.locator_json,
        "locator_correction_json": source.locator_correction_json,
        "source_text_snapshot": source.source_text_snapshot,
        "raw_ocr_text_snapshot": source.raw_ocr_text_snapshot,
        "confidence": source.confidence,
        "ocr_block_ids": [
            link.ocr_block.id
            for link in sorted(
                source.ocr_block_links,
                key=lambda item: (
                    item.ocr_block.reading_order,
                    item.ocr_block.id,
                ),
            )
        ],
        "ocr_blocks": [
            {
                "id": link.ocr_block.id,
                "text": link.ocr_block.text,
                "bbox": link.ocr_block.bbox_json,
                "reading_order": link.ocr_block.reading_order,
                "confidence": link.ocr_block.confidence,
            }
            for link in sorted(
                source.ocr_block_links,
                key=lambda item: (
                    item.ocr_block.reading_order,
                    item.ocr_block.id,
                ),
            )
        ],
        "original_image_url": f"/api/v1/sources/{source.source_asset_id}/original",
        "display_image_url": f"/api/v1/sources/{source.source_asset_id}/display",
    }


def review_json(review):
    def as_utc(value):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()

    return {
        "id": review.id,
        "question_id": review.question_id,
        "session_item_id": review.session_item_id,
        "review_rating": review.review_rating,
        "saved_answer_version_id": review.saved_answer_version_id,
        "reviewed_at": as_utc(review.reviewed_at),
        "created_at": as_utc(review.created_at),
        "updated_at": as_utc(review.updated_at),
    }



def _timestamp(value):
    return value.isoformat() if value is not None else None


def session_item_json(item):
    question = item.question
    return {
        "id": item.id,
        "session_id": item.session_id,
        "question_id": item.question_id,
        "ordinal": item.ordinal,
        "status": item.status,
        "selection_reason": item.selection_reason,
        "viewed_at": _timestamp(item.viewed_at),
        "completed_at": _timestamp(item.completed_at),
        "question": {
            "id": question.id,
            "text": question.text,
            "status": question.status,
            "archived_at": _timestamp(question.archived_at),
        },
    }

