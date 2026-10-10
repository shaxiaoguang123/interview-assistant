import { flushPromises, mount } from '@vue/test-utils';
import { createMemoryHistory, createRouter } from 'vue-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import SetupPage from '../src/pages/PracticeSetupPage.vue';
import ProgressPage from '../src/pages/ProgressPage.vue';
import SessionPage from '../src/pages/PracticeSessionPage.vue';
import ReviewStatus from '../src/components/review/ReviewStatus.vue';

const response=(data:unknown)=>({ok:true,status:200,json:async()=>data}) as Response;
async function page(component:object,path:string){const router=createRouter({history:createMemoryHistory(),routes:[{path:'/practice',name:'practice-setup',component:SetupPage},{path:'/progress',component:ProgressPage},{path:'/practice/sessions/:id',name:'practice-session',component:SessionPage}]});await router.push(path);await router.isReady();const wrapper=mount(component,{global:{plugins:[router]}});await flushPromises();return {wrapper,router};}
afterEach(()=>vi.unstubAllGlobals());
const progress={as_of:'2026-10-10T08:00:00Z',window_days:30,active_question_count:3,reviewed_question_count:2,practice_review_count:4,mastery_counts:{dont_know:2,vague:1,basic:1,proficient:0},due_question_count:1,future_question_count:1,favorite_question_count:1,wrong_question_count:1,saved_answer_count:2,rated_answer_count:1,answer_quality_counts:{'1':0,'2':0,'3':0,'4':0,'5':1},due_questions:[{id:1,text:'Due canonical question',next_review_at:'2026-10-09T08:00:00Z'}],due_list_limit:20,topics:[{id:1,name:'RAG',question_count:2,reviewed_question_count:1,review_count:3,mastery_counts:{dont_know:1,vague:1,basic:1,proficient:0},has_enough_records:true,weak_ratio:2/3},{id:2,name:'Memory',question_count:1,reviewed_question_count:1,review_count:1,mastery_counts:{dont_know:1,vague:0,basic:0,proficient:0},has_enough_records:false,weak_ratio:null}]};

