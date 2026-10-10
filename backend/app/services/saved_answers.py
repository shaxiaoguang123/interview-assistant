"""Small transactional answer operations; never derive mastery from quality scores."""
from datetime import timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.errors import ApiError
from app.models.practice import PracticeReview, SessionItem
from app.models.question import Question
from app.models.saved_answer import SavedAnswer, SavedAnswerVersion
from app.models.taxonomy import utc_now
from app.repositories.questions import canonical_member_ids
from app.services.question_relations import _begin_write


def _error(message, status=400):
    raise ApiError(status, "VALIDATION_ERROR" if status == 400 else "CONFLICT", message)


def question_group(session, question_id):
    question = session.get(Question, question_id)
    if question is None:
        raise ApiError(404, "NOT_FOUND", "Question not found")
    if question.status not in {"active", "merged"}:
        _error("Save answers only for confirmed questions", 409)
    return canonical_member_ids(session, question.merged_into_question_id or question.id)


def _answer(session, answer_id, writable=False):
    answer = session.get(SavedAnswer, answer_id)
    if answer is None:
        raise ApiError(404, "NOT_FOUND", "Saved answer not found")
    if writable and answer.archived_at is not None:
        _error("Archived answers are read-only", 409)
    return answer


def _payload(payload):
    allowed = {"content", "self_rating", "source_session_item_id", "source_practice_review_id"}
    if not isinstance(payload, dict) or "content" not in payload or set(payload) - allowed:
        _error("Expected content and optional quality rating and paired practice sources")
    content = payload["content"]
    if not isinstance(content, str) or not content.strip() or len(content) > 100000:
        _error("Answer content must contain 1–100000 characters")
    rating = validate_rating(payload.get("self_rating"))
    item_id, review_id = payload.get("source_session_item_id"), payload.get("source_practice_review_id")
    if (item_id is None) != (review_id is None):
        _error("Practice source item and review must be supplied together")
    for value in (item_id, review_id):
        if value is not None and (type(value) is not int or value <= 0):
            _error("Practice source IDs must be positive integers")
    return content, rating, item_id, review_id


def validate_rating(value):
    if value is not None and (type(value) is not int or not 1 <= value <= 5):
        _error("Answer quality rating must be an integer from 1 to 5, or null")
    return value


def _source(session, question_id, item_id, review_id):
    if item_id is None:
        return None
    members = question_group(session, question_id)
    item, review = session.get(SessionItem, item_id), session.get(PracticeReview, review_id)
    if (item is None or review is None or item.status != "completed" or review.session_item_id != item_id
            or item.question_id not in members or review.question_id not in members):
        _error("Practice sources must identify one completed review in this canonical group")
    if review.saved_answer_version_id is not None:
        _error("This practice review already has a saved answer", 409)
    return review


def _append(session, answer, data, *, origin_kind="user_written", based_on_version_id=None, assistant_output_id=None):
    content, rating, item_id, review_id = data
    review = _source(session, answer.question_id, item_id, review_id)
    number = (session.scalar(select(func.max(SavedAnswerVersion.version_no)).where(
        SavedAnswerVersion.saved_answer_id == answer.id)) or 0) + 1
    now = utc_now()
    version = SavedAnswerVersion(saved_answer_id=answer.id, version_no=number, content=content,
        self_rating=rating, self_rating_updated_at=now if rating is not None else None,
        origin_kind=origin_kind, based_on_version_id=based_on_version_id, assistant_output_id=assistant_output_id,
        source_session_item_id=item_id, source_practice_review_id=review_id)
    session.add(version)
    answer.updated_at = now
    session.flush()
    if review is not None:
        # Preserve reviewed_at, updated_at and review_rating; this is only an optional link.
        session.execute(PracticeReview.__table__.update().where(PracticeReview.id == review.id)
                        .values(saved_answer_version_id=version.id, updated_at=review.updated_at))
        session.expire(review)
    return version


def create_answer(session, question_id, payload):
    data = _payload(payload)
    with session.begin():
        _begin_write(session)
        question_group(session, question_id)
        _source(session, question_id, data[2], data[3])
        answer = SavedAnswer(question_id=question_id, source_session_item_id=data[2])
        session.add(answer)
        session.flush()
        _append(session, answer, data)
    return answer


