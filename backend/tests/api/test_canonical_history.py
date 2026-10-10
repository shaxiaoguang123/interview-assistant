"""Canonical reads must preserve IDs and immutable evidence in migrated SQLite."""
from datetime import datetime, timezone

import pytest
from sqlalchemy import event, select

from app.models.ingestion import IngestionJob, OCRBlock, QuestionSource, QuestionSourceOCRBlock, SourceAsset
from app.models.practice import PracticeReview, PracticeSession, SessionItem
from app.models.question import Question, QuestionState, QuestionTag, QuestionTopic
from app.models.taxonomy import Tag, Topic
from app.services.questions import prepare_question_text, update_question_state


def _q(session, value, **extra):
    value, normalized, digest = prepare_question_text(value)
    row = Question(text=value, normalized_text=normalized, search_text=normalized,
                   normalized_hash=digest, status=extra.pop('status', 'active'), **extra)
    session.add(row)
    session.flush()
    return row


@pytest.fixture
def group(app):
    with app.extensions['sqlalchemy_session_factory'].begin() as s:
        root = _q(s, '规范题：工具协议的设计边界')
        children = [_q(s, value, status='merged', merged_into_question_id=root.id) for value in (
            'LangGraph持久化与 Function Calling 历史证据',
            'MCP 通信协议与 RAG 检索重排历史证据',
            'Function Calling 历史证据另一版本',
        )]
        plain = _q(s, '普通题：历史证据 independent')
        pending = _q(s, 'pending historical evidence', status='pending_review')
        topics = [Topic(slug='final', name='最终分类'), Topic(slug='historical', name='历史分类')]
        tags = [Tag(name='最终标签'), Tag(name='历史标签')]
        s.add_all(topics + tags)
        s.flush()
        s.add_all([QuestionTopic(question_id=root.id, topic_id=topics[0].id),
                   QuestionTopic(question_id=children[0].id, topic_id=topics[1].id),
                   QuestionTag(question_id=root.id, tag_id=tags[0].id),
                   QuestionTag(question_id=children[0].id, tag_id=tags[1].id)])
        asset = SourceAsset(original_filename='synthetic.png', mime_type='image/png', byte_size=10,
                            original_width=100, original_height=80, display_width=100, display_height=80,
                            original_path='synthetic.png', display_preview_path='synthetic.png', sha256='a'*64)
        s.add(asset); s.flush()
        job = IngestionJob(source_asset_id=asset.id, status='succeeded', stage='completed')
        s.add(job); s.flush()
        block = OCRBlock(ingestion_job_id=job.id, text='原始 OCR exact 文本',
                         bbox_json={'x':.1,'y':.2,'width':.5,'height':.1}, reading_order=0, confidence=.9)
        s.add(block); s.flush()
        sources = []
        for q in (root, children[0]):
            source = QuestionSource(question_id=q.id, source_asset_id=asset.id,
                locator_json=block.bbox_json, source_text_snapshot='不可覆盖来源',
                raw_ocr_text_snapshot=block.text, confidence=.9)
            s.add(source); s.flush()
            s.add(QuestionSourceOCRBlock(question_source_id=source.id, ocr_block_id=block.id))
            sources.append(source.id)
        reviews = []
        for q in (root, children[0]):
            ps = PracticeSession(mode='random', filters_json={})
            s.add(ps); s.flush()
            item = SessionItem(session_id=ps.id, question_id=q.id, ordinal=1, status='completed')
            s.add(item); s.flush()
            review = PracticeReview(question_id=q.id, session_item_id=item.id, review_rating='basic')
            s.add(review); s.flush()
            reviews.append(review.id)
        ps = PracticeSession(mode='random', filters_json={})
        s.add(ps); s.flush()
        item = SessionItem(session_id=ps.id, question_id=children[1].id, ordinal=1, status='shown')
        s.add(item); s.flush()
        result = dict(root=root.id, children=[q.id for q in children], plain=plain.id, pending=pending.id,
                      topics=[t.id for t in topics], tags=[t.id for t in tags], sources=sources,
                      reviews=reviews, old_session=ps.id, old_item=item.id, block=block.id)
    return result


@pytest.mark.parametrize('query', ['LangGraph', 'LangGraph 持久化', 'MCP 通信协议', 'RAG 检索重排', 'Function Calling'])
def test_child_only_search_resolves_root_once(client, group, query):
    response = client.get('/api/v1/questions', query_string={'q':query})
    assert response.status_code == 200
    assert [row['id'] for row in response.get_json()] == [group['root']]


def test_search_classification_is_root_final_not_child(client, group):
    for field, ids in (('topic_ids', group['topics']), ('tag_ids', group['tags'])):
        assert [q['id'] for q in client.get('/api/v1/questions',query_string={'q':'LangGraph',field:ids[0]}).get_json()] == [group['root']]
        assert client.get('/api/v1/questions',query_string={'q':'LangGraph',field:ids[1]}).get_json() == []


