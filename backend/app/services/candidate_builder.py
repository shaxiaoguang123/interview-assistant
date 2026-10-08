from __future__ import annotations

from dataclasses import dataclass
import re
from statistics import median
from typing import Sequence

from app.ocr.adapter import OCRDetection


@dataclass(frozen=True)
class CandidateDraft:
    text: str
    ocr_block_ids: tuple[str, ...]
    source_text_snapshot: str
    locator: dict[str, float]
    confidence: float | None


_NUMBER_MARKER = re.compile(
    r"^\s*(?:(?:第)?\s*[0-9０-９]{1,3}[\.\．、\)）:：]|"
    r"[一二三四五六七八九十百]+[、．\.])\s*"
)


def _ordered(detections: Sequence[OCRDetection]) -> list[OCRDetection]:
    return sorted(
        detections,
        key=lambda detection: (
            detection.reading_order,
            detection.bbox[1],
            detection.bbox[0],
            detection.id,
        ),
    )


def _make_draft(blocks: Sequence[OCRDetection]) -> CandidateDraft:
    text_parts = [block.text for block in blocks]
    left = min(block.bbox[0] for block in blocks)
    top = min(block.bbox[1] for block in blocks)
    right = max(block.bbox[0] + block.bbox[2] for block in blocks)
    bottom = max(block.bbox[1] + block.bbox[3] for block in blocks)
    confidences = [block.confidence for block in blocks if block.confidence is not None]
    return CandidateDraft(
        text="\n".join(text_parts),
        ocr_block_ids=tuple(block.id for block in blocks),
        source_text_snapshot="\n".join(text_parts),
        locator={
            "x": left,
            "y": top,
            "width": min(1.0, right) - left,
            "height": min(1.0, bottom) - top,
        },
        confidence=sum(confidences) / len(confidences) if confidences else None,
    )


def build_candidate_groups(detections: Sequence[OCRDetection]) -> list[CandidateDraft]:
    """Group OCR text conservatively while retaining stable block references."""
    ordered = _ordered(detections)
    nonempty = [detection for detection in ordered if detection.text.strip()]
    if not nonempty:
        return []

    numbered_positions = [
        index
        for index, detection in enumerate(nonempty)
        if _NUMBER_MARKER.match(detection.text)
    ]
    groups: list[list[OCRDetection]] = []

    if numbered_positions:
        current: list[OCRDetection] = []
        for detection in nonempty:
            if _NUMBER_MARKER.match(detection.text):
                if current:
                    groups.append(current)
                current = [detection]
            elif current:
                current.append(detection)
            # Leading header/title blocks remain OCRBlocks but are not candidates.
        if current:
            groups.append(current)
    else:
        median_height = median(detection.bbox[3] for detection in nonempty)
        current = [nonempty[0]]
        for previous, following in zip(nonempty, nonempty[1:]):
            gap = following.bbox[1] - (previous.bbox[1] + previous.bbox[3])
            if gap > 1.8 * median_height:
                groups.append(current)
                current = [following]
            else:
                current.append(following)
        groups.append(current)

    return [_make_draft(group) for group in groups]
