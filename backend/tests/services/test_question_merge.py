"""Task 4: real migrated SQLite, optimistic preview, atomic canonical writes."""
from datetime import datetime, timezone
from hashlib import sha256
from importlib import import_module
from pathlib import Path
from threading import Barrier
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import event, select, text

from app.errors import ApiError
from app.models.ingestion import IngestionJob, OCRBlock, QuestionSource, QuestionSourceOCRBlock, SourceAsset
from app.models.practice import PracticeReview, PracticeSession, SessionItem
from app.models.question import Question, QuestionRelation, QuestionState, QuestionTag, QuestionTopic
from app.models.taxonomy import Tag, Topic
from app.services.questions import prepare_question_text


def _service():
    assert (Path(__file__).resolve().parents[2] / 'app/services/question_merge.py').is_file(), 'missing canonical merge service'
    return import_module('app.services.question_merge')


def _q(session, value='What is MCP?', **extra):
    value, normalized, digest = prepare_question_text(value)
    item = Question(text=value, normalized_text=normalized, search_text=normalized, normalized_hash=digest,
                    state=QuestionState(is_favorite=False, is_wrong=False), **extra)
    session.add(item); session.flush()
    return item


def _relation(session, left, right, **extra):
    low, high = sorted((left, right), key=lambda q: q.id)
    values = dict(question_id=low.id, related_question_id=high.id, relation_type='same_question',
                  decision_status='accepted', suggested_by='user', confidence=1.,
                  question_text_sha256_snapshot=sha256(low.text.encode()).hexdigest(),
                  related_question_text_sha256_snapshot=sha256(high.text.encode()).hexdigest())
    values.update(extra)
    row = QuestionRelation(**values); session.add(row); session.flush(); return row


@pytest.fixture
def pair(app):
    factory = app.extensions['sqlalchemy_session_factory']
    with factory.begin() as s:
        target = _q(s, status='active'); source = _q(s, status='active')
        relation = _relation(s, target, source)
        topics = [Topic(slug='mcp', name='MCP'), Topic(slug='old',name='旧分类',is_active=False)]
        tags = [Tag(name='协议'), Tag(name='旧标签',is_active=False)]
        s.add_all(topics + tags); s.flush()
        s.add_all([QuestionTopic(question_id=target.id,topic_id=topics[0].id),
                   QuestionTopic(question_id=source.id,topic_id=topics[1].id),
                   QuestionTag(question_id=target.id,tag_id=tags[0].id),
                   QuestionTag(question_id=source.id,tag_id=tags[1].id)])
        result = dict(target=target.id,source=source.id,relation=relation.id,
                      topics=[q.id for q in topics],tags=[q.id for q in tags])
    return result


def _snapshot(app):
    names = ['question','question_relation','question_topic','question_tag','question_state',
             'question_source','question_source_ocr_block','ocr_block','ingestion_job','session_item','practice_review']
    with app.extensions['sqlalchemy_engine'].connect() as c:
        return {name:c.exec_driver_sql(f'SELECT * FROM {name} ORDER BY 1,2').all() for name in names}


def _preview(app, pair):
    with app.extensions['sqlalchemy_session_factory']() as s:
        return _service().preview_question_merge(s, pair['target'], pair['source'])


def _payload(pair, preview):
    return dict(canonical_id=pair['target'],source_question_id=pair['source'],relation_id=pair['relation'],
                preview_token=preview['preview_token'],topic_ids=pair['topics'],tag_ids=pair['tags'])


def _merge(app, pair, payload):
    with app.extensions['sqlalchemy_session_factory']() as s:
        return _service().merge_question(s,pair['target'],payload)


