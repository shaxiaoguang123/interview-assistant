import { flushPromises, mount } from '@vue/test-utils';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import QuestionMergeDialog from '../src/components/QuestionMergeDialog.vue';

const json = (body: unknown, status = 200) => ({ok: status < 400, status, json: async () => body}) as Response;
const member = (id: number) => ({id, text: `原始正文 ${id}`, status:'active', topic_ids:[id], tag_ids:[], candidate_revision:0, candidate_state:null});
function preview(root = 1, pending = false, token = 'a'.repeat(64)) {
  const source = root === 1 ? 2 : 1;
  return {canonical_id:root, source_question_id:source, canonical_question:member(root), source_question:member(source),
    target_members:[member(root)], source_members:[member(source)], relation:{id:5}, preview_token:token,
    topic_union:[{id:1,name:'MCP',is_active:true},{id:2,name:'历史分类',is_active:false}], tag_union:[],
    available_topics:[{id:1,name:'MCP',is_active:true},{id:2,name:'历史分类',is_active:false}], available_tags:[], expected_candidate_revision:pending ? 3 : null};
}
const props = {questionId:1, text:'原始正文 1', otherQuestion:{id:2,text:'原始正文 2',status:'active',candidate_state:null}, relationId:5, pendingCandidate:false};
const wrappers: Array<ReturnType<typeof mount>> = [];
function open(extra = {}) { const w = mount(QuestionMergeDialog,{props:{...props,...extra},attachTo:document.body,global:{stubs:{RouterLink:true}}}); wrappers.push(w);return w; }
beforeEach(() => {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open',''); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute('open'); };
});
afterEach(() => { wrappers.splice(0).forEach(w => w.unmount()); document.body.innerHTML='';vi.unstubAllGlobals(); });
function api(options:{pending?:boolean;stale?:boolean} = {}) {
  let stale = options.stale;
  const fetch = vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
    const path = String(input);
    if(path.endsWith('/history')) return json({sources:[],practice_reviews:[],session_items:[],member_question_ids:[1]});
    if(init?.method === 'POST') {
      if(stale) {stale=false;return json({error:{code:'MERGE_PREVIEW_STALE',message:'changed'}},409);}
      return json({id:JSON.parse(String(init.body)).canonical_id});
    }
    return json(preview(path.includes('/questions/2/') ? 2 : 1, options.pending, fetch.mock.calls.filter(([p])=>String(p).includes('merge-preview')).length > 1 ? 'b'.repeat(64):'a'.repeat(64)));
  });vi.stubGlobal('fetch',fetch);return fetch;
}
describe('explicit canonical merge dialog',()=>{
  it('previews union and inactive labels, then cancels without posting a merge',async()=>{
    const fetch=api();const w=open();await flushPromises();
    expect(w.text()).toContain('原始正文 1');expect(w.text()).toContain('原始正文 2');expect(w.text()).toContain('停用');
    expect(w.get('input[aria-label="最终 Topic 历史分类"]').element).toHaveProperty('checked',true);
    await w.get('button[aria-label="取消归并"]').trigger('click');
    expect(w.emitted('close')).toBeTruthy();expect(fetch.mock.calls.some(([,init])=>init?.method==='POST')).toBe(false);
  });
  it.each([1,2])('keeps chosen root %s and requires final confirmation',async(root)=>{
    const fetch=api();const w=open();await flushPromises();
    if(root===2) {await w.get('input[aria-label="选择规范题 2"]').setValue();await flushPromises();}
    expect(fetch.mock.calls.some(([,init])=>init?.method==='POST')).toBe(false);
    await w.get('button[aria-label="确认归并"]').trigger('click');await flushPromises();
    const post=fetch.mock.calls.find(([,init])=>init?.method==='POST');
    expect(JSON.parse(String(post?.[1]?.body))).toMatchObject({canonical_id:root,source_question_id:root===1?2:1,relation_id:5,topic_ids:[1,2]});
    expect(w.emitted('merged')?.[0]?.[0]).toEqual({canonicalId:root,sourceId:root===1?2:1});
  });
  it('fixes an OCR candidate as source and sends the previewed candidate revision',async()=>{
    const fetch=api({pending:true});const w=open({questionId:2,otherQuestion:{...props.otherQuestion,id:1},pendingCandidate:true});await flushPromises();
    expect(w.find('input[aria-label="选择规范题 2"]').exists()).toBe(false);
    await w.get('button[aria-label="确认归并"]').trigger('click');await flushPromises();
    expect(JSON.parse(String(fetch.mock.calls.find(([,init])=>init?.method==='POST')?.[1]?.body))).toMatchObject({canonical_id:1,source_question_id:2,expected_candidate_revision:3});
  });
  it('requires refreshed preview and a second explicit confirmation after a real 409 response',async()=>{
    const fetch=api({stale:true});const w=open();await flushPromises();
    await w.get('button[aria-label="确认归并"]').trigger('click');await flushPromises();
    expect(w.text()).toContain('预览已过期');expect(w.get('button[aria-label="确认归并"]').attributes('disabled')).toBeDefined();
    expect(fetch.mock.calls.filter(([,init])=>init?.method==='POST')).toHaveLength(1);
    await w.get('button[aria-label="重新获取归并预览"]').trigger('click');await flushPromises();
    expect(fetch.mock.calls.filter(([,init])=>init?.method==='POST')).toHaveLength(1);
    await w.get('button[aria-label="确认归并"]').trigger('click');await flushPromises();
    expect(JSON.parse(String(fetch.mock.calls.filter(([,init])=>init?.method==='POST')[1][1]?.body)).preview_token).toBe('b'.repeat(64));
  });
  it('ignores an old preview when the direction changes',async()=>{
    let resolve!: (r:Response)=>void;let first=true;
    vi.stubGlobal('fetch',vi.fn(async(input:RequestInfo|URL)=>{
      if(String(input).endsWith('/history'))return json({sources:[],practice_reviews:[],session_items:[]});
      if(first){first=false;return new Promise<Response>(r=>resolve=r);}return json(preview(2));
    }));const w=open();await flushPromises();
    await w.get('input[aria-label="选择规范题 2"]').setValue();await flushPromises();resolve(json(preview(1)));await flushPromises();
    expect(w.get('[data-canonical-id]').attributes('data-canonical-id')).toBe('2');
  });
  it('does not emit an old merge result after unmount',async()=>{
    const fetch=api();const w=open();await flushPromises();let resolve!:(r:Response)=>void;
    fetch.mockImplementationOnce(()=>new Promise<Response>(r=>resolve=r));
    await w.get('button[aria-label="确认归并"]').trigger('click');w.unmount();wrappers.pop();resolve(json({id:1}));await flushPromises();
    expect(w.emitted('merged')).toBeUndefined();
  });
});

