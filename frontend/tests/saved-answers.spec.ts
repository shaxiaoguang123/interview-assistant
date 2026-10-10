import { mount, flushPromises } from '@vue/test-utils';
import { describe, it, expect, vi } from 'vitest';
import { createMemoryHistory } from 'vue-router';
import { createAppRouter } from '../src/router';
import SavedAnswersPanel from '../src/components/answers/SavedAnswersPanel.vue';
import PracticeSessionPage from '../src/pages/PracticeSessionPage.vue';
import QuestionMergeDialog from '../src/components/QuestionMergeDialog.vue';
import type { SavedAnswer } from '../src/api/saved-answers';
const json=(data:unknown,status=200)=>({ok:status<400,status,json:async()=>data}) as Response;
const version=(n=1,content='原始答案',rating:number|null=4)=>({id:n,saved_answer_id:1,version_no:n,content,self_rating:rating,self_rating_updated_at:null,origin_kind:'user_written',source_session_item_id:null,source_practice_review_id:null,based_on_version_id:null,assistant_output_id:null,created_at:'2026-10-10T00:00:00Z'});
const answer=():SavedAnswer=>({id:1,question_id:2,source_session_item_id:null,is_pinned:false,archived_at:null,created_at:'2026-10-10T00:00:00Z',updated_at:'2026-10-10T00:00:00Z',version_count:1,current_version:version()});
const button=(w:ReturnType<typeof mount>,text:string)=>w.findAll('button').find(b=>b.text()===text)!;
function deferred<T>(){let resolve!:(v:T)=>void;const promise=new Promise<T>(r=>resolve=r);return {promise,resolve};}

describe('saved answer management',()=>{
  it('keeps a new draft local on cancel and only saves on explicit submit',async()=>{
    let rows:SavedAnswer[]=[];
    const fetch=vi.fn(async(_input:RequestInfo|URL,init?:RequestInit)=>{if(init?.method==='POST'){rows=[{...answer(),current_version:{...version(),content:JSON.parse(String(init.body)).content}}];return json(rows[0],201);}return json(rows);});
    vi.stubGlobal('fetch',fetch);const w=mount(SavedAnswersPanel,{props:{questionId:2}});await flushPromises();
    await button(w,'新建回答').trigger('click');await w.get('textarea').setValue('未保存草稿');await button(w,'取消').trigger('click');
    expect(fetch.mock.calls.some(([,init])=>init?.method==='POST')).toBe(false);
    await button(w,'新建回答').trigger('click');await w.get('textarea').setValue('主动保存');await w.get('form').trigger('submit');await flushPromises();
    expect(w.text()).toContain('主动保存');expect(w.text()).toContain('回答已保存');
    expect(fetch.mock.calls.filter(([,init])=>init?.method==='POST')).toHaveLength(1);
  });
  it('appends a version, resets quality and lets the user read the unchanged old version',async()=>{
    let row=answer();let versions=[version()];
    vi.stubGlobal('fetch',vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
      if(init?.method==='POST'){const v=version(2,JSON.parse(String(init.body)).content,null);versions=[v,...versions];row={...row,current_version:v,version_count:2};return json(v,201);}
      return json(String(input).includes('/versions')?versions:[row]);
    }));const w=mount(SavedAnswersPanel,{props:{questionId:2}});await flushPromises();
    await button(w,'编辑回答').trigger('click');await w.get('textarea').setValue('第二版答案');await w.get('form').trigger('submit');await flushPromises();
    expect(w.text()).toContain('当前 v2');expect(w.text()).toContain('第二版答案');
    expect((w.get('select[aria-label="回答 1 质量评分"]').element as HTMLSelectElement).value).toBe('');
    await button(w,'版本历史 · 2').trigger('click');await flushPromises();await w.get('select[aria-label="回答 1 历史版本"]').setValue(1);
    expect(w.get('[aria-label="回答版本历史"]').text()).toContain('原始答案');expect(w.get('[aria-label="回答版本历史"]').text()).toContain('4 分');
  });
  it('handles quality, preferred answer, archive confirmation and retained archive history',async()=>{
    let row=answer();const fetch=vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
      const path=String(input);
      if(path.endsWith('/rating')){row.current_version.self_rating=JSON.parse(String(init?.body)).self_rating;return json(row.current_version);}
      if(path.endsWith('/pin')){row.is_pinned=JSON.parse(String(init?.body)).is_pinned;return json(row);}
      if(path.endsWith('/archive')){row.archived_at='2026-10-10T01:00:00Z';row.is_pinned=false;return json(row);}
      return json(row.archived_at&&!path.includes('include_archived')?[]:[row]);
    });vi.stubGlobal('fetch',fetch);const w=mount(SavedAnswersPanel,{props:{questionId:2}});await flushPromises();
    await w.get('select[aria-label="回答 1 质量评分"]').setValue('5');await flushPromises();await button(w,'设为首选').trigger('click');await flushPromises();expect(w.text()).toContain('置顶 · 首选');
    await button(w,'归档').trigger('click');expect(fetch.mock.calls.some(([p])=>String(p).endsWith('/archive'))).toBe(false);
    await button(w,'确认归档').trigger('click');await flushPromises();expect(w.find('[aria-label="保存回答 1"]').exists()).toBe(false);
    await w.get('input[type=checkbox]').setValue(true);await flushPromises();expect(w.text()).toContain('原始答案');expect(w.text()).toContain('已归档');
  });
  it('preserves editor content after failed save and allows retry',async()=>{
    let fail=true;vi.stubGlobal('fetch',vi.fn(async(_input:RequestInfo|URL,init?:RequestInit)=>init?.method==='POST'?(fail?json({error:{message:'保存失败'}},409):json(answer(),201)):json([])));
    const w=mount(SavedAnswersPanel,{props:{questionId:2}});await flushPromises();await button(w,'新建回答').trigger('click');await w.get('textarea').setValue('保留的正文');await w.get('form').trigger('submit');await flushPromises();
    expect(w.get('[role=alert]').text()).toContain('保存失败');expect((w.get('textarea').element as HTMLTextAreaElement).value).toBe('保留的正文');fail=false;await w.get('form').trigger('submit');await flushPromises();expect(w.find('textarea').exists()).toBe(false);
  });
  it('ignores a late answer list from the previous question',async()=>{
    const old=deferred<Response>();vi.stubGlobal('fetch',vi.fn(async(input:RequestInfo|URL)=>String(input).includes('/1/')?old.promise:json([])));
    const w=mount(SavedAnswersPanel,{props:{questionId:1}});await w.setProps({questionId:2});await flushPromises();old.resolve(json([answer()]));await flushPromises();expect(w.text()).not.toContain('原始答案');
  });
});

