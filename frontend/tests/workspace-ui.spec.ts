import { flushPromises, mount } from "@vue/test-utils";
import { createMemoryHistory } from "vue-router";
import { describe, expect, it, vi } from "vitest";
import App from "../src/App.vue";
import QuestionBankPage from "../src/pages/QuestionBankPage.vue";
import PracticeSessionPage from "../src/pages/PracticeSessionPage.vue";
import IngestionCandidateEditor from "../src/components/IngestionCandidateEditor.vue";
import SourceImageViewer from "../src/components/SourceImageViewer.vue";
import TaxonomyPage from "../src/pages/TaxonomyPage.vue";
import { createAppRouter } from "../src/router";

const json=(body:unknown,status=200)=>({ok:status<400,status,json:async()=>body}) as Response;
function deferred<T>(){let resolve!:(value:T)=>void;const promise=new Promise<T>(r=>resolve=r);return {promise,resolve};}
const q=(id:number,text:string)=>({id,text,topics:[],tags:[],state:{is_favorite:false,is_wrong:false},archived_at:null});
const session=(id:number)=>({id,mode:'random',items:[{id:id*10,question_id:id,ordinal:1,status:'shown',question:{id,text:`Session question ${id}`,status:'active',archived_at:null}}],completed_at:null});

describe('professional workspace behaviors',()=>{
  it('has eight semantic navigation links, selected state, local health and a skip link',async()=>{
    vi.stubGlobal('fetch',vi.fn(async(input:RequestInfo|URL)=>json(String(input).endsWith('/health')?{status:'ok'}:[])));
    const router=createAppRouter(createMemoryHistory());await router.push('/');await router.isReady();
    const wrapper=mount(App,{global:{plugins:[router]}});await flushPromises();
    expect(wrapper.text()).toContain('Agent Interview Workspace');
    expect(wrapper.find('a[href="#workspace-content"]').exists()).toBe(true);
    const nav=wrapper.get('nav[aria-label="主导航"]');expect(nav.findAll('a')).toHaveLength(8);
    expect(nav.get('a[href="/"]').attributes('aria-current')).toBe('page');
    expect(nav.findAll('svg[aria-hidden="true"]')).toHaveLength(8);
    await nav.get('a[href="/practice"]').trigger('click');await flushPromises();
    expect(nav.get('a[href="/practice"]').attributes('aria-current')).toBe('page');
    expect(wrapper.text()).toContain('后端已连接');
  });
  it('provides an honest result count and retries a failed bank load',async()=>{
    let fail=true;
    vi.stubGlobal('fetch',vi.fn(async(input:RequestInfo|URL)=>String(input)==='/api/v1/questions'?(fail?json({error:{message:'bank unavailable'}},503):json([q(1,'Recovered question')])):json([])));
    const router=createAppRouter(createMemoryHistory());await router.push('/');await router.isReady();
    const wrapper=mount(QuestionBankPage,{global:{plugins:[router]}});await flushPromises();
    expect(wrapper.text()).not.toContain('当前没有题目');
    fail=false;await wrapper.get('[aria-label="重试加载题库"]').trigger('click');await flushPromises();
    expect(wrapper.get('[aria-label="题库结果数量"]').text()).toContain('1 道题目');
  });
  it('keeps newer search results and ignores an older request',async()=>{
    const old=deferred<Response>();
    vi.stubGlobal('fetch',vi.fn(async(input:RequestInfo|URL)=>{
      const path=String(input);if(path.includes('?q=old'))return old.promise;
      if(path.includes('?q=new'))return json([q(2,'NEW RESULT')]);return json([]);
    }));
    const router=createAppRouter(createMemoryHistory());await router.push('/');await router.isReady();
    const wrapper=mount(QuestionBankPage,{global:{plugins:[router]}});await flushPromises();
    await wrapper.get('[aria-label="搜索题目"]').setValue('old');await wrapper.get('form[role="search"]').trigger('submit');
    await wrapper.get('[aria-label="搜索题目"]').setValue('new');await wrapper.get('form[role="search"]').trigger('submit');await flushPromises();
    old.resolve(json([q(1,'OLD RESULT')]));await flushPromises();
    expect(wrapper.text()).toContain('NEW RESULT');expect(wrapper.text()).not.toContain('OLD RESULT');
  });
  it('shows actual practice progress and reloads after Session route changes',async()=>{
    const old=deferred<Response>();
    vi.stubGlobal('fetch',vi.fn(async(input:RequestInfo|URL)=>String(input).endsWith('/1')?old.promise:json(session(2))));
    const router=createAppRouter(createMemoryHistory());await router.push('/practice/sessions/1');await router.isReady();
    const wrapper=mount(PracticeSessionPage,{global:{plugins:[router]}});await router.push('/practice/sessions/2');await flushPromises();
    old.resolve(json(session(1)));await flushPromises();
    expect(wrapper.text()).toContain('Session question 2');expect(wrapper.text()).not.toContain('Session question 1');
    expect(wrapper.get('progress[aria-label="练习完成进度"]').attributes('max')).toBe('1');
  });
  it('explains the disabled OCR confirm action without hiding alternative actions',()=>{
    const wrapper=mount(IngestionCandidateEditor,{props:{candidate:{id:1,text:'Synthetic',status:'pending_review',candidate_state:'pending_review',candidate_revision:0,topics:[],tags:[],sources:[]},confirmationBlocked:true}});
    expect(wrapper.get('[aria-label="确认受限原因"]').text()).toContain('相似题');
    expect(wrapper.get('[aria-label="确认进入题库"]').attributes('disabled')).toBeDefined();
    expect(wrapper.get('[aria-label="拒绝候选题"]').attributes('disabled')).toBeUndefined();
  });
  it('uses image aspect ratio while retaining explicit contain containers',()=>{
    const wrapper=mount(SourceImageViewer,{props:{sources:[],selectedSourceId:null,imageWidth:1100,imageHeight:700}});
    expect(wrapper.get('.image-stage').attributes('style')).toContain('aspect-ratio: 1100 / 700');
    expect(wrapper.get('.image-stage').attributes('style')).toContain('height: auto');
    const explicit=mount(SourceImageViewer,{props:{sources:[],selectedSourceId:null,imageWidth:1100,imageHeight:700,containerWidth:400,containerHeight:200}});
    expect(explicit.get('.image-stage').attributes('style')).toContain('height: 200px');
  });
  it('organizes topics by parent and exposes focused edit disclosures',async()=>{
    vi.stubGlobal('fetch',vi.fn(async(input:RequestInfo|URL)=>json(String(input).endsWith('/topics')?[
      {id:2,parent_id:1,slug:'child',name:'Child topic',sort_order:0,is_active:true},
      {id:1,parent_id:null,slug:'parent',name:'Parent topic',sort_order:0,is_active:true},
    ]:[])));
    const wrapper=mount(TaxonomyPage);await flushPromises();
    const rows=wrapper.findAll('.taxonomy-list li');
    expect(rows[0].get('input').attributes('aria-label')).toBe('Topic 名称 parent');expect(rows[1].get('input').attributes('aria-label')).toBe('Topic 名称 child');
    expect(wrapper.findAll('details.taxonomy-editor')).toHaveLength(2);
  });
  it('does not offer a doomed archive from the bank for a canonical group',async()=>{
    vi.stubGlobal('fetch',vi.fn(async(input:RequestInfo|URL)=>json(String(input)==='/api/v1/questions'?[{...q(1,'Canonical group'),canonical_member_count:3}]:[])));
    const router=createAppRouter(createMemoryHistory());await router.push('/');await router.isReady();
    const wrapper=mount(QuestionBankPage,{global:{plugins:[router]}});await flushPromises();
    expect(wrapper.get('[aria-label="归档题目 1"]').attributes('disabled')).toBeDefined();
    expect(wrapper.text()).toContain('归并组暂不支持整组归档');
  });
  it('retries taxonomy too after the initial bank metadata request fails',async()=>{
    let topicsCalls=0;
    vi.stubGlobal('fetch',vi.fn(async(input:RequestInfo|URL)=>{
      if(String(input)==='/api/v1/topics')return ++topicsCalls===1?json({error:{message:'topics unavailable'}},503):json([{id:8,name:'Recovered MCP',is_active:true}]);
      return json([]);
    }));
    const router=createAppRouter(createMemoryHistory());await router.push('/');await router.isReady();
    const wrapper=mount(QuestionBankPage,{global:{plugins:[router]}});await flushPromises();
    await wrapper.get('[aria-label="重试加载题库"]').trigger('click');await flushPromises();
    expect(wrapper.get('[aria-label="按 Topic 筛选"]').text()).toContain('Recovered MCP');
    expect(topicsCalls).toBe(2);
  });
});