def _candidate(app, pair):
    with app.extensions['sqlalchemy_session_factory'].begin() as s:
        asset = SourceAsset(original_filename='synthetic.png',mime_type='image/png',byte_size=12,
                            original_width=100,original_height=80,display_width=100,display_height=80,
                            original_path='synthetic.png',display_preview_path='synthetic.png',sha256='a'*64)
        s.add(asset);s.flush()
        job=IngestionJob(source_asset_id=asset.id,status='succeeded',stage='completed');s.add(job);s.flush()
        block=OCRBlock(ingestion_job_id=job.id,text='raw OCR evidence',bbox_json={'x':.1,'y':.2,'width':.5,'height':.1},reading_order=0,confidence=.9)
        s.add(block);s.flush()
        candidate=s.get(Question,pair['source']);candidate.status='pending_review';candidate.origin_ingestion_job_id=job.id
        candidate.ingestion_candidate_state='pending_review';candidate.candidate_revision=3
        row=QuestionSource(question_id=candidate.id,source_asset_id=asset.id,locator_json=block.bbox_json,
                           source_text_snapshot='raw OCR evidence',raw_ocr_text_snapshot='raw OCR evidence',confidence=.9)
        s.add(row);s.flush();s.add(QuestionSourceOCRBlock(question_source_id=row.id,ocr_block_id=block.id))
    return job.id


def test_preview_is_readonly_and_contains_groups_union_and_inactive_labels(app,pair):
    before=_snapshot(app); result=_preview(app,pair)
    assert result['canonical_question']['id']==pair['target']
    assert result['source_question']['id']==pair['source']
    assert [q['id'] for q in result['target_members']]==[pair['target']]
    assert [q['id'] for q in result['source_members']]==[pair['source']]
    assert [t['id'] for t in result['topic_union']]==pair['topics']
    assert [t['is_active'] for t in result['topic_union']]==[True,False]
    assert [t['id'] for t in result['tag_union']]==pair['tags']
    assert result['relation']['id']==pair['relation'] and result['relation']['decision_status']=='accepted'
    assert len(result['preview_token'])==64 and _preview(app,pair)==result
    assert _snapshot(app)==before


@pytest.mark.parametrize('reverse',[False,True])
def test_merge_both_orientations_preserves_source_taxonomy_and_text(app,pair,reverse):
    if reverse:pair['target'],pair['source']=pair['source'],pair['target']
    before=_snapshot(app); preview=_preview(app,pair); result=_merge(app,pair,_payload(pair,preview))
    assert result.id==pair['target']
    with app.extensions['sqlalchemy_session_factory']() as s:
        source=s.get(Question,pair['source']);root=s.get(Question,pair['target'])
        assert (source.status,source.merged_into_question_id)==('merged',root.id)
        assert (root.status,root.merged_into_question_id)==('active',None)
        assert list(s.scalars(select(QuestionTopic.topic_id).where(QuestionTopic.question_id==root.id).order_by(QuestionTopic.topic_id)))==pair['topics']
        assert list(s.scalars(select(QuestionTag.tag_id).where(QuestionTag.question_id==root.id).order_by(QuestionTag.tag_id)))==pair['tags']
    after=_snapshot(app)
    for name in ['question_state','question_relation']:
        assert after[name]==before[name]
    assert [r for r in after['question_topic'] if r[0]==pair['source']]==[r for r in before['question_topic'] if r[0]==pair['source']]
    assert [r for r in after['question_tag'] if r[0]==pair['source']]==[r for r in before['question_tag'] if r[0]==pair['source']]


def test_group_merge_repoints_all_children_before_their_root(app,pair):
    with app.extensions['sqlalchemy_session_factory'].begin() as s:
        ids=[_q(s,'Historical child '+str(i),status='merged',merged_into_question_id=pair['source']).id for i in range(3)]
        target_child=_q(s,'Target old child',status='merged',merged_into_question_id=pair['target']).id
    preview=_preview(app,pair)
    assert {q['id'] for q in preview['source_members']}=={pair['source'],*ids}
    _merge(app,pair,_payload(pair,preview))
    with app.extensions['sqlalchemy_session_factory']() as s:
        assert {q.id for q in s.scalars(select(Question).where(Question.merged_into_question_id==pair['target']))}=={pair['source'],target_child,*ids}


