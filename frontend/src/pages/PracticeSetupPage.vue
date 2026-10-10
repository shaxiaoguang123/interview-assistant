<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue';
import { RouterLink, useRouter, useRoute } from 'vue-router';
import { ApiError, request } from '../api/client';
import type { PracticeMode } from '../api/progress';
interface TaxonomyItem {id:number;name:string;is_active:boolean}
const router=useRouter(),route=useRoute();
const modes:Array<{id:PracticeMode;label:string;hint:string}>=[
  {id:'random',label:'随机练习',hint:'从有效规范题中随机选题，覆盖新的知识。'},
  {id:'topic',label:'分类练习',hint:'选择一个或多个 Topic，集中巩固同一类知识。'},
  {id:'tag',label:'知识点练习',hint:'选择 Tag，围绕特定技术词条练习。'},
  {id:'favorite',label:'收藏练习',hint:'练习你收藏的题目，归并组中的收藏也会计入。'},
  {id:'wrong',label:'错题练习',hint:'手动标记的错题，或最近一次自评为「不会」的题目。'},
  {id:'due',label:'到期复习',hint:'只练习已到期的题目，按最早到期顺序出题。'},
];
const initialMode=modes.some(m=>m.id===route.query.mode)?route.query.mode as PracticeMode:'random';
const mode=shallowRef<PracticeMode>(initialMode),topics=ref<TaxonomyItem[]>([]),tags=ref<TaxonomyItem[]>([]);
const initialTopic=Number(route.query.topic_id);
const selectedTopicIds=ref<number[]>(initialMode==='topic'&&Number.isSafeInteger(initialTopic)&&initialTopic>0?[initialTopic]:[]);
const selectedTagIds=ref<number[]>([]),limit=shallowRef(10),errorMessage=shallowRef(''),starting=shallowRef(false);
const counts=shallowRef<Partial<Record<PracticeMode,number>>>({}),available=shallowRef<number|null>(null),countLoading=shallowRef(false),countError=shallowRef('');
const modeHint=computed(()=>modes.find(m=>m.id===mode.value)?.hint);
const filters=computed(()=>mode.value==='topic'?{topic_ids:selectedTopicIds.value}:mode.value==='tag'?{tag_ids:selectedTagIds.value}:{});
const needsSelection=computed(()=>mode.value==='topic'&&!selectedTopicIds.value.length||mode.value==='tag'&&!selectedTagIds.value.length);
let revision=0,alive=true;
function displayError(error:unknown){return error instanceof ApiError?[error.message,...Object.values(error.fields)].join('：'):'请求失败，请稍后重试。';}
async function preview(){const id=++revision;available.value=null;countError.value='';countLoading.value=false;if(needsSelection.value)return;countLoading.value=true;try{const result=await request<{question_count:number}>('/api/v1/practice-sessions/preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode:mode.value,filters:filters.value})});if(id===revision)available.value=result.question_count;}catch(e){if(id===revision)countError.value=displayError(e);}finally{if(id===revision)countLoading.value=false;}}
async function load(){try{const [topicRows,tagRows,options]=await Promise.all([request<TaxonomyItem[]>('/api/v1/topics'),request<TaxonomyItem[]>('/api/v1/tags'),request<{counts:Partial<Record<PracticeMode,number>>}>('/api/v1/practice-options')]);if(!alive)return;topics.value=topicRows.filter(i=>i.is_active);tags.value=tagRows.filter(i=>i.is_active);counts.value=options.counts??{};}catch(e){if(alive)errorMessage.value=displayError(e);}}
async function startPractice(){if(starting.value||needsSelection.value||countLoading.value||available.value===0||countError.value)return;errorMessage.value='';starting.value=true;try{const session=await request<{id:number}>('/api/v1/practice-sessions',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode:mode.value,filters:filters.value,limit:Number(limit.value)})});if(alive)await router.push({name:'practice-session',params:{id:session.id}});}catch(e){if(alive)errorMessage.value=displayError(e);}finally{if(alive)starting.value=false;}}
watch([mode,selectedTopicIds,selectedTagIds],()=>void preview(),{immediate:true,deep:true});onMounted(load);onBeforeUnmount(()=>{alive=false;revision++;});
</script>
<template>
  <section aria-labelledby="practice-setup-title" class="practice-setup"><header class="page-heading"><div><span class="eyebrow">专注练习</span><h2 id="practice-setup-title">选择今天的练习</h2><p>组织自己的答案，再用四级掌握度安排下次复习。</p></div><RouterLink to="/progress">查看学习进度</RouterLink></header>
    <p v-if="errorMessage" role="alert">{{ errorMessage }}</p>
    <div class="practice-counts" aria-label="可练习题数"><button v-for="key in (['random','favorite','wrong','due'] as const)" :key="key" :class="{selected:mode===key}" :aria-pressed="mode===key" :disabled="starting" @click="mode=key"><span>{{ {random:'全部规范题',favorite:'收藏题',wrong:'错题',due:'已到期'}[key] }}</span><strong>{{ counts[key]??'—' }}</strong></button></div>
    <form class="panel practice-settings" aria-label="练习设置" @submit.prevent="startPractice"><div class="practice-settings-heading"><h3>练习条件</h3><span class="badge">规范题去重</span></div>
      <label>练习模式<select v-model="mode" aria-label="练习模式" :disabled="starting"><option v-for="item in modes" :key="item.id" :value="item.id">{{ item.label }}{{ counts[item.id]!==undefined?` · ${counts[item.id]} 道`:'' }}</option></select></label><p class="helper">{{ modeHint }}</p>
      <label v-if="mode==='topic'">Topic<select v-model="selectedTopicIds" multiple aria-label="选择 Topic" :disabled="starting"><option v-for="topic in topics" :key="topic.id" :value="topic.id">{{ topic.name }}</option></select></label>
      <label v-if="mode==='tag'">Tag<select v-model="selectedTagIds" multiple aria-label="选择 Tag" :disabled="starting"><option v-for="tag in tags" :key="tag.id" :value="tag.id">{{ tag.name }}</option></select></label>
      <p v-if="needsSelection" class="helper">请选择至少一个启用的 {{ mode==='topic'?'Topic':'Tag' }}。</p><p v-else-if="countLoading" role="status">正在确认可练习题数…</p><p v-else-if="countError" role="alert">{{ countError }} <button type="button" @click="preview">重新加载可练题数</button></p><p v-else-if="available!==null" role="status" class="practice-available">{{ mode==='due'?`当前有 ${available} 道题需要复习`:`当前有 ${available} 道可练习题目` }}<span v-if="available===0">。{{ mode==='due'?'当前没有到期题，可选择随机或分类练习。':'请换一种模式或先在题库中添加、标记题目。' }}</span></p>
      <label>题目数量<input v-model.number="limit" type="number" min="1" max="100" aria-label="题目数量" :disabled="starting"/></label><p v-if="available!==null&&available>0" class="helper">本次最多选择 {{ Math.min(limit,available) }} 道题；题目顺序在会话创建后固定。</p>
      <button class="primary" type="submit" :disabled="starting||needsSelection||countLoading||available===0||!!countError">{{ starting?'正在创建…':mode==='due'?'开始到期复习':'开始练习' }}</button>
    </form><p class="helper">不会 1 天 · 模糊 2 天 · 基本会 7 天 · 熟练 14 天。保存回答与答案质量评分不会改变复习安排。</p>
  </section>
</template>
<style scoped>
.practice-counts{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin:24px 0;}.practice-counts button{display:flex;flex-direction:column;align-items:flex-start;gap:10px;padding:18px 20px;}.practice-counts span{font-size:13px;color:var(--muted);}.practice-counts strong{font-size:28px;line-height:1;}.practice-counts button.selected{border-color:var(--brand);background:var(--brand-soft);}.practice-settings{max-width:760px;}.practice-settings-heading{display:flex;align-items:center;justify-content:space-between;gap:16px;}.practice-settings-heading h3{margin:0;}.practice-available{padding:12px 16px;border-radius:8px;background:var(--brand-soft);}.practice-settings .primary{margin-top:16px;}
@media(max-width:600px){.practice-counts{grid-template-columns:1fr 1fr;gap:12px;}.practice-counts button{padding:16px;}}
</style>
