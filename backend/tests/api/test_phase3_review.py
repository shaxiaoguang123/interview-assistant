from datetime import datetime, timedelta, timezone

import pytest

from app.models.question import QuestionState
from app.services.review_schedule import next_review_time
from app.services.practice_selector import eligible_questions
from app.services.progress import get_progress

NOW = datetime(2026, 10, 10, 8, 0, tzinfo=timezone.utc)


def question(client, text='Agent review question', **extra):
    response = client.post('/api/v1/questions', json={'text': text, **extra})
    assert response.status_code == 201, response.get_json()
    return response.get_json()['id']


def review(client, monkeypatch, qid, rating, when=NOW):
    monkeypatch.setattr('app.services.practice_review.utc_now', lambda: when)
    result = client.post('/api/v1/practice-sessions', json={'mode':'random','limit':100})
    assert result.status_code == 201
    item = next(i for i in result.get_json()['items'] if i['question_id']==qid)
    result = client.post(f"/api/v1/session-items/{item['id']}/review", json={'review_rating':rating})
    assert result.status_code == 201, result.get_json()
    return result.get_json()


@pytest.mark.parametrize('rating,days',[('dont_know',1),('vague',2),('basic',7),('proficient',14)])
def test_mastery_intervals_and_review_creation(client, monkeypatch, rating, days):
    qid = question(client)
    result = review(client, monkeypatch, qid, rating)
    state = client.get(f'/api/v1/questions/{qid}').get_json()['state']
    assert datetime.fromisoformat(state['next_review_at']) == NOW+timedelta(days=days)
    assert state['last_review_rating'] == rating
    assert state['last_reviewed_at'] == NOW.isoformat()
    assert result['review_schedule']['next_review_at'] == state['next_review_at']
    assert next_review_time(NOW.astimezone(timezone(timedelta(hours=8))),rating)==NOW+timedelta(days=days)


def test_correction_uses_original_event_time_and_latest_only(client, monkeypatch):
    qid=question(client)
    old=review(client,monkeypatch,qid,'dont_know',NOW-timedelta(days=10))
    latest=review(client,monkeypatch,qid,'basic')
    first=client.patch(f"/api/v1/practice-reviews/{old['id']}",json={'review_rating':'proficient'}).get_json()
    assert first['reviewed_at']==old['reviewed_at']
    assert datetime.fromisoformat(first['review_schedule']['next_review_at'])==NOW+timedelta(days=7)
    result=client.patch(f"/api/v1/practice-reviews/{latest['id']}",json={'review_rating':'vague'}).get_json()
    assert result['id']==latest['id'] and result['reviewed_at']==latest['reviewed_at']
    assert datetime.fromisoformat(result['review_schedule']['next_review_at'])==NOW+timedelta(days=2)
    assert len(client.get(f'/api/v1/questions/{qid}/practice-reviews').get_json())==2


def test_answer_quality_flags_and_text_do_not_reschedule(client,monkeypatch):
    qid=question(client)
    before=review(client,monkeypatch,qid,'basic')['review_schedule']
    answer=client.post(f'/api/v1/questions/{qid}/saved-answers',json={'content':'A user answer'}).get_json()
    version=answer['current_version']['id']
    assert client.patch(f'/api/v1/saved-answer-versions/{version}/rating',json={'self_rating':5}).status_code==200
    assert client.post(f"/api/v1/saved-answers/{answer['id']}/versions",json={'content':'New version'}).status_code==201
    assert client.patch(f"/api/v1/saved-answers/{answer['id']}/pin",json={'is_pinned':True}).status_code==200
    assert client.post(f"/api/v1/saved-answers/{answer['id']}/archive").status_code==200
    for fields in ({'is_favorite':True},{'is_wrong':True},{'is_wrong':False}):
        assert client.patch(f'/api/v1/questions/{qid}/state',json=fields).status_code==200
    assert client.patch(f'/api/v1/questions/{qid}',json={'text':'Updated user question'}).status_code==200
    state=client.get(f'/api/v1/questions/{qid}').get_json()['state']
    fields=('last_reviewed_at','last_review_rating','next_review_at')
    assert {k:state[k] for k in fields}=={k:before[k] for k in fields}
    assert len(client.get(f'/api/v1/questions/{qid}/practice-reviews').get_json())==1


