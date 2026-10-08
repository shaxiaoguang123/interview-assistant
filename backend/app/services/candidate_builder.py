from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from app.ocr.adapter import OCRDetection


@dataclass(frozen=True)
class CandidateDraft:
    text: str
    ocr_block_ids: tuple[str, ...]
    source_text_snapshot: str
    locator: dict[str, float]
    confidence: float | None


def build_candidate_groups(detections: Sequence[OCRDetection]) -> list[CandidateDraft]:
    """Conservatively preserve each OCR text block as an editable candidate.

    Task 4 replaces this baseline with multi-block and numbered-question
    grouping while keeping the job transaction contract unchanged.
    """
    drafts: list[CandidateDraft] = []
    for detection in detections:
        if not detection.text.strip():
            continue
        x, y, width, height = detection.bbox
        drafts.append(
            CandidateDraft(
                text=detection.text,
                ocr_block_ids=(detection.id,),
                source_text_snapshot=detection.text,
                locator={"x": x, "y": y, "width": width, "height": height},
                confidence=detection.confidence,
            )
        )
    return drafts
