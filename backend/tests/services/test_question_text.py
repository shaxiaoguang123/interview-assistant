from importlib import import_module, util
from pathlib import Path

import pytest

from app.errors import ApiError


SERVICE_PATH = Path(__file__).resolve().parents[2] / "app" / "services" / "questions.py"


def _question_text_functions():
    assert SERVICE_PATH.is_file(), "missing feature: question text service"
    assert util.find_spec("app.services.questions") is not None
    module = import_module("app.services.questions")
    return module.prepare_question_text, module.normalize_question_text, module.MAX_QUESTION_TEXT_LENGTH


def test_question_text_rejects_empty_string():
    prepare_question_text, _, _ = _question_text_functions()

    with pytest.raises(ApiError) as error:
        prepare_question_text("")

    assert error.value.status_code == 400
    assert error.value.code == "VALIDATION_ERROR"
    assert "text" in error.value.fields


def test_question_text_rejects_whitespace_only():
    prepare_question_text, _, _ = _question_text_functions()

    with pytest.raises(ApiError) as error:
        prepare_question_text(" \t\n ")

    assert error.value.fields.get("text")


def test_question_text_rejects_over_limit():
    prepare_question_text, _, max_length = _question_text_functions()

    with pytest.raises(ApiError) as error:
        prepare_question_text("题" * (max_length + 1))

    assert error.value.status_code == 400
    assert "text" in error.value.fields


def test_question_text_accepts_exact_limit_and_valid_mixed_text():
    prepare_question_text, _, max_length = _question_text_functions()

    raw, normalized, digest = prepare_question_text("题" * max_length)
    assert len(raw) == max_length
    assert normalized
    assert len(digest) == 64

    raw, normalized, digest = prepare_question_text("  LangGraph 持久化 MCP  C++ C# GPT-4.1  ")
    assert raw == "LangGraph 持久化 MCP  C++ C# GPT-4.1"
    assert "langgraph" in normalized
    assert "c++" in normalized
    assert "c#" in normalized
    assert "gpt-4.1" in normalized
    assert len(digest) == 64


def test_normalization_preserves_distinct_technical_punctuation():
    _, normalize, _ = _question_text_functions()

    assert normalize("C++") != normalize("C#")
    assert normalize("GPT-4.1") != normalize("GPT 4.1")
    assert normalize("MCP") == normalize("mcp")


def test_normalization_folds_unicode_width_and_whitespace():
    _, normalize, _ = _question_text_functions()

    assert normalize("ＭＣＰ　通信协议？") == normalize("mcp 通信协议?")