def merge(client,root,child):
    candidates=client.get(f'/api/v1/questions/{root}/similar-candidates').get_json()
    relation=next(r for r in candidates['candidates'] if r['other_question']['id']==child)
    response=client.patch(f"/api/v1/question-relations/{relation['id']}",json={
        'question_id':root,'relation_type':'same_question','decision_status':'accepted','expected_review_token':relation['review_token']})
    assert response.status_code==200,response.get_json()
    preview=client.get(f'/api/v1/questions/{root}/merge-preview?source_question_id={child}').get_json()
    response=client.post(f'/api/v1/questions/{root}/merge',json={
        'canonical_id':root,'source_question_id':child,'relation_id':preview['relation']['id'],
        'preview_token':preview['preview_token'],'topic_ids':[],'tag_ids':[]})
    assert response.status_code==200,response.get_json()


def test_merge_recomputes_latest_tie_and_preserves_original_events(client,monkeypatch,db_session):
    root=question(client,'Canonical Agent question')
    child=question(client,'Canonical Agent question')
    earlier=review(client,monkeypatch,root,'dont_know')
    later=review(client,monkeypatch,child,'proficient')
    merge(client,root,child)
    state=client.get(f'/api/v1/questions/{root}').get_json()['state']
    assert state['last_review_rating']=='proficient'
    assert datetime.fromisoformat(state['next_review_at'])==NOW+timedelta(days=14)
    assert db_session.get(QuestionState,child).next_review_at is None
    events=client.get(f'/api/v1/questions/{root}/history').get_json()['practice_reviews']
    assert {r['id'] for r in events}=={earlier['id'],later['id']}
    assert {r['question_id'] for r in events}=={root,child}
    result=client.patch(f"/api/v1/practice-reviews/{later['id']}",json={'review_rating':'vague'}).get_json()
    assert result['canonical_question_id']==root
    assert datetime.fromisoformat(result['review_schedule']['next_review_at'])==NOW+timedelta(days=2)


def test_canonical_due_favorite_wrong_and_active_filters(client,monkeypatch,db_session):
    root=question(client,'Canonical practice')
    child=question(client,'Canonical practice')
    manual=question(client,'Manual wrong')
    future=question(client,'Future review')
    never=question(client,'Never reviewed')
    archived=question(client,'Archived review')
    review(client,monkeypatch,child,'dont_know',NOW-timedelta(days=2))
    review(client,monkeypatch,manual,'basic',NOW-timedelta(days=8))
    review(client,monkeypatch,future,'proficient')
    review(client,monkeypatch,archived,'dont_know',NOW-timedelta(days=4))
    client.patch(f'/api/v1/questions/{child}/state',json={'is_favorite':True})
    client.patch(f'/api/v1/questions/{manual}/state',json={'is_wrong':True})
    merge(client,root,child)
    client.post(f'/api/v1/questions/{archived}/archive')
    assert [q.id for q in eligible_questions(db_session,'due',{},now=NOW)]==[root,manual]
    assert [q.id for q in eligible_questions(db_session,'favorite',{},now=NOW)]==[root]
    assert {q.id for q in eligible_questions(db_session,'wrong',{},now=NOW)}=={root,manual}
    assert never not in [q.id for q in eligible_questions(db_session,'due',{},now=NOW)]
    db_session.rollback()  # Release the read snapshot before another request writes.
    for mode in ('favorite','wrong','due'):
        result=client.post('/api/v1/practice-sessions',json={'mode':mode,'limit':1}).get_json()
        assert result['mode']==mode and result['selector_version']=='v2' and len(result['items'])<=1
        assert all(i['selection_reason']==mode and i['question_id']!=child for i in result['items'])
    assert client.post('/api/v1/practice-sessions/preview',json={'mode':'due','filters':{}}).status_code==200
    assert client.get('/api/v1/practice-options').status_code==200


