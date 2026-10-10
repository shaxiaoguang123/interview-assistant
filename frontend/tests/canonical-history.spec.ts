import { flushPromises, mount } from "@vue/test-utils";
import { createMemoryHistory } from "vue-router";
import { describe, expect, it, vi } from "vitest";
import QuestionDetailPage from "../src/pages/QuestionDetailPage.vue";
import { createAppRouter } from "../src/router";
import { emptySimilarityResponse } from "./fixtures/similarity";

const json = (body: unknown, status = 200) => ({ok:status<400,status,json:async()=>body}) as Response;
const question = (id: number, child = false) => ({
  id,text:`Question ${id}`,status:child?"merged":"active",canonical_question_id:child?1:id,
  archived_at:null,answer_type:null,difficulty:null,topics:[],tags:[],
  state:{is_favorite:true,is_wrong:true,user_note:null},
});
const review = {id:91,question_id:2,session_item_id:81,review_rating:"basic",reviewed_at:"2026-10-10T00:00:00Z",created_at:"2026-10-10T00:00:00Z",updated_at:"2026-10-10T00:00:00Z"};
const source = {
  question_source_id:71,question_id:2,source_asset_id:7,source_title:"历史子题来源",
  display_width:100,display_height:80,source_text_snapshot:"original child evidence",raw_ocr_text_snapshot:"original OCR",
  locator_json:{x:.1,y:.2,width:.5,height:.1},locator_correction_json:null,ocr_block_ids:["stable-uuid"],
  ocr_blocks:[{id:"stable-uuid",text:"original OCR",bbox:{x:.1,y:.2,width:.5,height:.1},reading_order:0,confidence:.9}],
  original_image_url:"/api/v1/sources/7/original",display_image_url:"/api/v1/sources/7/display",
};
const history = (id=1) => ({canonical_question_id:id,member_question_ids:[id,2],sources:[source],practice_reviews:[review],session_items:[{id:81,question_id:2,session_id:8,ordinal:1,status:"completed"}]});
function deferred<T>() {let resolve!:(value:T)=>void;const promise=new Promise<T>(r=>resolve=r);return {promise,resolve};}
async function setup(override:(path:string,init?:RequestInit)=>Response|Promise<Response>|undefined=()=>undefined,id=1,historical=false,query=""){
  const fetchMock=vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
    const path=String(input);const custom=override(path,init);if(custom)return custom;
    const sim=emptySimilarityResponse(path);if(sim)return sim;
    if(path==='/api/v1/topics'||path==='/api/v1/tags')return json([]);
    const detail=path.match(/^\/api\/v1\/questions\/(\d+)$/);if(detail)return json(question(Number(detail[1])));
    const h=path.match(/^\/api\/v1\/questions\/(\d+)\/history$/);if(h)return json(history(Number(h[1])));
    if(/\/(sources|practice-reviews)$/.test(path))return json([]);
    throw Error(path);
  });
  vi.stubGlobal('fetch',fetchMock);
  const router=createAppRouter(createMemoryHistory());await router.push(`/questions/${id}${query ? `?${query}` : historical ? "?history=1" : ""}`);await router.isReady();
  const wrapper=mount(QuestionDetailPage,{global:{plugins:[router]}});await flushPromises();
  return {wrapper,router,fetchMock};
}

