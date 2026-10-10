import { mount,flushPromises } from '@vue/test-utils';
import { describe,it,expect,vi,afterEach } from 'vitest';
import ProjectForm from '../src/components/materials/ProjectForm.vue';
import MaterialDetails from '../src/components/materials/MaterialDetails.vue';
import AssistantPanel from '../src/components/assistant/AssistantPanel.vue';
import SettingsPage from '../src/pages/SettingsPage.vue';
import MaterialPreview from '../src/components/materials/MaterialPreview.vue';
import type { Material } from '../src/api/materials';
const response=(data:unknown,status=200)=>({ok:status<400,status,json:async()=>data}) as Response;
const stub={RouterLink:{template:'<a><slot /></a>'}};
const material:Material={id:1,title:'Synthetic Resume',kind:'resume',project_id:null,original_filename:'resume.md',is_active:true,include_in_context:true,is_system_managed:false,archived_at:null,created_at:'2026-10-10T08:00:00Z',updated_at:'2026-10-10T08:00:00Z',version_count:2,current_version:{id:2,material_id:1,version_no:2,original_filename:'resume.md',sha256:'a'.repeat(64),byte_size:100,created_at:'2026-10-10T08:00:00Z',parsed_at:'2026-10-10T08:00:00Z',parse_status:'ready',download_url:'/api/v1/material-versions/2/file'}};
afterEach(()=>vi.unstubAllGlobals());

describe('Phase 4 projects evidence and assistant',()=>{
  it('submits one project facts form with separate private notes',async()=>{
    const wrapper=mount(ProjectForm,{global:{stubs:stub}});
    await wrapper.get('input[aria-label="项目名称"]').setValue('Agent 项目');await wrapper.get('textarea[aria-label="个人职责"]').setValue('我负责状态恢复');await wrapper.get('textarea[aria-label="管理备注"]').setValue('仅供管理');await wrapper.get('form').trigger('submit');
    expect(wrapper.emitted('save')?.[0][0]).toMatchObject({name:'Agent 项目',personal_role:'我负责状态恢复',notes:'仅供管理'});
    expect(wrapper.text()).toContain('备注和有效状态变化不会产生事实版本');wrapper.unmount();
  });
  it('updates context opt-out and retains version preview',async()=>{
    let sent:unknown;vi.stubGlobal('fetch',vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{if(init?.method==='PATCH'){sent=JSON.parse(String(init.body));return response({...material,include_in_context:false});}return response(String(input).endsWith('/versions')?[material.current_version]:{...material.current_version,text:'提取的文字'});}));
    const wrapper=mount(MaterialDetails,{props:{material,projects:[]},global:{stubs:stub}});await flushPromises();
    const box=wrapper.findAll('input[type="checkbox"]').find(x=>x.element.parentElement?.textContent?.includes('允许加入 AI 上下文'))!;
    await box.setValue(false);await wrapper.get('form[aria-label="资料设置"]').trigger('submit');await flushPromises();expect(sent).toMatchObject({include_in_context:false});expect(wrapper.emitted('changed')?.[0][0]).toMatchObject({include_in_context:false});expect(wrapper.text()).toContain('提取的文字');wrapper.unmount();
  });
  it('shows old material text when switching versions',async()=>{
    vi.stubGlobal('fetch',vi.fn(async(input:RequestInfo|URL)=>{const url=String(input);return response(url.endsWith('/versions')?[material.current_version,{...material.current_version,id:1,version_no:1}]:{...material.current_version,id:url.endsWith('/1')?1:2,text:url.endsWith('/1')?'旧版事实':'新版事实'});}));
    const wrapper=mount(MaterialPreview,{props:{material},global:{stubs:stub}});await flushPromises();expect(wrapper.text()).toContain('新版事实');await wrapper.get('select[aria-label="资料版本"]').setValue('1');await flushPromises();expect(wrapper.get('pre').text()).toBe('旧版事实');wrapper.unmount();
  });
  it('previews real context identities before generating and saves only on an explicit click',async()=>{
    const calls:Array<{url:string;body?:any}>=[];
    const sources=[{label:'S1',material_id:1,material_version_id:2,project_id:1,title:'事实 Profile',version_no:2,sha256:'a'.repeat(64),chunks:[{chunk_id:4,page_number:null,text:'用户实际负责恢复机制',retrieval_method:'fts'}]}];
    vi.stubGlobal('fetch',vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{const url=String(input),body=init?.body?JSON.parse(String(init.body)):undefined;calls.push({url,body});return response(url==='/api/v1/projects'?[{id:1,name:'Agent Project',is_active:true,archived_at:null}]:url.startsWith('/api/v1/materials?')?[{...material,project_id:1}]:url==='/api/v1/llm/config'?{configured:true,model:'fake',base_url:'http://local.test/v1',has_api_key:true}:url.endsWith('context-preview')?{context_token:'preview-token',sources,no_personal_materials:false}:url.endsWith('/reference-answer')?{preview_id:'one',question_id:1,operation:'reference_answer',content:'参考答案 [S1]',sources,model:'fake'}:url.endsWith('/save')?{output:{id:1},answer:{id:5},version:{origin_kind:'ai_assisted'}}:{});}));
    const wrapper=mount(AssistantPanel,{props:{questionId:1},global:{stubs:stub}});await wrapper.get('details').trigger('toggle'); // jsdom does not auto-open details on summary clicks.
    (wrapper.get('details').element as HTMLDetailsElement).open=true;await wrapper.get('details').trigger('toggle');await flushPromises();
    const project=wrapper.findAll('input[type="checkbox"]').find(x=>x.element.parentElement?.textContent?.includes('Agent Project'))!;await project.setValue(true);
    await wrapper.findAll('button').find(b=>b.text()==='预览本次发送内容')!.trigger('click');await flushPromises();
    expect(wrapper.text()).toContain('用户实际负责恢复机制');expect(calls.filter(c=>c.url.endsWith('/reference-answer'))).toHaveLength(0);
    await wrapper.findAll('button').find(b=>b.text()==='确认发送并生成')!.trigger('click');await flushPromises();expect(wrapper.text()).toContain('参考答案 [S1]');expect(calls.filter(c=>c.url.endsWith('/save'))).toHaveLength(0);
    await wrapper.get('textarea[aria-label="AI 结果编辑正文"]').setValue('我整理后的表达');await wrapper.findAll('button').find(b=>b.text()==='保存为新回答')!.trigger('click');await flushPromises();
    expect(calls.find(c=>c.url.endsWith('/save'))?.body).toEqual({save_kind:'new_answer',content:'我整理后的表达'});expect(wrapper.emitted('saved')).toHaveLength(1);wrapper.unmount();
  });
  it('retains source answer and exposes reload after a stale context error',async()=>{
    vi.stubGlobal('fetch',vi.fn(async(input:RequestInfo|URL)=>{const url=String(input);return response(url.endsWith('/polish')?{error:{code:'ASSISTANT_CONTEXT_STALE',message:'请重新预览'}}:url.endsWith('context-preview')?{context_token:'token',sources:[],no_personal_materials:true}:url.endsWith('/config')?{configured:true,model:'fake'}:[],url.endsWith('/polish')?409:200);}));
    const wrapper=mount(AssistantPanel,{props:{questionId:1,draft:'用户原始草稿'},global:{stubs:stub}});(wrapper.get('details').element as HTMLDetailsElement).open=true;await wrapper.get('details').trigger('toggle');await flushPromises();await wrapper.findAll('button').find(b=>b.text()==='预览本次发送内容')!.trigger('click');await flushPromises();await wrapper.findAll('button').find(b=>b.text()==='确认发送并生成')!.trigger('click');await flushPromises();expect(wrapper.get('[role="alert"]').text()).toContain('请重新预览');expect(wrapper.find('[aria-label="本次发送内容"]').exists()).toBe(false);expect(wrapper.emitted('apply')).toBeUndefined();wrapper.unmount();
  });
  it('never renders a stored key and clears newly applied input',async()=>{
    let sent:any;vi.stubGlobal('fetch',vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{if(init?.method==='PATCH')sent=JSON.parse(String(init.body));return response({base_url:'http://local.test/v1',model:'fake',has_api_key:true,configured:true});}));
    const wrapper=mount(SettingsPage);await flushPromises();expect((wrapper.get('input[aria-label="LLM API Key"]').element as HTMLInputElement).value).toBe('');await wrapper.get('input[aria-label="LLM API Key"]').setValue('temporary-test-secret');await wrapper.get('form').trigger('submit');await flushPromises();expect(sent.api_key).toBe('temporary-test-secret');expect((wrapper.get('input[aria-label="LLM API Key"]').element as HTMLInputElement).value).toBe('');expect(wrapper.text()).not.toContain('temporary-test-secret');wrapper.unmount();
  });
});

