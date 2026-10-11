"""Explicit, traceable export of user-written mock-interview answers."""
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.errors import ApiError
from app.models.mock_interview import MockInterviewAnswerExport, MockInterviewSession, MockInterviewTurn
from app.models.question import Question
from app.models.saved_answer import SavedAnswer, SavedAnswerVersion
from app.models.taxonomy import utc_now
from app.services import saved_answers
from app.services.question_relations import _begin_write


def _error(status: int, code: str, message: str) -> ApiError:
    return ApiError(status, code, message)


def _parse_payload(payload: object) -> tuple[str, int | None, str, int | None]:
    allowed = {"save_mode", "saved_answer_id", "content", "self_rating"}
    if not isinstance(payload, dict) or set(payload) - allowed:
        raise _error(400, "VALIDATION_ERROR", "导出回答字段无效。")
    mode = payload.get("save_mode")
    target_id = payload.get("saved_answer_id")
    if mode not in {"new_answer", "append_version"}:
        raise _error(400, "VALIDATION_ERROR", "请选择新建回答或追加到已有回答。")
    if mode == "new_answer" and target_id is not None:
        raise _error(400, "VALIDATION_ERROR", "新建回答不接受已有回答 ID。")
    if mode == "append_version" and (type(target_id) is not int or target_id <= 0):
        raise _error(400, "VALIDATION_ERROR", "请选择要追加版本的已有回答。")
    content, rating, _item_id, _review_id = saved_answers._payload(
        {"content": payload.get("content"), "self_rating": payload.get("self_rating")}
    )
    return mode, target_id, content, rating


def _source_json(record: MockInterviewSession, turn: MockInterviewTurn) -> dict:
    return {
        "mock_interview_id": record.id,
        "mock_interview_title": record.title,
        "turn_id": turn.id,
        "question_id": turn.question_id,
        "question_text": turn.question_text_snapshot,
    }


def _result_json(session, record, turn, link, *, already_exported: bool) -> dict:
    version = session.get(SavedAnswerVersion, link.saved_answer_version_id)
    answer = session.get(SavedAnswer, version.saved_answer_id) if version else None
    if version is None or answer is None:
        raise _error(409, "MOCK_INTERVIEW_EXPORT_BROKEN", "回答来源关联不完整，请联系维护者。")
    return {
        "saved_answer": {
            "id": answer.id,
            "question_id": answer.question_id,
            "is_pinned": answer.is_pinned,
            "archived_at": answer.archived_at.isoformat() if answer.archived_at else None,
        },
        "version": saved_answers.version_json(version),
        "source": _source_json(record, turn),
        "already_exported": already_exported,
    }


def _active_canonical_group(session, question_id: int) -> tuple[Question, set[int]]:
    question = session.get(Question, question_id)
    if question is None:
        raise _error(409, "MOCK_INTERVIEW_QUESTION_UNAVAILABLE", "原题已不存在，不能导出回答。")
    if question.status not in {"active", "merged"}:
        raise _error(409, "MOCK_INTERVIEW_QUESTION_UNAVAILABLE", "原题尚未确认，不能导出回答。")
    members = set(saved_answers.question_group(session, question_id))
    root_id = question.merged_into_question_id or question.id
    root = session.get(Question, root_id)
    if root is None or root.status != "active" or root.merged_into_question_id is not None or root.archived_at is not None:
        raise _error(409, "MOCK_INTERVIEW_QUESTION_UNAVAILABLE", "规范题已归档或不可写，请先恢复或选择其他题目。")
    return root, members


