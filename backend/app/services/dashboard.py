"""Small live dashboard aggregates; no synthetic progress or readiness scores."""
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.assistant import AssistantOutput
from app.models.ingestion import IngestionJob
from app.models.material import Material, MaterialVersion, Project
from app.models.practice import PracticeSession, SessionItem
from app.models.question import Question, QuestionState
from app.models.saved_answer import SavedAnswer, SavedAnswerVersion


def _time(value):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def get_dashboard(session: Session) -> dict:
    now = datetime.now(timezone.utc)
    due_count = session.scalar(
        select(func.count()).select_from(QuestionState)
        .join(Question, Question.id == QuestionState.question_id)
        .where(
            Question.status == "active",
            Question.merged_into_question_id.is_(None),
            Question.archived_at.is_(None),
            QuestionState.next_review_at.is_not(None),
            QuestionState.next_review_at <= now,
        )
    ) or 0
    pending_count = session.scalar(
        select(func.count()).select_from(Question).where(
            Question.status == "pending_review",
            Question.ingestion_candidate_state == "pending_review",
            Question.archived_at.is_(None),
        )
    ) or 0

    recent_answers = []
    answers = list(session.scalars(
        select(SavedAnswer).where(SavedAnswer.archived_at.is_(None))
        .order_by(SavedAnswer.updated_at.desc(), SavedAnswer.id.desc()).limit(6)
    ))
    for answer in answers:
        question = session.get(Question, answer.question_id)
        if question is None or question.archived_at is not None:
            continue
        root = session.get(Question, question.merged_into_question_id or question.id)
        if root is None or root.status != "active" or root.archived_at is not None:
            continue
        version = session.scalar(
            select(SavedAnswerVersion).where(SavedAnswerVersion.saved_answer_id == answer.id)
            .order_by(SavedAnswerVersion.version_no.desc()).limit(1)
        )
        recent_answers.append({
            "id": answer.id,
            "question_id": root.id,
            "question_text": root.text,
            "updated_at": _time(answer.updated_at),
            "is_pinned": answer.is_pinned,
            "version_id": version.id if version else None,
            "preview": (version.content[:180] + ("…" if len(version.content) > 180 else "")) if version else "",
            "self_rating": version.self_rating if version else None,
        })
        if len(recent_answers) == 5:
            break

    recent_sessions = []
    sessions = list(session.scalars(
        select(PracticeSession).order_by(PracticeSession.started_at.desc(), PracticeSession.id.desc()).limit(5)
    ))
    for item in sessions:
        total = session.scalar(select(func.count()).select_from(SessionItem).where(SessionItem.session_id == item.id)) or 0
        completed = session.scalar(select(func.count()).select_from(SessionItem).where(
            SessionItem.session_id == item.id, SessionItem.status == "completed"
        )) or 0
        recent_sessions.append({
            "id": item.id,
            "mode": item.mode,
            "started_at": _time(item.started_at),
            "completed_at": _time(item.completed_at),
            "item_count": total,
            "completed_count": completed,
        })

    active_projects = session.scalar(select(func.count()).select_from(Project).where(
        Project.is_active.is_(True), Project.archived_at.is_(None)
    )) or 0
    recent_materials = []
    for version, material in session.execute(
        select(MaterialVersion, Material).join(Material, Material.id == MaterialVersion.material_id)
        .where(Material.archived_at.is_(None))
        .order_by(MaterialVersion.created_at.desc(), MaterialVersion.id.desc()).limit(5)
    ):
        recent_materials.append({
            "id": material.id,
            "project_id": material.project_id,
            "version_id": version.id,
            "title": material.title,
            "kind": material.kind,
            "updated_at": _time(version.created_at),
            "version_no": version.version_no,
            "is_system_managed": material.is_system_managed,
        })

    recent_outputs = []
    for output in session.scalars(
        select(AssistantOutput).order_by(AssistantOutput.created_at.desc(), AssistantOutput.id.desc()).limit(3)
    ):
        recent_outputs.append({
            "id": output.id,
            "question_id": output.question_id,
            "output_type": output.output_type,
            "created_at": _time(output.created_at),
            "preview": output.content_text[:180] + ("…" if len(output.content_text) > 180 else ""),
        })

    return {
        "as_of": now.isoformat(),
        "due_question_count": int(due_count),
        "pending_candidate_count": int(pending_count),
        "active_project_count": int(active_projects),
        "recent_answers": recent_answers,
        "recent_sessions": recent_sessions,
        "recent_materials": recent_materials,
        "recent_ai_outputs": recent_outputs,
    }