it('retains AI provenance and real practice source when explicitly saving after mastery',async()=>{
  const { createMemoryHistory,createRouter }=await import('vue-router');
  const { defineComponent,h }=await import('vue');
  const SessionPage=(await import('../src/pages/PracticeSessionPage.vue')).default;
  const router=createRouter({history:createMemoryHistory(),routes:[{path:'/practice/sessions/:id',component:SessionPage}]});
  await router.push('/practice/sessions/1');await router.isReady();let savedBody:any;
  vi.stubGlobal('fetch',vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
    const url=String(input);
    if(url.endsWith('/review'))return response({id:10,review_schedule:{next_review_at:'2026-10-17T08:00:00Z'}});
    if(url.endsWith('/save')){savedBody=JSON.parse(String(init?.body));return response({answer:{id:22}});}
    return response({id:1,completed_at:null,items:[{id:5,question_id:1,ordinal:1,status:'shown',question:{id:1,text:'MCP'}}]});
  }));
  const fakePanel=defineComponent({emits:['apply'],setup(_,ctx){return()=>h('button',{onClick:()=>ctx.emit('apply',{content:'润色后的临时回答',previewId:'ai-preview'})},'应用 AI 测试结果');}});
  const wrapper=mount(SessionPage,{global:{plugins:[router],stubs:{AssistantPanel:fakePanel}}});await flushPromises();
  await wrapper.findAll('button').find(b=>b.text()==='应用 AI 测试结果')!.trigger('click');
  expect(wrapper.get('textarea').element.value).toBe('润色后的临时回答');
  await wrapper.findAll('button').find(b=>b.text()==='基本会')!.trigger('click');await flushPromises();
  await wrapper.findAll('button').find(b=>b.text()==='保存本次回答')!.trigger('click');await flushPromises();
  expect(savedBody).toEqual({save_kind:'new_answer',content:'润色后的临时回答',self_rating:null,source_session_item_id:5,source_practice_review_id:10});
  expect(wrapper.text()).toContain('AI 辅助回答已保存，并保留本次练习来源');
  expect(wrapper.text()).not.toContain('AI 辅助结果已应用到临时回答，尚未保存');wrapper.unmount();
});