def test_root_and_many_children_search_is_stable_and_deduplicated(client, app, group):
    with app.extensions['sqlalchemy_session_factory'].begin() as s:
        q = s.get(Question,group['root'])
        q.text, q.normalized_text, q.normalized_hash = prepare_question_text('Root Function Calling 历史证据')
        q.search_text = q.normalized_text
    results = [client.get('/api/v1/questions?q=Function+Calling').get_json() for _ in range(3)]
    assert results[0] == results[1] == results[2]
    assert [q['id'] for q in results[0]] == [group['root']]
    with app.extensions['sqlalchemy_engine'].connect() as c:
        assert c.exec_driver_sql('PRAGMA integrity_check').scalar() == 'ok'
        assert c.exec_driver_sql('PRAGMA foreign_key_check').all() == []
        assert len(c.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'question_fts_%'").all()) == 3


@pytest.mark.parametrize('field', ['is_favorite','is_wrong'])
@pytest.mark.parametrize('marked', ['root','child','mixed','none'])
def test_group_true_false_filters_and_detail_or(client, app, group, field, marked):
    with app.extensions['sqlalchemy_session_factory'].begin() as s:
        s.add(QuestionState(question_id=group['plain'], is_favorite=False, is_wrong=False))
        if marked != 'none':
            ids = [group['root']] if marked == 'root' else [group['children'][0]]
            for qid in ids:
                s.add(QuestionState(question_id=qid, **{field:True}, user_note='历史 note'))
            if marked == 'mixed':
                s.add(QuestionState(question_id=group['root'], **{field:False}))
    true_ids = [q['id'] for q in client.get('/api/v1/questions',query_string={field:'true'}).get_json()]
    false_ids = [q['id'] for q in client.get('/api/v1/questions',query_string={field:'false'}).get_json()]
    assert true_ids == ([] if marked == 'none' else [group['root']])
    assert set(false_ids) == ({group['root'],group['plain']} if marked == 'none' else {group['plain']})
    assert client.get(f"/api/v1/questions/{group['root']}").get_json()['state'][field] == (marked != 'none')


@pytest.mark.parametrize('field',['is_favorite','is_wrong'])
def test_group_disable_clears_all_flags_atomically_without_notes(client, app, group, field):
    with app.extensions['sqlalchemy_session_factory'].begin() as s:
        for qid in (group['root'],*group['children']):
            s.add(QuestionState(question_id=qid,is_favorite=True,is_wrong=True,user_note=f'note {qid}'))
    response = client.patch(f"/api/v1/questions/{group['root']}/state",json={field:False})
    assert response.status_code == 200 and response.get_json()[field] is False
    other = 'is_wrong' if field == 'is_favorite' else 'is_favorite'
    assert response.get_json()[other] is True
    with app.extensions['sqlalchemy_session_factory']() as s:
        rows = list(s.scalars(select(QuestionState)))
        assert all(not getattr(row,field) and getattr(row,other) and row.user_note == f'note {row.question_id}' for row in rows)
    assert client.patch(f"/api/v1/questions/{group['root']}/state",json={field:True}).status_code == 200
    with app.extensions['sqlalchemy_session_factory']() as s:
        assert getattr(s.get(QuestionState,group['root']),field)
        assert all(not getattr(s.get(QuestionState,qid),field) for qid in group['children'])


def test_state_response_aggregates_other_flag_without_creating_child_state(client, app, group):
    with app.extensions['sqlalchemy_session_factory'].begin() as s:
        s.add(QuestionState(question_id=group['children'][0],is_wrong=True,user_note='child untouched'))
    body = client.patch(f"/api/v1/questions/{group['root']}/state",json={'is_favorite':True}).get_json()
    assert body['is_wrong'] is True
    with app.extensions['sqlalchemy_session_factory']() as s:
        assert s.get(QuestionState,group['children'][1]) is None
        assert not s.get(QuestionState,group['root']).is_wrong


def test_group_state_failure_rolls_back_all_updates(app, group):
    with app.extensions['sqlalchemy_session_factory'].begin() as s:
        for qid in (group['root'],*group['children']):
            s.add(QuestionState(question_id=qid,is_favorite=True,user_note='preserved'))
    engine = app.extensions['sqlalchemy_engine']
    def fail_after_update(_conn,_cursor,statement,_parameters,_context,_many):
        if statement.lstrip().upper().startswith('UPDATE QUESTION_STATE'):
            raise RuntimeError('injected after state update')
    event.listen(engine,'after_cursor_execute',fail_after_update)
    try:
        with app.extensions['sqlalchemy_session_factory']() as s:
            with pytest.raises(RuntimeError):
                update_question_state(s,group['root'],{'is_favorite':False})
    finally:
        event.remove(engine,'after_cursor_execute',fail_after_update)
    with app.extensions['sqlalchemy_session_factory']() as s:
        assert all(row.is_favorite and row.user_note == 'preserved' for row in s.scalars(select(QuestionState)))


def test_history_retains_exact_endpoint_payloads_original_ids_and_readonly_rows(client,app,group):
    engine = app.extensions['sqlalchemy_engine']
    names=['question_source','question_source_ocr_block','ocr_block','session_item','practice_review','question_topic','question_tag']
    def snapshot():
        with engine.connect() as c:
            return {name:c.exec_driver_sql(f'SELECT * FROM {name} ORDER BY 1,2').all() for name in names}
    before=snapshot()
    exact_sources=[]; exact_reviews=[]
    for qid in (group['root'],*group['children']):
        exact_sources += client.get(f'/api/v1/questions/{qid}/sources').get_json()
        exact_reviews += client.get(f'/api/v1/questions/{qid}/practice-reviews').get_json()
    for qid in (group['root'],group['children'][0]):
        response=client.get(f'/api/v1/questions/{qid}/history')
        assert response.status_code == 200
        result=response.get_json()
        assert result['canonical_question_id'] == group['root']
        assert result['member_question_ids'] == [group['root'],*group['children']]
        assert result['sources'] == sorted(exact_sources,key=lambda x:x['question_source_id'])
        assert result['practice_reviews'] == sorted(exact_reviews,key=lambda x:(x['reviewed_at'],x['id']),reverse=True)
        assert {row['question_id'] for row in result['session_items']} == {group['root'],group['children'][0],group['children'][1]}
        assert {'id','question_id','session_id','ordinal','status','viewed_at','completed_at','selection_reason'} <= result['session_items'][0].keys()
    assert snapshot() == before


@pytest.mark.parametrize('action',['review','skip'])
def test_historical_child_session_remains_readable_and_terminal(client,group,action):
    body=client.get(f"/api/v1/practice-sessions/{group['old_session']}").get_json()
    assert body['items'][0]['question_id'] == group['children'][1]
    assert body['items'][0]['question']['status'] == 'merged'
    response=client.post(f"/api/v1/session-items/{group['old_item']}/{action}",json={'review_rating':'proficient'} if action=='review' else None)
    assert response.status_code == (201 if action=='review' else 200)
    if action=='review':
        review=response.get_json()
        assert review['question_id'] == group['children'][1] and review['session_item_id'] == group['old_item']
        corrected=client.patch(f"/api/v1/practice-reviews/{review['id']}",json={'review_rating':'vague'}).get_json()
        assert corrected['question_id'] == review['question_id'] and corrected['session_item_id'] == review['session_item_id']


@pytest.mark.parametrize('mode',['random','topic','tag'])
def test_new_selectors_only_roots(client,group,mode):
    field='topic_ids' if mode=='topic' else 'tag_ids'
    filters={} if mode=='random' else {field:[group['topics' if mode=='topic' else 'tags'][0]]}
    response=client.post('/api/v1/practice-sessions',json={'mode':mode,'filters':filters,'limit':100})
    assert response.status_code == 201
    ids=[row['question_id'] for row in response.get_json()['items']]
    assert len(ids)==len(set(ids)) and not set(ids)&set(group['children'])
    assert set(ids)==({group['root'],group['plain']} if mode=='random' else {group['root']})


def test_child_direct_read_writes_forbidden_and_history_not_found(client,group):
    qid=group['children'][0]
    before=client.get(f'/api/v1/questions/{qid}').get_json()
    assert before['id']==qid and before['canonical_question_id']==group['root']
    assert client.patch(f'/api/v1/questions/{qid}',json={'text':'wrong'}).status_code==409
    assert client.patch(f'/api/v1/questions/{qid}/state',json={'is_favorite':True}).status_code==409
    assert client.post(f'/api/v1/questions/{qid}/archive').status_code==409
    assert client.get(f'/api/v1/questions/{qid}').get_json()==before
    assert client.get('/api/v1/questions/99999/history').status_code==404


def test_plain_empty_and_archived_history_remain_readable(client,group):
    qid=group['plain']
    assert client.post(f'/api/v1/questions/{qid}/archive').status_code==200
    history=client.get(f'/api/v1/questions/{qid}/history').get_json()
    assert history == {'canonical_question_id':qid,'member_question_ids':[qid],
                       'sources':[],'practice_reviews':[],'session_items':[], 'saved_answers':[]}
    assert qid not in [q['id'] for q in client.get('/api/v1/questions').get_json()]
    assert qid in [q['id'] for q in client.get('/api/v1/questions?include_archived=true').get_json()]


@pytest.mark.parametrize('field',['is_favorite','is_wrong'])
def test_child_search_combines_group_state_and_final_taxonomy(client,app,group,field):
    with app.extensions['sqlalchemy_session_factory'].begin() as s:
        s.add(QuestionState(question_id=group['children'][2],**{field:True}))
    filters={'q':'LangGraph','topic_ids':group['topics'][0],'tag_ids':group['tags'][0],field:'true'}
    assert [q['id'] for q in client.get('/api/v1/questions',query_string=filters).get_json()]==[group['root']]
    filters[field]='false'
    assert client.get('/api/v1/questions',query_string=filters).get_json()==[]


def test_root_member_count_supports_safe_list_archive_controls(client,group):
    roots={q['id']:q for q in client.get('/api/v1/questions').get_json()}
    assert roots[group['root']]['canonical_member_count']==4
    assert roots[group['plain']]['canonical_member_count']==1
    assert client.get(f"/api/v1/questions/{group['root']}").get_json()['canonical_member_count']==4
