import json
from pathlib import Path
import uuid

import pytest

from app.ocr.adapter import OCRDetection
from app.services.candidate_builder import build_candidate_groups


FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "ocr" / "candidate_cases.json"


def _cases():
    return {
        case["name"]: case
        for case in json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    }


def _detections(case_name):
    case = _cases()[case_name]
    return [
        OCRDetection(
            id=item["id"],
            text=item["text"],
            bbox=tuple(item["bbox"]),
            confidence=item["confidence"],
            reading_order=item["reading_order"],
        )
        for item in case["detections"]
    ]


def _assert_case(case_name):
    case = _cases()[case_name]
    drafts = build_candidate_groups(_detections(case_name))
    assert [draft.text for draft in drafts] == case["expected_texts"]
    assert [list(draft.ocr_block_ids) for draft in drafts] == case["expected_block_groups"]
    for draft in drafts:
        assert all(str(uuid.UUID(block_id)) == block_id for block_id in draft.ocr_block_ids)
        assert draft.source_text_snapshot == draft.text


def test_numbered_multiline_questions_make_one_candidate_each():
    _assert_case("numbered_multiblock")


def test_header_does_not_become_a_numbered_candidate():
    case = _cases()["numbered_multiblock"]
    drafts = build_candidate_groups(_detections("numbered_multiblock"))
    assert "Agent 面试题" not in [draft.text for draft in drafts]
    assert case["detections"][0]["id"] not in {
        block_id for draft in drafts for block_id in draft.ocr_block_ids
    }


def test_one_question_across_multiple_blocks_stays_together():
    _assert_case("one_question_across_ocr_blocks")


def test_no_numbered_questions_use_conservative_spatial_groups():
    _assert_case("unnumbered_spatial")


def test_title_and_questions_mixed_keeps_title_out_of_candidates():
    _assert_case("title_and_numbered_questions")


def test_chinese_english_terms_are_preserved():
    _assert_case("mixed_chinese_english_terms")


def test_multiple_questions_inside_one_ocr_block_remain_recoverable():
    _assert_case("multiple_questions_in_one_block")


def test_long_screenshot_preserves_candidate_order_and_regions():
    case = _cases()["long_screenshot"]
    drafts = build_candidate_groups(_detections("long_screenshot"))
    assert [draft.text for draft in drafts] == case["expected_texts"]
    assert drafts[0].locator == pytest.approx(
        {"x": 0.08, "y": 0.05, "width": 0.84, "height": 0.05}
    )


def test_empty_ocr_result_builds_no_candidates():
    _assert_case("zero_text_detected")


def test_out_of_order_ocr_blocks_follow_reading_order():
    _assert_case("out_of_order_input")