async function practiceSetup(failSave=false){
  let completed=false;const fetch=vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
    const path=String(input);if(path.endsWith('/review')){completed=true;return json({id:90},201);}
    if(path.endsWith('/saved-answers'))return failSave?json({error:{message:'保存失败'}},503):json(answer(),201);
    return json({id:5,mode:'random',completed_at:completed?'2026-10-10T00:00:00Z':null,items:[{id:51,question_id:2,ordinal:1,status:completed?'completed':'shown',question:{id:2,text:'练习题目',status:'active',archived_at:null}}]});
  });vi.stubGlobal('fetch',fetch);const router=createAppRouter(createMemoryHistory());await router.push('/practice/sessions/5');await router.isReady();const w=mount(PracticeSessionPage,{global:{plugins:[router]}});await flushPromises();return {w,fetch,router};
}
describe('practice saving decision',()=>{
  it('keeps final draft after mastery and saves with the real item and review source',async()=>{
    const {w,fetch}=await practiceSetup();await w.get('textarea').setValue('本次回答');await w.get('[aria-label="自评基本会"]').trigger('click');await flushPromises();expect((w.get('textarea').element as HTMLTextAreaElement).value).toBe('本次回答');expect(w.text()).toContain('仍可保存');
    expect(fetch.mock.calls.some(([p])=>String(p).endsWith('/saved-answers'))).toBe(false);
    await button(w,'保存本次回答').trigger('click');await flushPromises();const call=fetch.mock.calls.find(([p])=>String(p).endsWith('/saved-answers'))!;
    expect(JSON.parse(String(call[1]?.body))).toEqual({content:'本次回答',self_rating:null,source_session_item_id:51,source_practice_review_id:90});expect(w.text()).toContain('已保存');
    await button(w,'完成练习').trigger('click');await flushPromises();expect(w.find('textarea').exists()).toBe(false);
  });
  it('can discard after mastery without creating an answer',async()=>{
    const {w,fetch}=await practiceSetup();await w.get('textarea').setValue('不保存');await w.get('[aria-label="自评基本会"]').trigger('click');await flushPromises();await button(w,'不保存，结束练习').trigger('click');await flushPromises();expect(fetch.mock.calls.some(([p])=>String(p).endsWith('/saved-answers'))).toBe(false);expect(w.find('textarea').exists()).toBe(false);
  });
  it('keeps the draft and save choice on save failure',async()=>{
    const {w}=await practiceSetup(true);await w.get('textarea').setValue('失败仍保留');await w.get('[aria-label="自评基本会"]').trigger('click');await flushPromises();await button(w,'保存本次回答').trigger('click');await flushPromises();expect(w.get('[role=alert]').text()).toContain('保存失败');expect((w.get('textarea').element as HTMLTextAreaElement).value).toBe('失败仍保留');
  });
});

it('requires explicit preferred answer selection when both merge groups have a pin',async()=>{
  HTMLDialogElement.prototype.showModal=vi.fn();
  HTMLDialogElement.prototype.close=vi.fn();
  const member=(id:number)=>({id,text:'same question',status:'active',topic_ids:[],tag_ids:[],candidate_state:null,candidate_revision:0});
  const preview={canonical_id:1,source_question_id:2,preview_token:'a'.repeat(64),canonical_question:member(1),source_question:member(2),target_members:[member(1)],source_members:[member(2)],topic_union:[],tag_union:[],available_topics:[],available_tags:[],relation:{id:3},expected_candidate_revision:null,
    pinned_answers:[{id:10,question_id:1,content:'首选 A',version_no:1},{id:11,question_id:2,content:'首选 B',version_no:1}]};
  const fetch=vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>String(input).endsWith('/history')?json({sources:[],practice_reviews:[],session_items:[]}):init?.method==='POST'?json({id:1}):json(preview));
  vi.stubGlobal('fetch',fetch);const router=createAppRouter(createMemoryHistory());await router.push('/questions/1');await router.isReady();const w=mount(QuestionMergeDialog,{props:{questionId:1,text:'same question',relationId:3,pendingCandidate:false,otherQuestion:{id:2,text:'same question',status:'active',candidate_state:null}},global:{plugins:[router]}});await flushPromises();
  expect(w.get('[aria-label="确认归并"]').attributes('disabled')).toBeDefined();await w.get('[aria-label="保留置顶回答 11"]').setValue(true);await w.get('[aria-label="确认归并"]').trigger('click');await flushPromises();
  expect(JSON.parse(String(fetch.mock.calls.find(([,init])=>init?.method==='POST')?.[1]?.body)).pinned_answer_id).toBe(11);expect(w.emitted('merged')).toBeDefined();w.unmount();
});