def append_version(session, answer_id, payload):
    data = _payload(payload)
    with session.begin():
        _begin_write(session)
        answer = _answer(session, answer_id, True)
        current=session.scalar(select(SavedAnswerVersion).where(SavedAnswerVersion.saved_answer_id==answer.id).order_by(SavedAnswerVersion.version_no.desc()).limit(1))
        derivation={"origin_kind":"ai_assisted","based_on_version_id":current.id,"assistant_output_id":current.assistant_output_id} if current and current.assistant_output_id else {}
        version = _append(session, answer, data, **derivation)
    return version


def set_rating(session, version_id, payload):
    if not isinstance(payload, dict) or set(payload) != {"self_rating"}:
        _error("Expected only self_rating")
    rating = validate_rating(payload["self_rating"])
    with session.begin():
        _begin_write(session)
        version = session.get(SavedAnswerVersion, version_id)
        if version is None:
            raise ApiError(404, "NOT_FOUND", "Answer version not found")
        answer = _answer(session, version.saved_answer_id, True)
        latest = session.scalar(select(func.max(SavedAnswerVersion.version_no)).where(SavedAnswerVersion.saved_answer_id == answer.id))
        if version.version_no != latest:
            _error("Historical version ratings are preserved; rate the current version", 409)
        version.self_rating, version.self_rating_updated_at = rating, utc_now()
        answer.updated_at = utc_now()
        session.flush()
    return version


def set_pin(session, answer_id, payload):
    if not isinstance(payload, dict) or set(payload) != {"is_pinned"} or type(payload["is_pinned"]) is not bool:
        _error("Expected boolean is_pinned")
    try:
        with session.begin():
            _begin_write(session)
            answer = _answer(session, answer_id, True)
            if payload["is_pinned"]:
                members = question_group(session, answer.question_id)
                # Explicitly choosing a new preferred answer replaces the old preference only.
                for previous in session.scalars(select(SavedAnswer).where(SavedAnswer.question_id.in_(members),
                        SavedAnswer.is_pinned.is_(True), SavedAnswer.id != answer.id)):
                    previous.is_pinned = False
                    previous.updated_at = utc_now()
                session.flush()
            answer.is_pinned = payload["is_pinned"]
            answer.updated_at = utc_now()
            session.flush()
        return answer
    except IntegrityError as error:
        raise ApiError(409, "CONFLICT", "Pinned answer changed; reload and retry") from error


def archive_answer(session, answer_id):
    with session.begin():
        _begin_write(session)
        answer = _answer(session, answer_id)
        if answer.archived_at is None:
            answer.archived_at = answer.updated_at = utc_now()
            answer.is_pinned = False
            session.flush()
    return answer


def _timestamp(value):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def version_json(version):
    return {field: getattr(version, field) for field in (
        "id", "saved_answer_id", "version_no", "content", "self_rating", "origin_kind",
        "source_session_item_id", "source_practice_review_id", "based_on_version_id", "assistant_output_id")} | {
        "created_at": _timestamp(version.created_at), "self_rating_updated_at": _timestamp(version.self_rating_updated_at)}


def answer_json(session, answer):
    versions = list_versions(session, answer.id)
    return {"id": answer.id, "question_id": answer.question_id, "source_session_item_id": answer.source_session_item_id,
        "is_pinned": answer.is_pinned, "archived_at": _timestamp(answer.archived_at),
        "created_at": _timestamp(answer.created_at), "updated_at": _timestamp(answer.updated_at),
        "version_count": len(versions), "current_version": version_json(versions[0])}


def list_versions(session, answer_id):
    _answer(session, answer_id)
    return list(session.scalars(select(SavedAnswerVersion).where(SavedAnswerVersion.saved_answer_id == answer_id)
                               .order_by(SavedAnswerVersion.version_no.desc())))


def list_answers(session, question_id, include_archived=False):
    members = question_group(session, question_id)
    query = select(SavedAnswer).where(SavedAnswer.question_id.in_(members))
    if not include_archived:
        query = query.where(SavedAnswer.archived_at.is_(None))
    answers = [answer_json(session, a) for a in session.scalars(query)]
    return sorted(answers, key=lambda a: (a["is_pinned"], a["current_version"]["self_rating"] or 0,
                                          a["updated_at"], a["id"]), reverse=True)


def validate_review_version(session, question_id, version_id):
    if type(version_id) is not int or version_id <= 0:
        _error("saved_answer_version_id must be a positive integer")
    version = session.get(SavedAnswerVersion, version_id)
    if version is None:
        _error("Saved answer version not found")
    answer = _answer(session, version.saved_answer_id)
    if answer.question_id not in question_group(session, question_id):
        _error("Saved answer version must belong to the same canonical group")
    return version
