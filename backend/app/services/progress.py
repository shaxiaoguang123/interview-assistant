"""Small, explainable aggregates; answer quality never enters mastery statistics."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.practice import PracticeReview
from app.models.question import Question
from app.models.saved_answer import SavedAnswer, SavedAnswerVersion
from app.models.taxonomy import Topic
from app.repositories.questions import group_states, list_questions
from app.services.review_schedule import as_utc, schedule_json, REVIEW_INTERVAL_DAYS


def get_progress(session: Session, *, now: datetime | None = None, window_days: int = 30) -> dict:
    connection = session.connection()
    if connection.dialect.name == 'sqlite' and not connection.connection.driver_connection.in_transaction:
        connection.exec_driver_sql('BEGIN')
    now = as_utc(now or datetime.now(timezone.utc))
    roots = list_questions(session)
    root_by_id = {q.id: q for q in roots}
    canonical_by_id = {qid: root or qid for qid, root in session.execute(
        select(Question.id, Question.merged_into_question_id))}
    reviews = list(session.scalars(select(PracticeReview)))
    mastery = dict.fromkeys(REVIEW_INTERVAL_DAYS, 0)
    reviewed_roots = set()
    topic_reviews: dict[int, list] = {}
    cutoff = now - timedelta(days=window_days)
    # Each event belongs to the final root's direct classification exactly once per Topic.
    for review in reviews:
        mastery[review.review_rating] += 1
        root_id = canonical_by_id[review.question_id]
        if root_id not in root_by_id:
            continue
        reviewed_roots.add(root_id)
        if cutoff <= as_utc(review.reviewed_at) <= now:
            for link in root_by_id[root_id].topic_links:
                topic_reviews.setdefault(link.topic_id, []).append(review)
    all_reviewed = {canonical_by_id[r.question_id] for r in reviews}
    topics = []
    for topic in session.scalars(select(Topic).where(Topic.is_active.is_(True)).order_by(Topic.sort_order, Topic.id)):
        classified = [q for q in roots if any(t.topic_id == topic.id for t in q.topic_links)]
        events = topic_reviews.get(topic.id, [])
        counts = dict.fromkeys(REVIEW_INTERVAL_DAYS, 0)
        for event in events:
            counts[event.review_rating] += 1
        enough = len(events) >= 3
        topics.append({"id": topic.id, "name": topic.name, "question_count": len(classified),
            "reviewed_question_count": sum(q.id in all_reviewed for q in classified),
            "review_count": len(events), "mastery_counts": counts, "has_enough_records": enough,
            "weak_ratio": (counts["dont_know"] + counts["vague"]) / len(events) if enough else None})
    topics.sort(key=lambda t: (not t['has_enough_records'], -(t['weak_ratio'] or 0), -t['review_count'], t['id']))
    flags = group_states(session, list(root_by_id))
    due = [q for q in roots if q.state and q.state.next_review_at and as_utc(q.state.next_review_at) <= now]
    due.sort(key=lambda q: (as_utc(q.state.next_review_at), q.id))
    future = sum(bool(q.state and q.state.next_review_at and as_utc(q.state.next_review_at) > now) for q in roots)
    answers = [a for a in session.scalars(select(SavedAnswer).where(SavedAnswer.archived_at.is_(None)))
               if canonical_by_id[a.question_id] in root_by_id]
    answer_ids = {a.id for a in answers}
    current = {}
    for version in session.scalars(select(SavedAnswerVersion).where(SavedAnswerVersion.saved_answer_id.in_(answer_ids))
                                  .order_by(SavedAnswerVersion.version_no)):
        current[version.saved_answer_id] = version
    quality = {str(n): 0 for n in range(1, 6)}
    for version in current.values():
        if version.self_rating is not None:
            quality[str(version.self_rating)] += 1
    return {"as_of": now.isoformat(), "window_days": window_days, "active_question_count": len(roots),
        "reviewed_question_count": len(reviewed_roots), "practice_review_count": len(reviews),
        "mastery_counts": mastery, "due_question_count": len(due), "future_question_count": future,
        "favorite_question_count": sum(f['is_favorite'] for f in flags.values()),
        "wrong_question_count": sum(flags[q.id]['is_wrong'] or bool(q.state and q.state.last_review_rating == 'dont_know') for q in roots),
        "saved_answer_count": len(answers), "rated_answer_count": sum(quality.values()),
        "answer_quality_counts": quality, "topics": topics,
        "due_questions": [{"id": q.id, "text": q.text, **schedule_json(q.state, now=now)} for q in due[:20]],
        "due_list_limit": 20}