import QuestionRelationReview from '../src/components/QuestionRelationReview.vue';
import QuestionDetailPage from '../src/pages/QuestionDetailPage.vue';
import InboxPage from '../src/pages/InboxPage.vue';
import { createMemoryHistory } from 'vue-router';
import { createAppRouter } from '../src/router';
const rel = () => ({id:5,question_id:1,related_question_id:2,relation_type:'same_question',decision_status:'suggested',suggested_by:'rule',confidence:1,match_kind:'exact',review_token:'a'.repeat(64),other_question:props.otherQuestion});
const similar = (id:number,accepted=false,rows=[rel()])=>({question_id:id,canonical_question_id:id,candidate_state:null,total_count:rows.length,unresolved_count:rows.length,confirmation_blocked:rows.length>0,scan_required:false,candidates:rows.map(r=>({...r,decision_status:accepted?'accepted':r.decision_status}))});
const detail = (id:number,merged=false)=>({id,text:`原始正文 ${id}`,status:merged?'merged':'active',canonical_question_id:merged?1:id,archived_at:null,topics:[],tags:[],state:{is_favorite:false,is_wrong:false,user_note:null}});
const history = (id:number)=>({canonical_question_id:id,member_question_ids:[id],sources:[],practice_reviews:[],session_items:[]});
it('accepts same_question, keeps confirmation blocked on cancel, and reopens accepted review without another write',async()=>{
  let accepted=false;const fetch=vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
    const path=String(input);
    if(init?.method==='PATCH'){accepted=true;return json({...rel(),decision_status:'accepted'});}
    if(path.endsWith('/history'))return json(history(1));
    if(path.includes('merge-preview'))return json(preview());
    return json(similar(1,accepted));
  });vi.stubGlobal('fetch',fetch);
  const w=mount(QuestionRelationReview,{props:{questionId:1,text:'原始正文 1'},global:{stubs:{RouterLink:true}},attachTo:document.body});wrappers.push(w);
  await flushPromises();await w.get('button[aria-label="确认为同题并归并关系 5"]').trigger('click');await flushPromises();
  expect(w.findComponent(QuestionMergeDialog).exists()).toBe(true);
  expect(w.emitted('state')?.at(-1)?.[0]).toMatchObject({canConfirm:false});
  await w.get('button[aria-label="取消归并"]').trigger('click');await flushPromises();
  expect(document.activeElement?.getAttribute('aria-label')).toBe('确认为同题并归并关系 5');
  expect(w.text()).toContain('同题待归并');expect(fetch.mock.calls.some(([,init])=>init?.method==='POST')).toBe(false);
  await w.get('button[aria-label="确认为同题并归并关系 5"]').trigger('click');await flushPromises();
  expect(fetch.mock.calls.filter(([,init])=>init?.method==='PATCH')).toHaveLength(1);
});
it('replaces a merged child route, preserves explicit original history access, and ignores old child loads',async()=>{
  vi.stubGlobal('fetch',vi.fn(async(input:RequestInfo|URL)=>{
    const path=String(input);if(path.endsWith('/history'))return json({...history(1),member_question_ids:[1,2]});
    if(path.includes('similar-candidates'))return json(similar(1,false,[]));
    if(path.endsWith('/topics')||path.endsWith('/tags'))return json([]);
    return json(detail(path.endsWith('/2')?2:1,path.endsWith('/2')));
  }));const router=createAppRouter(createMemoryHistory());await router.push('/questions/2');await router.isReady();
  const w=mount(QuestionDetailPage,{global:{plugins:[router]}});wrappers.push(w);await flushPromises();
  expect(router.currentRoute.value.path).toBe('/questions/1');expect(w.text()).toContain('原题 #2');
  await router.push('/questions/2?history=1');await flushPromises();
  expect(w.find('textarea[aria-label="题目正文"]').exists()).toBe(false);expect(w.text()).toContain('原始内容只读');
});
it('refreshes a surviving detail and history after the GUI merge',async()=>{
  let merged=false;let accepted=false;let reads=0;
  vi.stubGlobal('fetch',vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
    const path=String(input);
    if(path.endsWith('/merge')){merged=true;return json({id:1});}
    if(init?.method==='PATCH'){accepted=true;return json({...rel(),decision_status:'accepted'});}
    if(path.includes('merge-preview'))return json(preview());
    if(path.endsWith('/history')){reads++;return json({...history(1),member_question_ids:merged?[1,2]:[1]});}
    if(path.includes('similar-candidates'))return json(similar(1,accepted,merged?[]:[rel()]));
    if(path.endsWith('/topics')||path.endsWith('/tags'))return json([]);return json(detail(Number(path.split('/').at(-1))));
  }));const router=createAppRouter(createMemoryHistory());await router.push('/questions/1');await router.isReady();
  const w=mount(QuestionDetailPage,{global:{plugins:[router]},attachTo:document.body});wrappers.push(w);await flushPromises();
  await w.get('button[aria-label="确认为同题并归并关系 5"]').trigger('click');await flushPromises();
  await w.get('button[aria-label="确认归并"]').trigger('click');await flushPromises();
  expect(w.text()).toContain('归并成功');expect(w.text()).toContain('2 道原题');expect(reads).toBeGreaterThanOrEqual(3);
  await router.push('/questions/3');await flushPromises();expect(w.text()).not.toContain('归并成功');
  await router.push('/questions/1');await flushPromises();expect(w.text()).not.toContain('归并成功');
});
it('refreshes an OCR candidate as confirmed merged history and offers its root',async()=>{
  let merged=false;let accepted=false;
  const candidate=()=>({...detail(2,merged),candidate_state:merged?'confirmed':'pending_review',candidate_revision:merged?4:3,
    status:merged?'merged':'pending_review',split_from_candidate_id:null,split_child_ids:[],superseded_by_candidate_id:null,sources:[]});
  vi.stubGlobal('fetch',vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
    const path=String(input);
    if(path.endsWith('/merge')){merged=true;return json({id:1});}
    if(init?.method==='PATCH'){accepted=true;return json({...rel(),decision_status:'accepted'});}
    if(path.includes('merge-preview'))return json(preview(1,true));
    if(path.endsWith('/history'))return json(history(1));
    if(path.includes('similar-candidates'))return json({...similar(2,accepted),candidate_state:'pending_review',candidates:[{...rel(),decision_status:accepted?'accepted':'suggested',other_question:{...props.otherQuestion,id:1}}]});
    if(path.endsWith('/candidates'))return json([candidate()]);
    if(path==='/api/v1/sources')return json([{id:1,display_width:1100,display_height:700,sha256:'a',ingestion_jobs:[{id:11,source_asset_id:1,status:'succeeded',stage:'completed',candidate_count:1}]}]);
    return json([]);
  }));const w=mount(InboxPage,{global:{stubs:{RouterLink:true}},attachTo:document.body});wrappers.push(w);await flushPromises();
  await w.get('button[aria-label="打开导入任务 11"]').trigger('click');await flushPromises();
  await w.get('button[aria-label="确认为同题并归并关系 5"]').trigger('click');await flushPromises();
  await w.get('button[aria-label="确认归并"]').trigger('click');await flushPromises();
  expect(w.text()).toContain('归并成功');expect(w.text()).toContain('已归并');expect(w.findComponent(QuestionRelationReview).exists()).toBe(false);
  expect(w.findComponent(QuestionMergeDialog).exists()).toBe(false);
});