def test_ocr_merge_atomically_confirms_with_revision_and_preserves_evidence_history(app,pair):
    _candidate(app,pair)
    with app.extensions['sqlalchemy_session_factory'].begin() as s:
        practice=PracticeSession(mode='random',filters_json={},selector_version='test');s.add(practice);s.flush()
        item=SessionItem(session_id=practice.id,question_id=pair['source'],ordinal=0,status='completed');s.add(item);s.flush()
        s.add(PracticeReview(question_id=pair['source'],session_item_id=item.id,review_rating='basic'))
    before=_snapshot(app);preview=_preview(app,pair)
    assert preview['expected_candidate_revision']==3
    payload=_payload(pair,preview);payload['expected_candidate_revision']=3
    _merge(app,pair,payload)
    with app.extensions['sqlalchemy_session_factory']() as s:
        q=s.get(Question,pair['source'])
        assert (q.status,q.ingestion_candidate_state,q.candidate_revision,q.merged_into_question_id)==('merged','confirmed',4,pair['target'])
    after=_snapshot(app)
    for name in ['question_source','question_source_ocr_block','ocr_block','session_item','practice_review','ingestion_job','question_state']:
        assert after[name]==before[name]


@pytest.mark.parametrize('changes',[
    {'decision_status':'suggested'},{'decision_status':'rejected'},
    {'relation_type':'related_question'},{'relation_type':'different_question'},
    {'suggested_by':'rule'}, {'question_text_sha256_snapshot':'a'*64},
])
def test_invalid_or_nonhuman_relation_cannot_preview_or_merge(app,pair,changes):
    with app.extensions['sqlalchemy_session_factory'].begin() as s:
        row=s.get(QuestionRelation,pair['relation'])
        for field,value in changes.items():setattr(row,field,value)
    before=_snapshot(app)
    with pytest.raises(ApiError) as error:_preview(app,pair)
    assert error.value.status_code==409
    with pytest.raises(ApiError) as error:_merge(app,pair,_payload(pair,{'preview_token':'a'*64}))
    assert error.value.status_code==409 and _snapshot(app)==before


@pytest.mark.parametrize('case',['self','archived_target','archived_source','merged_target','merged_source','pending_target','invalid_source','wrong_pair'])
def test_root_eligibility_self_and_wrong_pair_are_rejected(app,pair,case):
    with app.extensions['sqlalchemy_session_factory'].begin() as s:
        if case.startswith('archived'):s.get(Question,pair['target' if case=='archived_target' else 'source']).archived_at=datetime.now(timezone.utc)
        if case.startswith('merged'):
            other=_q(s,'A third canonical',status='active'); q=s.get(Question,pair['target' if case=='merged_target' else 'source'])
            q.status='merged';q.merged_into_question_id=other.id
        if case=='pending_target':s.get(Question,pair['target']).status='pending_review'
        if case=='invalid_source':s.get(Question,pair['source']).status='pending_review'
        if case=='wrong_pair':pair['source']=_q(s,'Unrelated question',status='active').id
    if case=='self':pair['source']=pair['target']
    before=_snapshot(app)
    with pytest.raises(ApiError) as error:_preview(app,pair)
    assert error.value.status_code in (404,409) and _snapshot(app)==before


