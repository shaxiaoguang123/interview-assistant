"""Phase 2 data boundaries exercised through real migrated SQLite and HTTP."""
from hashlib import sha256
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.models.question import Question, QuestionRelation
from app.models.practice import PracticeReview
from app.models.saved_answer import SavedAnswer, SavedAnswerVersion
from app.services.saved_answers import append_version, set_pin


def question(client, value="What is MCP?"):
    response = client.post('/api/v1/questions', json={'text':value})
    assert response.status_code == 201
    return response.get_json()['id']


def answer(client, q, content="我的完整回答", **extra):
    response = client.post(f'/api/v1/questions/{q}/saved-answers', json={'content':content, **extra})
    assert response.status_code == 201, response.get_json()
    return response.get_json()


def practice(client, q):
    ps = client.post('/api/v1/practice-sessions', json={'mode':'random','limit':100}).get_json()
    item = next(i for i in ps['items'] if i['question_id']==q)
    review = client.post(f"/api/v1/session-items/{item['id']}/review",json={'review_rating':'basic'}).get_json()
    return item, review


def accepted_pair(client, app):
    left, right = question(client), question(client)
    with app.extensions['sqlalchemy_session_factory'].begin() as s:
        relation = s.scalar(select(QuestionRelation).where(QuestionRelation.question_id==left,QuestionRelation.related_question_id==right))
        relation.relation_type='same_question';relation.decision_status='accepted';relation.suggested_by='user'
        relation.question_text_sha256_snapshot=sha256(s.get(Question,left).text.encode()).hexdigest()
        relation.related_question_text_sha256_snapshot=sha256(s.get(Question,right).text.encode()).hexdigest()
        s.flush();rid=relation.id
    return left,right,rid


def merge(client,left,right,rid,**extra):
    preview=client.get(f'/api/v1/questions/{left}/merge-preview?source_question_id={right}').get_json()
    return client.post(f'/api/v1/questions/{left}/merge',json={'canonical_id':left,'source_question_id':right,
        'relation_id':rid,'preview_token':preview['preview_token'],'topic_ids':[],'tag_ids':[],**extra})


def test_explicit_creation_multiple_answers_versions_and_rating_separation(client,app):
    q=question(client);item,review=practice(client,q)
    assert client.get(f'/api/v1/questions/{q}/saved-answers').get_json()==[]
    first=answer(client,q,self_rating=5);second=answer(client,q,'简短回答')
    version=client.post(f"/api/v1/saved-answers/{first['id']}/versions",json={'content':'修改后的回答'}).get_json()
    assert version['version_no']==2 and version['self_rating'] is None
    old=client.get(f"/api/v1/saved-answers/{first['id']}/versions").get_json()[1]
    assert old['content']=='我的完整回答' and old['self_rating']==5
    rated=client.patch(f"/api/v1/saved-answer-versions/{version['id']}/rating",json={'self_rating':4})
    assert rated.status_code==200
    history=client.get(f'/api/v1/questions/{q}/practice-reviews').get_json()
    assert history==[{key:value for key,value in review.items() if key not in {"canonical_question_id","review_schedule"}}]  # No quality operation creates, edits or retimes mastery events.
    assert client.patch(f"/api/v1/saved-answer-versions/{old['id']}/rating",json={'self_rating':1}).status_code==409
    with app.extensions['sqlalchemy_engine'].begin() as c:
        with pytest.raises(IntegrityError):
            c.execute(text('UPDATE saved_answer_version SET content = :content WHERE id = :id'),{'content':'overwrite','id':old['id']})
    assert first['id']!=second['id']


@pytest.mark.parametrize('rating',[0,6,True,2.5,'4'])
def test_invalid_quality_scores_do_not_write(client,rating):
    q=question(client)
    assert client.post(f'/api/v1/questions/{q}/saved-answers',json={'content':'answer','self_rating':rating}).status_code==400
    assert client.get(f'/api/v1/questions/{q}/saved-answers').get_json()==[]