def test_progress_window_minimum_samples_and_answer_quality_separation(client,monkeypatch,db_session):
    topic=client.post('/api/v1/topics',json={'name':'RAG','slug':'rag','track_key':'agent_development'}).get_json()['id']
    sparse=client.post('/api/v1/topics',json={'name':'Memory','slug':'memory','track_key':'agent_development'}).get_json()['id']
    root=question(client,'RAG retrieval',topic_ids=[topic])
    for rating in ('dont_know','vague','basic'):
        review(client,monkeypatch,root,rating,NOW-timedelta(days=2))
    review(client,monkeypatch,root,'proficient',NOW-timedelta(days=40))
    q2=question(client,'Memory retention',topic_ids=[sparse])
    review(client,monkeypatch,q2,'dont_know',NOW-timedelta(days=1))
    client.post(f'/api/v1/questions/{root}/saved-answers',json={'content':'Quality answer','self_rating':5})
    progress=get_progress(db_session,now=NOW)
    assert progress['active_question_count']==2 and progress['reviewed_question_count']==2
    assert progress['practice_review_count']==5
    assert progress['mastery_counts']=={'dont_know':2,'vague':1,'basic':1,'proficient':1}
    assert progress['rated_answer_count']==1 and progress['answer_quality_counts']['5']==1
    rag=next(t for t in progress['topics'] if t['id']==topic)
    mem=next(t for t in progress['topics'] if t['id']==sparse)
    assert rag['review_count']==3 and rag['weak_ratio']==pytest.approx(2/3)
    assert mem['review_count']==1 and not mem['has_enough_records'] and mem['weak_ratio'] is None
    assert client.get('/api/v1/progress?window_days=0').status_code==400
    assert client.get('/api/v1/progress').status_code==200


def test_progress_merged_history_uses_final_root_topic_once(client,monkeypatch,db_session):
    topic=client.post('/api/v1/topics',json={'name':'Root Topic','slug':'root-topic'}).get_json()['id']
    old_topic=client.post('/api/v1/topics',json={'name':'Old Topic','slug':'old-topic'}).get_json()['id']
    root=question(client,'Group question',topic_ids=[topic])
    child=question(client,'Group question',topic_ids=[old_topic])
    for rating in ('dont_know','vague','basic'):
        review(client,monkeypatch,child,rating,NOW-timedelta(days=8))
    merge(client,root,child)
    client.patch(f'/api/v1/questions/{root}',json={'topic_ids':[topic]})
    result=get_progress(db_session,now=NOW)
    assert result['active_question_count']==result['reviewed_question_count']==result['due_question_count']==1
    current=next(t for t in result['topics'] if t['id']==topic)
    old=next(t for t in result['topics'] if t['id']==old_topic)
    assert current['review_count']==3 and current['reviewed_question_count']==1
    assert old['review_count']==old['question_count']==0
    assert [q['id'] for q in result['due_questions']]==[root]


def test_modes_exclude_pending_candidates_even_when_flagged(client,db_session):
    from app.models.question import Question
    active=question(client,'Active question')
    pending=question(client,'Synthetic candidate')
    row=db_session.get(Question,pending);row.status='pending_review';row.state.is_favorite=True;row.state.is_wrong=True
    row.state.next_review_at=NOW-timedelta(days=1);db_session.commit()
    for mode in ('random','favorite','wrong','due'):
        assert pending not in [q.id for q in eligible_questions(db_session,mode,{},now=NOW)]
    assert [q.id for q in eligible_questions(db_session,'random',{},now=NOW)]==[active]