@pytest.mark.parametrize('change',['text','hash','updated_at','archive','topic_links','tag_links','source_topics','source_tags','taxonomy_name','taxonomy_active','tag_name','tag_active','relation','relation_snapshot','group_members','member_text','candidate_revision','job_status'])
def test_preview_state_change_returns_stale_without_writes(app,pair,change):
    if change in ('candidate_revision','job_status'):_candidate(app,pair)
    if change=='member_text':
        with app.extensions['sqlalchemy_session_factory'].begin() as s:
            child_id=_q(s,'Historical content',status='merged',merged_into_question_id=pair['source']).id
    preview=_preview(app,pair);payload=_payload(pair,preview)
    if change in ('candidate_revision','job_status'):payload['expected_candidate_revision']=3
    with app.extensions['sqlalchemy_session_factory'].begin() as s:
        target=s.get(Question,pair['target']);source=s.get(Question,pair['source'])
        if change=='text':target.text='Ｗhat is MCP?'
        elif change=='hash':source.normalized_hash='b'*64
        elif change=='updated_at':target.updated_at=datetime(2030,1,1,tzinfo=timezone.utc)
        elif change=='archive':target.archived_at=datetime.now(timezone.utc)
        elif change in ('topic_links','source_topics'):
            item=Topic(slug='new',name='new');s.add(item);s.flush();s.add(QuestionTopic(question_id=target.id if change=='topic_links' else source.id,topic_id=item.id))
        elif change in ('tag_links','source_tags'):
            item=Tag(name='new');s.add(item);s.flush();s.add(QuestionTag(question_id=target.id if change=='tag_links' else source.id,tag_id=item.id))
        elif change=='taxonomy_name':s.get(Topic,pair['topics'][0]).name='renamed'
        elif change=='taxonomy_active':s.get(Topic,pair['topics'][0]).is_active=False
        elif change=='tag_name':s.get(Tag,pair['tags'][0]).name='renamed'
        elif change=='tag_active':s.get(Tag,pair['tags'][0]).is_active=False
        elif change=='relation':s.get(QuestionRelation,pair['relation']).decision_status='rejected'
        elif change=='relation_snapshot':s.get(QuestionRelation,pair['relation']).related_question_text_sha256_snapshot='f'*64
        elif change=='group_members':_q(s,'New historical member',status='merged',merged_into_question_id=source.id)
        elif change=='member_text':
            s.get(Question,child_id).text='Edited historical member'
        elif change=='candidate_revision':source.candidate_revision+=1
        elif change=='job_status':s.get(IngestionJob,source.origin_ingestion_job_id).status='failed'
    before=_snapshot(app)
    with pytest.raises(ApiError) as error:_merge(app,pair,payload)
    assert (error.value.status_code,error.value.code)==(409,'MERGE_PREVIEW_STALE')
    assert _snapshot(app)==before


def test_preview_utc_normalization_avoids_false_stale(app,pair):
    service=_service();factory=app.extensions['sqlalchemy_session_factory']
    with factory.begin() as s:
        q=s.get(Question,pair['target']);q.updated_at=datetime(2026,10,10,tzinfo=timezone.utc);s.flush()
        aware=service.preview_question_merge(s,pair['target'],pair['source'])
    assert _preview(app,pair)['preview_token']==aware['preview_token']
    _merge(app,pair,_payload(pair,aware))


def test_failure_after_taxonomy_replacement_rolls_back_every_row(app,pair,monkeypatch):
    _candidate(app,pair);preview=_preview(app,pair);before=_snapshot(app)
    service=_service();original=service.question_repository.replace_question_tags
    def replace_then_fail(session,question_id,ids):
        original(session,question_id,ids);session.flush()
        raise RuntimeError('injected failure after classification, before pointers')
    monkeypatch.setattr(service.question_repository,'replace_question_tags',replace_then_fail)
    payload=_payload(pair,preview);payload['topic_ids']=[];payload['tag_ids']=[];payload['expected_candidate_revision']=3
    with pytest.raises(RuntimeError,match='injected failure'):_merge(app,pair,payload)
    assert _snapshot(app)==before


def test_duplicate_merge_submit_does_not_rewrite_any_row(app,pair):
    payload=_payload(pair,_preview(app,pair));_merge(app,pair,payload);before=_snapshot(app)
    with pytest.raises(ApiError) as error:_merge(app,pair,payload)
    assert error.value.status_code==409 and _snapshot(app)==before


def test_concurrent_merges_have_one_winner_and_take_write_lock_before_read(app,pair):
    service=_service();factory=app.extensions['sqlalchemy_session_factory'];engine=app.extensions['sqlalchemy_engine']
    with factory.begin() as s:
        third=_q(s,'What is MCP?',status='active');relation=_relation(s,third,s.get(Question,pair['source']))
        other={**pair,'target':third.id,'relation':relation.id}
    jobs=[(p,_payload(p,_preview(app,p))) for p in (pair,other)]
    barrier=Barrier(2);queries=[]
    def record(connection,cursor,statement,parameters,context,many):queries.append(statement)
    event.listen(engine,'before_cursor_execute',record)
    def run(job):
        p,payload=job;barrier.wait(timeout=5)
        try:_merge(app,p,payload);return 'success'
        except ApiError as e:return e.code
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(run,jobs))
    finally:event.remove(engine,'before_cursor_execute',record)
    assert results.count('success')==1 and results.count('MERGE_PREVIEW_STALE')==1
    assert queries[0]=='BEGIN IMMEDIATE'
    with factory() as s:
        assert s.get(Question,pair['source']).merged_into_question_id in (pair['target'],other['target'])