describe('Phase 3 practice and progress',()=>{
  it('offers all six modes and prevents creating an empty due session',async()=>{
    const calls:string[]=[];vi.stubGlobal('fetch',vi.fn(async(input:RequestInfo|URL)=>{const url=String(input);calls.push(url);return response(url==='/api/v1/practice-options'?{counts:{random:3,favorite:1,wrong:1,due:0}}:url.endsWith('/preview')?{question_count:0}:[]);}));
    const {wrapper}=await page(SetupPage,'/practice?mode=due');
    expect(wrapper.get('select[aria-label="练习模式"]').findAll('option')).toHaveLength(6);
    expect(wrapper.text()).toContain('当前有 0 道题需要复习');
    expect(wrapper.get('button[type="submit"]').attributes('disabled')).toBeDefined();
    await wrapper.get('form').trigger('submit');await flushPromises();
    expect(calls.filter(c=>c==='/api/v1/practice-sessions')).toHaveLength(0);wrapper.unmount();
  });
  it('previews selected Topics and creates the correct new mode',async()=>{
    let body:unknown;vi.stubGlobal('fetch',vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{const url=String(input);if(url==='/api/v1/practice-sessions'){body=JSON.parse(String(init?.body));return response({id:9});}return response(url==='/api/v1/topics'?[{id:1,name:'RAG',is_active:true}]:url.endsWith('/preview')?{question_count:2}:url==='/api/v1/practice-options'?{counts:{random:3,favorite:2,wrong:1,due:1}}:[]);}));
    const {wrapper,router}=await page(SetupPage,'/practice?mode=topic&topic_id=1');
    expect(wrapper.text()).toContain('当前有 2 道可练习题目');
    await wrapper.get('select[aria-label="练习模式"]').setValue('favorite');await flushPromises();
    await wrapper.get('form').trigger('submit');await flushPromises();
    expect(body).toEqual({mode:'favorite',filters:{},limit:10});expect(router.currentRoute.value.path).toBe('/practice/sessions/9');wrapper.unmount();
  });
  it('shows separate quality/mastery counts, sparse Topics and window controls',async()=>{
    const urls:string[]=[];vi.stubGlobal('fetch',vi.fn(async(input:RequestInfo|URL)=>{urls.push(String(input));return response(progress);}));
    const {wrapper}=await page(ProgressPage,'/progress');
    expect(wrapper.text()).toContain('不会或模糊 67%');expect(wrapper.text()).toContain('练习记录不足 · 1 次');
    expect(wrapper.get('section[aria-label="保存回答统计"]').text()).toContain('质量评分独立于掌握度');
    expect(wrapper.get('a[href="/questions/1"]').text()).toBe('Due canonical question');
    expect(wrapper.get('a[href="/practice?mode=topic&topic_id=1"]').text()).toBe('练习此 Topic');
    await wrapper.get('select[aria-label="弱项统计窗口"]').setValue('7');await flushPromises();expect(urls).toContain('/api/v1/progress?window_days=7');wrapper.unmount();
  });
  it('recovers from a progress loading error',async()=>{
    const fetch=vi.fn().mockResolvedValueOnce({ok:false,status:500,json:async()=>({error:{code:'ERROR',message:'加载失败'}})}).mockResolvedValue(response({...progress,practice_review_count:0,due_question_count:0,due_questions:[],topics:[]}));vi.stubGlobal('fetch',fetch);
    const {wrapper}=await page(ProgressPage,'/progress');expect(wrapper.get('[role="alert"]').text()).toContain('加载失败');await wrapper.get('button').trigger('click');await flushPromises();expect(wrapper.text()).toContain('当前到期队列已清空');expect(wrapper.find('[role="alert"]').exists()).toBe(false);wrapper.unmount();
  });
  it('retains the answer and displays scheduling after the final review',async()=>{
    vi.stubGlobal('fetch',vi.fn(async(input:RequestInfo|URL)=>response(String(input).endsWith('/review')?{id:9,review_schedule:{next_review_at:'2026-10-11T08:00:00Z'}}:{id:1,completed_at:null,items:[{id:5,question_id:1,ordinal:1,status:'shown',question:{id:1,text:'Explain MCP'}}]})));
    const {wrapper}=await page(SessionPage,'/practice/sessions/1');await wrapper.get('textarea').setValue('Keep my answer');await wrapper.findAll('button').find(b=>b.text()==='不会')!.trigger('click');await flushPromises();
    expect(wrapper.get('textarea').element.value).toBe('Keep my answer');expect(wrapper.text()).toContain('下次复习：');expect(wrapper.text()).toContain('2026年10月11日');expect(wrapper.text()).toContain('本次练习已完成，仍可保存');wrapper.unmount();
  });
  it('changes a review summary when corrected while keeping the original review time',async()=>{
    const wrapper=mount(ReviewStatus,{props:{schedule:{last_reviewed_at:'2026-10-10T08:00:00Z',last_review_rating:'basic',next_review_at:'2026-10-17T08:00:00Z',is_due:false}},global:{stubs:{RouterLink:true}}});expect(wrapper.text()).toContain('基本会');expect(wrapper.text()).toContain('2026年10月17日');await wrapper.setProps({schedule:{last_reviewed_at:'2026-10-10T08:00:00Z',last_review_rating:'vague',next_review_at:'2026-10-12T08:00:00Z',is_due:false}});expect(wrapper.text()).toContain('模糊');expect(wrapper.text()).toContain('2026年10月12日');expect(wrapper.text()).toContain('2026年10月10日');wrapper.unmount();
  });
});

it('ignores an older eligibility response after switching modes',async()=>{
  let resolveDue!:(value:Response)=>void;
  const due=new Promise<Response>(resolve=>{resolveDue=resolve;});
  vi.stubGlobal('fetch',vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
    const url=String(input);
    if(url.endsWith('/preview'))return JSON.parse(String(init?.body)).mode==='due'?due:response({question_count:3});
    return response(url==='/api/v1/practice-options'?{counts:{random:3,favorite:1,wrong:1,due:0}}:[]);
  }));
  const {wrapper}=await page(SetupPage,'/practice?mode=due');
  await wrapper.get('select[aria-label="练习模式"]').setValue('random');await flushPromises();
  expect(wrapper.text()).toContain('当前有 3 道可练习题目');
  resolveDue(response({question_count:0}));await flushPromises();
  expect(wrapper.text()).toContain('当前有 3 道可练习题目');
  expect(wrapper.get('button[type="submit"]').attributes('disabled')).toBeUndefined();wrapper.unmount();
});