@pytest.mark.parametrize('payload',[{}, {'content':' '},{'content':'answer','source_session_item_id':1},
    {'content':'answer','source_session_item_id':1,'source_practice_review_id':999}, {'content':'answer','origin_kind':'ai_generated'}])
def test_invalid_content_or_sources_do_not_create_answer(client,payload):
    q=question(client)
    assert client.post(f'/api/v1/questions/{q}/saved-answers',json=payload).status_code==400
    assert client.get(f'/api/v1/questions/{q}/saved-answers').get_json()==[]


def test_completed_practice_save_keeps_real_source_and_review_time(client,app):
    q=question(client);item,review=practice(client,q)
    saved=answer(client,q,source_session_item_id=item['id'],source_practice_review_id=review['id'])
    v=saved['current_version']
    assert (saved['source_session_item_id'],v['source_session_item_id'],v['source_practice_review_id'])==(item['id'],item['id'],review['id'])
    current=client.get(f'/api/v1/questions/{q}/practice-reviews').get_json()[0]
    assert current=={**{key:value for key,value in review.items() if key not in {'canonical_question_id','review_schedule'}},'saved_answer_version_id':v['id']}
    # Double-click/retry cannot silently create two linked answers for the same event.
    assert client.post(f'/api/v1/questions/{q}/saved-answers',json={'content':'duplicate','source_session_item_id':item['id'],'source_practice_review_id':review['id']}).status_code==409
    assert len(client.get(f'/api/v1/questions/{q}/saved-answers').get_json())==1
    unrelated=question(client,'Another question')
    assert client.post(f'/api/v1/questions/{unrelated}/saved-answers',json={'content':'wrong source','source_session_item_id':item['id'],'source_practice_review_id':review['id']}).status_code==400


def test_pin_sort_archive_and_original_question_ids_survive_merge(client,app):
    left,right,rid=accepted_pair(client,app)
    a=answer(client,left,'低评分首选',self_rating=1);b=answer(client,right,'高评分回答',self_rating=5)
    for row in (a,b):assert client.patch(f"/api/v1/saved-answers/{row['id']}/pin",json={'is_pinned':True}).status_code==200
    assert merge(client,left,right,rid).status_code==400
    assert merge(client,left,right,rid,pinned_answer_id=b['id']).status_code==200
    rows=client.get(f'/api/v1/questions/{left}/saved-answers').get_json()
    assert [r['id'] for r in rows]==[b['id'],a['id']]
    assert rows[0]['question_id']==right and rows[1]['question_id']==left
    assert rows[0]['is_pinned'] and not rows[1]['is_pinned']
    assert client.get(f'/api/v1/questions/{left}/history').get_json()['saved_answers']==rows
    assert client.get(f'/api/v1/questions/{right}/saved-answers').get_json()==rows
    client.patch(f"/api/v1/saved-answers/{a['id']}/pin",json={'is_pinned':True})
    rows=client.get(f'/api/v1/questions/{left}/saved-answers').get_json()
    assert rows[0]['id']==a['id'] and sum(r['is_pinned'] for r in rows)==1
    client.post(f"/api/v1/saved-answers/{a['id']}/archive")
    assert len(client.get(f'/api/v1/questions/{left}/saved-answers').get_json())==1
    archived=client.get(f'/api/v1/questions/{left}/saved-answers?include_archived=1').get_json()
    assert len(archived)==2
    assert client.get(f"/api/v1/saved-answers/{a['id']}/versions").get_json()[0]['content']=='低评分首选'
    assert client.post(f"/api/v1/saved-answers/{a['id']}/versions",json={'content':'edit archived'}).status_code==409