@pytest.mark.parametrize('payload_change',[
    {'canonical_id':True},{'canonical_id':999},{'source_question_id':True},{'relation_id':False},
    {'preview_token':None},{'topic_ids':[True]},{'topic_ids':[1,1]},{'tag_ids':'bad'}, {'unexpected':1},
])
def test_merge_rejects_malformed_requests_before_writes(app,pair,payload_change):
    payload=_payload(pair,_preview(app,pair));payload.update(payload_change);before=_snapshot(app)
    with pytest.raises(ApiError) as error:_merge(app,pair,payload)
    assert error.value.status_code==400 and _snapshot(app)==before


def test_inactive_union_can_be_kept_or_explicitly_omitted_but_new_inactive_cannot_be_selected(app,pair):
    with app.extensions['sqlalchemy_session_factory'].begin() as s:
        inactive=Topic(slug='never-linked',name='未关联停用项',is_active=False);s.add(inactive);s.flush();unlinked=inactive.id
    preview=_preview(app,pair);payload=_payload(pair,preview);payload['topic_ids']=[unlinked]
    before=_snapshot(app)
    with pytest.raises(ApiError) as error:_merge(app,pair,payload)
    assert error.value.status_code==400 and _snapshot(app)==before
    payload['topic_ids']=pair['topics'][:1];payload['tag_ids']=pair['tags'][:1]
    _merge(app,pair,payload)
    with app.extensions['sqlalchemy_session_factory']() as s:
        assert list(s.scalars(select(QuestionTopic.topic_id).where(QuestionTopic.question_id==pair['source'])))==pair['topics'][1:]


def test_merge_api_preview_post_and_child_read_mutation_guards(client,app,pair):
    response=client.get(f"/api/v1/questions/{pair['target']}/merge-preview?source_question_id={pair['source']}")
    assert response.status_code==200,response.get_json()
    preview=response.get_json();response=client.post(f"/api/v1/questions/{pair['target']}/merge",json=_payload(pair,preview))
    assert response.status_code==200,response.get_json()
    child=client.get(f"/api/v1/questions/{pair['source']}")
    assert child.status_code==200 and child.get_json()['id']==pair['source']
    assert child.get_json()['status']=='merged' and child.get_json()['canonical_question_id']==pair['target']
    before=_snapshot(app)
    for method,path,payload in [('patch','',{'text':'changed'}),('patch','/state',{'is_favorite':True}),('post','/archive',{})]:
        r=getattr(client,method)(f"/api/v1/questions/{pair['source']}"+path,json=payload)
        assert r.status_code==409 and r.get_json()['error']['fields']['canonical_question_id']==str(pair['target'])
    assert _snapshot(app)==before


def test_backend_same_question_review_unlocked_but_standalone_confirm_remains_blocked(client,app,pair):
    _candidate(app,pair)
    with app.extensions['sqlalchemy_session_factory'].begin() as s:
        r=s.get(QuestionRelation,pair['relation']);r.decision_status='suggested';r.suggested_by='rule'
    current=client.get(f"/api/v1/questions/{pair['source']}/similar-candidates").get_json()['candidates'][0]
    reviewed=client.patch(f"/api/v1/question-relations/{pair['relation']}",json={
        'question_id':pair['source'],'relation_type':'same_question','decision_status':'accepted','expected_review_token':current['review_token']})
    assert reviewed.status_code==200,reviewed.get_json()
    candidate=client.get(f"/api/v1/questions/{pair['source']}").get_json()
    assert candidate['status']=='pending_review'
    assert client.post(f"/api/v1/ingestion-candidates/{pair['source']}/confirm",json={'expected_revision':3}).status_code==409
    # Reclassification remains the way to continue the staged GUI without Merge.
    reviewed=client.patch(f"/api/v1/question-relations/{pair['relation']}",json={
        'question_id':pair['source'],'relation_type':'different_question','decision_status':'accepted','expected_review_token':reviewed.get_json()['review_token']})
    assert reviewed.status_code==200
    # Standalone confirmation still requires active classification; merge may
    # preserve inactive historical union labels, while ordinary Confirm may not.
    corrected=client.patch(f"/api/v1/ingestion-candidates/{pair['source']}",json={
        'expected_revision':3,'topic_ids':pair['topics'][:1],'tag_ids':pair['tags'][:1]})
    assert corrected.status_code==200,corrected.get_json()
    assert client.post(f"/api/v1/ingestion-candidates/{pair['source']}/confirm",json={'expected_revision':4}).status_code==200