import IngestionCandidateEditor from '../src/components/IngestionCandidateEditor.vue';
it('requires saving OCR draft edits before independent confirmation or similarity review',async()=>{
  const w=mount(IngestionCandidateEditor,{props:{candidate:{id:2,text:'已保存正文',status:'pending_review',candidate_state:'pending_review',candidate_revision:3,topics:[],tags:[],sources:[]},confirmationBlocked:false}});wrappers.push(w);
  await w.get('textarea[aria-label="候选题正文"]').setValue('尚未保存正文');
  expect(w.get('button[aria-label="确认进入题库"]').attributes('disabled')).toBeDefined();
  expect(w.emitted('dirty-change')?.at(-1)?.[0]).toBe(true);
  expect(w.text()).toContain('请先保存修改');
  await w.get('form[aria-label="候选题正文与分类"]').trigger('submit');
  expect(w.emitted('save')?.[0]?.[0]).toMatchObject({expected_revision:3,text:'尚未保存正文'});
});
it('keeps the unsaved OCR draft gate when reselecting the current candidate',async()=>{
  vi.stubGlobal('fetch',vi.fn(async(input:RequestInfo|URL)=>{
    const path=String(input);
    if(path==='/api/v1/sources')return json([{id:1,display_width:1100,display_height:700,sha256:'a',ingestion_jobs:[{id:11,source_asset_id:1,status:'succeeded',stage:'completed',candidate_count:1}]}]);
    if(path.endsWith('/candidates'))return json([{...detail(2),status:'pending_review',candidate_state:'pending_review',candidate_revision:0,split_from_candidate_id:null,split_child_ids:[],superseded_by_candidate_id:null,sources:[]}]);
    if(path.includes('similar-candidates'))return json({...similar(2),candidate_state:'pending_review',candidates:[{...rel(),other_question:{...props.otherQuestion,id:1}}]});
    return json([]);
  }));const w=mount(InboxPage,{global:{stubs:{RouterLink:true}}});wrappers.push(w);await flushPromises();
  await w.get('button[aria-label="打开导入任务 11"]').trigger('click');await flushPromises();
  await w.get('textarea[aria-label="候选题正文"]').setValue('未保存的草稿');await flushPromises();
  expect(w.get('button[aria-label="确认为同题并归并关系 5"]').attributes('disabled')).toBeDefined();
  await w.get('button[aria-label="查看候选题 2"]').trigger('click');await flushPromises();
  expect(w.get('textarea[aria-label="候选题正文"]').element).toHaveProperty('value','未保存的草稿');
  expect(w.get('button[aria-label="确认为同题并归并关系 5"]').attributes('disabled')).toBeDefined();
});
it('opens pending OCR original evidence as read-only with an Inbox link',async()=>{
  vi.stubGlobal('fetch',vi.fn(async(input:RequestInfo|URL)=>{
    const path=String(input);if(path.endsWith('/history'))return json(history(2));
    if(path.endsWith('/topics')||path.endsWith('/tags'))return json([]);
    return json({...detail(2),status:'pending_review',canonical_question_id:null});
  }));const router=createAppRouter(createMemoryHistory());await router.push('/questions/2?history=1');await router.isReady();
  const w=mount(QuestionDetailPage,{global:{plugins:[router]}});wrappers.push(w);await flushPromises();
  expect(w.text()).toContain('待审核 OCR 候选');expect(w.find('textarea[aria-label="题目正文"]').exists()).toBe(false);
  expect(w.find('button[aria-label="收藏"]').exists()).toBe(false);expect(w.find('a[href="/inbox"]').exists()).toBe(true);
  expect(w.text()).not.toContain('此题已归并');
});