describe('canonical detail history',()=>{
  it('loads history once and preserves source/review original IDs without exact calls',async()=>{
    const {wrapper,fetchMock}=await setup();
    expect(fetchMock.mock.calls.filter(([p])=>String(p).endsWith('/history'))).toHaveLength(1);
    expect(fetchMock.mock.calls.some(([p])=>/\/(sources|practice-reviews)$/.test(String(p)))).toBe(false);
    expect(wrapper.text()).toContain('原题 #2');
    expect(wrapper.get('[data-source-region-id="71"]').attributes('x')).toBe('10');
    expect(wrapper.get('[data-review-id="91"]').text()).toContain('原题 #2');
    expect(wrapper.get('[aria-label="归并组练习会话历史"]').text()).toContain('原题 #2');
  });
  it('corrects a child review with its own ID and retains original question ID',async()=>{
    const {wrapper,fetchMock}=await setup((path,init)=>path==='/api/v1/practice-reviews/91'&&init?.method==='PATCH'?json({...review,review_rating:'proficient'}):undefined);
    await wrapper.get('[aria-label="更正掌握度 91"]').setValue('proficient');
    await wrapper.get('[aria-label="保存自评 91"]').trigger('click');await flushPromises();
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/practice-reviews/91',expect.objectContaining({method:'PATCH',body:JSON.stringify({review_rating:'proficient'})}));
    expect(wrapper.get('[data-review-id="91"]').text()).toContain('熟练');
    expect(wrapper.get('[data-review-id="91"]').text()).toContain('原题 #2');
  });
  it('shows explicit group scope and disables each flag through root state API',async()=>{
    const {wrapper,fetchMock}=await setup((path,init)=>path==='/api/v1/questions/1/state'?json({...question(1).state,...JSON.parse(String(init?.body))}):undefined);
    expect(wrapper.text()).toContain('取消收藏和取消错题标记作用于整个归并组');
    await wrapper.get('[aria-label="取消收藏"]').trigger('click');
    await flushPromises();
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/questions/1/state',expect.objectContaining({body:JSON.stringify({is_favorite:false})}));
  });
  it('reports failed history separately and retries without pretending it is empty',async()=>{
    let count=0;
    const {wrapper}=await setup(path=>path.endsWith('/history')?++count===1?json({error:{code:'INTERNAL_ERROR',message:'history unavailable'}},500):json(history()):undefined);
    expect(wrapper.get('[aria-label="题目历史加载失败"]').text()).toContain('history unavailable');
    expect(wrapper.text()).not.toContain('暂无练习记录');
    await wrapper.get('[aria-label="重试加载题目历史"]').trigger('click');await flushPromises();
    expect(wrapper.find('[aria-label="题目历史加载失败"]').exists()).toBe(false);
    expect(wrapper.text()).toContain('原题 #2');expect(count).toBe(2);
  });
  it.each([false,true])('ignores stale history success/error after navigation (error=%s)',async(fail)=>{
    const pending=deferred<Response>();
    const {wrapper,router}=await setup(path=>path==='/api/v1/questions/1/history'?pending.promise:undefined);
    await router.push('/questions/3');await flushPromises();
    pending.resolve(fail?json({error:{message:'old error'}},500):json({...history(),sources:[{...source,source_text_snapshot:'STALE EVIDENCE'}]}));
    await flushPromises();
    expect(wrapper.text()).not.toContain('STALE EVIDENCE');expect(wrapper.text()).not.toContain('old error');
    expect(wrapper.get('textarea[aria-label="题目正文"]').element).toHaveProperty('value','Question 3');
  });
  it('rejects the first A history after A → B → A reload',async()=>{
    const first=deferred<Response>();let calls=0;
    const {wrapper,router}=await setup(path=>path==='/api/v1/questions/1/history'&&++calls===1?first.promise:undefined);
    await router.push('/questions/3');await flushPromises();await router.push('/questions/1');await flushPromises();
    first.resolve(json({...history(),sources:[{...source,source_text_snapshot:'FIRST A STALE'}]}));await flushPromises();
    expect(wrapper.text()).toContain('original child evidence');expect(wrapper.text()).not.toContain('FIRST A STALE');
  });
  it('keeps merged child content read-only with a canonical link',async()=>{
    const {wrapper}=await setup(path=>path==='/api/v1/questions/2'?json(question(2,true)):undefined,2,true);
    expect(wrapper.text()).toContain('Question 2');expect(wrapper.find('form[aria-label="题目表单"]').exists()).toBe(false);
    expect(wrapper.find('button[aria-label="取消收藏"]').exists()).toBe(false);
    expect(wrapper.find('a[href="/questions/1"]').exists()).toBe(true);
  });
  it('does not offer ordinary root archival for a canonical group with children',async()=>{
    const {wrapper}=await setup();
    const archive=wrapper.findAll('button').find(b=>b.text()==='归档');
    expect(archive?.attributes('disabled')).toBeDefined();
    expect(wrapper.text()).toContain('归并组暂不支持整组归档');
  });
  it('does not trust an unrelated from_question query parameter',async()=>{
    const {wrapper}=await setup(undefined,1,false,'from_question=999');
    expect(wrapper.text()).not.toContain('原题 #999 已归并至当前规范题');
  });
  it('shows verified child provenance and hides it when the same route query changes',async()=>{
    const {wrapper,router}=await setup(undefined,1,false,'from_question=2');
    expect(wrapper.text()).toContain('原题 #2 已归并至当前规范题');
    expect(wrapper.find('a[href="/questions/2?history=1"]').exists()).toBe(true);
    await router.push('/questions/1?from_question=999');await flushPromises();
    expect(wrapper.text()).not.toContain('原题 #999 已归并至当前规范题');
  });
  it('does not label the root itself as a merged source',async()=>{
    const {wrapper}=await setup(undefined,1,false,'from_question=1');
    expect(wrapper.text()).not.toContain('原题 #1 已归并至当前规范题');
  });
  it('waits for authoritative history before claiming a source was merged',async()=>{
    const pending=deferred<Response>();
    const {wrapper}=await setup(path=>path.endsWith('/history')?pending.promise:undefined,1,false,'from_question=2');
    expect(wrapper.text()).not.toContain('原题 #2 已归并至当前规范题');
    pending.resolve(json(history(1)));await flushPromises();
    expect(wrapper.text()).toContain('原题 #2 已归并至当前规范题');
  });
});