def export_answer(session, record_id: int, turn_id: int, payload: object) -> tuple[dict, bool]:
    mode, target_answer_id, content, rating = _parse_payload(payload)
    try:
        with session.begin():
            _begin_write(session)
            record = session.get(MockInterviewSession, record_id)
            if record is None:
                raise _error(404, "MOCK_INTERVIEW_RECORD_NOT_FOUND", "保存的模拟面试记录不存在。")
            turn = session.scalar(
                select(MockInterviewTurn).where(
                    MockInterviewTurn.id == turn_id,
                    MockInterviewTurn.session_id == record_id,
                )
            )
            if turn is None:
                raise _error(404, "MOCK_INTERVIEW_TURN_NOT_FOUND", "这条回答不属于当前模拟面试记录。")
            if turn.kind != "answer":
                raise _error(409, "MOCK_INTERVIEW_TURN_NOT_ANSWER", "只能导出你自己写的回答。")

            existing = session.scalar(
                select(MockInterviewAnswerExport).where(
                    MockInterviewAnswerExport.mock_interview_turn_id == turn.id
                )
            )
            if existing is not None:
                return _result_json(session, record, turn, existing, already_exported=True), False

            root, source_members = _active_canonical_group(session, turn.question_id)
            export_payload = {"content": content, "self_rating": rating}
            if mode == "new_answer":
                answer, version = saved_answers.create_answer_in_transaction(session, root.id, export_payload)
            else:
                answer = session.get(SavedAnswer, target_answer_id)
                if answer is None:
                    raise _error(404, "NOT_FOUND", "目标回答不存在。")
                target_question = session.get(Question, answer.question_id)
                if target_question is None:
                    raise _error(409, "CONFLICT", "目标回答对应的题目已不存在。")
                if target_question.status not in {"active", "merged"} or target_question.archived_at is not None:
                    raise _error(409, "CONFLICT", "目标回答对应的题目已归档或不可写。")
                target_root = target_question.merged_into_question_id or target_question.id
                target_members = set(saved_answers.question_group(session, target_question.id))
                if target_root != root.id or target_members != source_members:
                    raise _error(400, "MOCK_INTERVIEW_ANSWER_GROUP_MISMATCH", "只能追加到同一规范题组中的回答。")
                answer, version = saved_answers.append_version_in_transaction(
                    session, answer.id, export_payload, inherit_ai_derivation=False
                )

            link = MockInterviewAnswerExport(
                mock_interview_turn_id=turn.id,
                saved_answer_version_id=version.id,
                created_at=utc_now(),
            )
            session.add(link)
            session.flush()
            return _result_json(session, record, turn, link, already_exported=False), True
    except IntegrityError as error:
        session.rollback()
        existing = session.scalar(
            select(MockInterviewAnswerExport).where(
                MockInterviewAnswerExport.mock_interview_turn_id == turn_id
            )
        )
        record = session.get(MockInterviewSession, record_id)
        turn = session.scalar(
            select(MockInterviewTurn).where(
                MockInterviewTurn.id == turn_id,
                MockInterviewTurn.session_id == record_id,
            )
        )
        if existing is not None and record is not None and turn is not None:
            return _result_json(session, record, turn, existing, already_exported=True), False
        raise _error(409, "CONFLICT", "回答导出发生冲突，请重新加载后再试。") from error


def answer_source_for_version(session, version_id: int) -> dict | None:
    return answer_sources_for_versions(session, [version_id]).get(version_id)


def answer_sources_for_versions(session, version_ids: list[int]) -> dict[int, dict]:
    if not version_ids:
        return {}
    row = session.execute(
        select(MockInterviewSession, MockInterviewTurn, MockInterviewAnswerExport)
        .join(MockInterviewTurn, MockInterviewTurn.session_id == MockInterviewSession.id)
        .join(MockInterviewAnswerExport, MockInterviewAnswerExport.mock_interview_turn_id == MockInterviewTurn.id)
        .where(MockInterviewAnswerExport.saved_answer_version_id.in_(version_ids))
    )
    return {
        link.saved_answer_version_id: _source_json(record, turn)
        for record, turn, link in row
    }


def exports_for_turn_ids(session, turn_ids: list[int]) -> dict[int, dict]:
    if not turn_ids:
        return {}
    rows = session.execute(
        select(MockInterviewAnswerExport, SavedAnswerVersion, SavedAnswer, MockInterviewTurn)
        .join(SavedAnswerVersion, SavedAnswerVersion.id == MockInterviewAnswerExport.saved_answer_version_id)
        .join(SavedAnswer, SavedAnswer.id == SavedAnswerVersion.saved_answer_id)
        .join(MockInterviewTurn, MockInterviewTurn.id == MockInterviewAnswerExport.mock_interview_turn_id)
        .where(MockInterviewAnswerExport.mock_interview_turn_id.in_(turn_ids))
    )
    return {
        turn.id: {
            "saved_answer_id": answer.id,
            "saved_answer_version_id": version.id,
            "version_no": version.version_no,
            "question_id": answer.question_id,
            "self_rating": version.self_rating,
            "created_at": link.created_at.isoformat() if link.created_at else None,
        }
        for link, version, answer, turn in rows
    }