def test_pin_change_invalidates_merge_preview(client,app):
    left,right,rid=accepted_pair(client,app);a=answer(client,left)
    preview=client.get(f'/api/v1/questions/{left}/merge-preview?source_question_id={right}').get_json()
    client.patch(f"/api/v1/saved-answers/{a['id']}/pin",json={'is_pinned':True})
    response=client.post(f'/api/v1/questions/{left}/merge',json={'canonical_id':left,'source_question_id':right,
        'relation_id':rid,'preview_token':preview['preview_token'],'topic_ids':[],'tag_ids':[]})
    assert response.status_code==409 and response.get_json()['error']['code']=='MERGE_PREVIEW_STALE'


def test_review_can_link_existing_group_version_without_rewriting_its_sources(client,app):
    left,right,rid=accepted_pair(client,app);a=answer(client,right)
    assert merge(client,left,right,rid).status_code==200
    ps=client.post('/api/v1/practice-sessions',json={'mode':'random','limit':100}).get_json()
    item=next(i for i in ps['items'] if i['question_id']==left)
    reviewed=client.post(f"/api/v1/session-items/{item['id']}/review",json={'review_rating':'proficient','saved_answer_version_id':a['current_version']['id']})
    assert reviewed.status_code==201
    assert client.get(f"/api/v1/saved-answers/{a['id']}/versions").get_json()[0]==a['current_version']


def test_concurrent_appends_and_pins_remain_consistent(client,app):
    q=question(client);a=answer(client,q);b=answer(client,q)
    factory=app.extensions['sqlalchemy_session_factory']
    def append(i):
        with factory() as s:return append_version(s,a['id'],{'content':f'version {i}'}).version_no
    with ThreadPoolExecutor(max_workers=2) as pool:assert sorted(pool.map(append,[1,2]))==[2,3]
    def pin(row):
        with factory() as s:set_pin(s,row['id'],{'is_pinned':True})
    with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(pin,[a,b]))
    assert sum(r['is_pinned'] for r in client.get(f'/api/v1/questions/{q}/saved-answers').get_json())==1


def test_rating_order_uses_current_quality_not_mastery(client):
    q=question(client);low=answer(client,q,self_rating=1);high=answer(client,q,self_rating=5);unrated=answer(client,q)
    rows=client.get(f'/api/v1/questions/{q}/saved-answers').get_json()
    assert [r['id'] for r in rows]==[high['id'],low['id'],unrated['id']]
    client.patch(f"/api/v1/saved-answer-versions/{high['current_version']['id']}/rating",json={'self_rating':None})
    assert client.get(f'/api/v1/questions/{q}/saved-answers').get_json()[0]['id']==low['id']


def test_database_rejects_multiple_pins_across_child_ids(client,app):
    left,right,rid=accepted_pair(client,app);a=answer(client,left);b=answer(client,right)
    assert merge(client,left,right,rid).status_code==200
    client.patch(f"/api/v1/saved-answers/{a['id']}/pin",json={'is_pinned':True})
    with app.extensions['sqlalchemy_engine'].begin() as c:
        with pytest.raises(IntegrityError):
            c.execute(text('UPDATE saved_answer SET is_pinned=1 WHERE id=:id'),{'id':b['id']})


def test_completed_legacy_child_practice_can_save_after_merge(client,app):
    from app.models.practice import PracticeSession, SessionItem
    left,right,rid=accepted_pair(client,app)
    with app.extensions['sqlalchemy_session_factory'].begin() as s:
        ps=PracticeSession(mode='random',filters_json={});s.add(ps);s.flush()
        item=SessionItem(session_id=ps.id,question_id=right,ordinal=1,status='shown');s.add(item);s.flush();item_id=item.id
    assert merge(client,left,right,rid).status_code==200
    review=client.post(f'/api/v1/session-items/{item_id}/review',json={'review_rating':'basic'}).get_json()
    saved=answer(client,right,source_session_item_id=item_id,source_practice_review_id=review['id'])
    assert saved['question_id']==right
    assert client.get(f'/api/v1/questions/{left}/saved-answers').get_json()[0]['id']==saved['id']