@pytest.mark.parametrize('query',['','?source_question_id=true','?source_question_id=-1','?source_question_id=1&source_question_id=2'])
def test_preview_api_rejects_invalid_source_id(client,pair,query):
    response=client.get(f"/api/v1/questions/{pair['target']}/merge-preview"+query)
    assert response.status_code==400


@pytest.mark.parametrize('revision',[None,2,True])
def test_pending_candidate_requires_exact_current_revision(app,pair,revision):
    _candidate(app,pair);preview=_preview(app,pair);payload=_payload(pair,preview)
    if revision is not None:payload['expected_candidate_revision']=revision
    before=_snapshot(app)
    with pytest.raises(ApiError) as error:_merge(app,pair,payload)
    assert error.value.status_code in (400,409) and _snapshot(app)==before


def test_fts_and_sqlite_integrity_remain_intact_after_merge(app,pair):
    _merge(app,pair,_payload(pair,_preview(app,pair)))
    with app.extensions['sqlalchemy_engine'].connect() as c:
        assert c.exec_driver_sql('PRAGMA foreign_key_check').all()==[]
        assert c.exec_driver_sql('PRAGMA integrity_check').scalar()=='ok'
        assert c.exec_driver_sql("SELECT count(*) FROM question_fts WHERE question_fts MATCH 'mcp'").scalar()==2
        assert c.exec_driver_sql("SELECT count(*) FROM sqlite_master WHERE type='trigger' AND name LIKE 'question_fts_%'").scalar()==3

@pytest.mark.parametrize('operation',['text','state','archive'])
def test_direct_question_mutations_reserve_sqlite_before_child_guard(app,pair,operation):
    # A read-only child guard must not be decided on a pre-merge snapshot and
    # then write after another connection commits a canonical merge.
    from app.services.questions import update_question, update_question_state, archive_question
    engine=app.extensions['sqlalchemy_engine'];statements=[]
    def record(connection,cursor,statement,parameters,context,many):statements.append(statement)
    event.listen(engine,'before_cursor_execute',record)
    try:
        with app.extensions['sqlalchemy_session_factory']() as s:
            if operation=='text':update_question(s,pair['source'],{'answer_type':'explanation'})
            elif operation=='state':update_question_state(s,pair['source'],{'is_wrong':True})
            else:archive_question(s,pair['source'])
    finally:event.remove(engine,'before_cursor_execute',record)
    assert statements[0]=='BEGIN IMMEDIATE'


def test_merged_ocr_candidate_api_retains_original_id_and_exposes_root(client, app, pair):
    job_id = _candidate(app, pair)
    preview = _preview(app, pair)
    payload = _payload(pair, preview)
    payload['expected_candidate_revision'] = 3
    _merge(app, pair, payload)
    response = client.get(f'/api/v1/ingestions/{job_id}/candidates')
    assert response.status_code == 200
    candidate = next(q for q in response.json if q['id'] == pair['source'])
    assert candidate['canonical_question_id'] == pair['target']
    assert (candidate['status'], candidate['candidate_state'], candidate['candidate_revision']) == ('merged', 'confirmed', 4)
    assert candidate['sources'][0]['question_source_id'] > 0
