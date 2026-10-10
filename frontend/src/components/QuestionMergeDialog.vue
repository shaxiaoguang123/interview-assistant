<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { ApiError, request } from '../api/client';
import { getMergePreview, mergeQuestions, type MergePreview, type MergeOutcome, type MergeMember, type MergeTaxonomy } from '../api/question-merge';
import type { CanonicalHistory } from '../api/question-history';
import { RouterLink } from 'vue-router';

const props = defineProps<{
  questionId:number; text:string; relationId:number; pendingCandidate:boolean;
  otherQuestion:{id:number; text:string; status:string; candidate_state:string|null};
}>();
const emit = defineEmits<{close:[]; merged:[outcome:MergeOutcome]}>();
const dialog = ref<HTMLDialogElement|null>(null);
const canonicalId = ref(props.pendingCandidate ? props.otherQuestion.id : props.questionId);
const sourceId = computed(() => canonicalId.value === props.questionId ? props.otherQuestion.id : props.questionId);
const canChoose = computed(() => !props.pendingCandidate && props.otherQuestion.status === 'active');
const choices = computed(() => [{id:props.questionId,text:props.text},props.otherQuestion]);
const preview = ref<MergePreview|null>(null);
const topicIds = ref<number[]>([]);
const tagIds = ref<number[]>([]);
const pinnedAnswerId = ref<number|null>(null);
const histories = ref<Record<number,CanonicalHistory>>({});
const loading = ref(false);
const submitting = ref(false);
const stale = ref(false);
const error = ref('');
const refreshed = ref(false);
let revision = 0;
let alive = true;
let previousFocus:HTMLElement|null = null;
let previousOverflow = '';
const hasInactive = computed(() => preview.value && [...preview.value.topic_union,...preview.value.tag_union].some(t=>!t.is_active));
function current(r:number) {return alive && r === revision;}
function message(e:unknown) {return e instanceof ApiError ? [e.message,...Object.values(e.fields)].join('；') : '无法读取归并预览，请重试。';}
async function loadPreview(refresh = false) {
  const r = ++revision;
  const target = canonicalId.value, source = sourceId.value;
  loading.value = true; error.value = ''; stale.value = false; preview.value = null;
  refreshed.value = false;
  try {
    const data = await getMergePreview(target,source);
    if (!current(r)) return;
    if(data.canonical_id !== target || data.source_question_id !== source || data.relation?.id !== props.relationId) throw new Error('Invalid preview');
    preview.value = data;
    pinnedAnswerId.value = null;
    topicIds.value = data.topic_union.map(t=>t.id); tagIds.value = data.tag_union.map(t=>t.id);
    refreshed.value = refresh;
    // History is supplementary; a failed read stays visible as unavailable.
    void Promise.allSettled([target,source].map(async id => {
      const h = await request<CanonicalHistory>(`/api/v1/questions/${id}/history`);
      if(current(r)) histories.value = {...histories.value,[id]:h};
    }));
  } catch(e) {if(current(r)) error.value = message(e);}
  finally {if(current(r)) loading.value = false;}
}
async function confirm() {
  const data = preview.value;
  if(!data || submitting.value || loading.value || stale.value || error.value || ((data.pinned_answers?.length??0)>1 && pinnedAnswerId.value===null)) return;
  const r = revision; submitting.value = true;
  try {
    const result = await mergeQuestions(data,[...topicIds.value],[...tagIds.value],pinnedAnswerId.value);
    if(!current(r)) return;
    if(result.id !== data.canonical_id) throw new Error('Invalid merge response');
    emit('merged',{canonicalId:data.canonical_id,sourceId:data.source_question_id});
  } catch(e) {
    if(current(r)) {
      stale.value = e instanceof ApiError && e.status === 409;
      error.value = stale.value ? '预览已过期：题目、关系或分类已更新。请重新获取预览，核对后再次确认。' : message(e);
    }
  } finally {if(current(r)) submitting.value = false;}
}
function close() {if(!submitting.value) emit('close');}
function unionFirst(items:MergeTaxonomy[], union:MergeTaxonomy[]) {
  const ids = new Set(union.map(t=>t.id));
  return [...items].sort((a,b)=>Number(ids.has(b.id))-Number(ids.has(a.id)));
}
function classifications(member:MergeMember) {
  if(!preview.value) return '';
  return [...preview.value.available_topics.filter(t=>member.topic_ids.includes(t.id)), ...preview.value.available_tags.filter(t=>member.tag_ids.includes(t.id))]
    .map(t=>`${t.name}${t.is_active?'':'（停用）'}`).join(' · ') || '未分类';
}
watch(canonicalId,()=>void loadPreview(),{immediate:true,flush:'sync'});
onMounted(()=>{
  previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  previousOverflow = document.body.style.overflow; document.body.style.overflow = 'hidden';
  dialog.value?.showModal();
});
onBeforeUnmount(()=>{
  alive=false;revision+=1;dialog.value?.close();document.body.style.overflow=previousOverflow;
  if(previousFocus?.isConnected) previousFocus.focus();
});
</script>

<template>
  <dialog ref="dialog" class="merge-dialog" aria-labelledby="merge-title" aria-describedby="merge-description" @cancel.prevent="close">
    <header class="merge-header">
      <div><span class="eyebrow">同题归并</span><h2 id="merge-title">两种表述，一道规范题</h2><p id="merge-description">已人工确认同题。核对保留的正文与分类，再完成归并。</p></div>
      <button type="button" aria-label="关闭归并对话框" :disabled="submitting" @click="close">关闭</button>
    </header>
    <div class="merge-body" :aria-busy="loading || submitting">
      <fieldset v-if="canChoose" class="canonical-choice" :disabled="submitting">
        <legend>选择要保留的规范题</legend>
        <label v-for="item in choices" :key="item.id" :class="{selected:canonicalId===item.id}">
          <input v-model="canonicalId" type="radio" :value="item.id" :aria-label="`选择规范题 ${item.id}`" />
          <span><strong>#{{ item.id }}</strong> {{ item.text }}</span>
        </label>
      </fieldset>
      <p v-else class="merge-note">OCR 候选归并至已有正式题 #{{ canonicalId }}，候选原文与截图继续保留。</p>
      <p v-if="loading" role="status">正在获取最新归并预览…</p>
      <div v-if="error" class="merge-error"><p role="alert">{{ error }}</p><button type="button" aria-label="重新获取归并预览" :disabled="loading || submitting" @click="loadPreview(true)">重新获取预览</button></div>
      <p v-if="refreshed" role="status">预览已更新，分类已恢复为当前并集。请重新核对并确认。</p>
      <template v-if="preview">
        <div class="merge-comparison" :data-canonical-id="preview.canonical_id">
          <article v-for="(member,index) in [preview.canonical_question,preview.source_question]" :key="member.id" :class="['merge-question',{canonical:index===0}]">
            <div class="record-meta"><span :class="['badge',index===0?'accent':'']">{{ index===0?'保留为规范题':'归并为历史题' }}</span><span class="mono">原始 Question #{{ member.id }}</span></div>
            <p class="merge-text">{{ member.text }}</p><p class="helper">{{ classifications(member) }}</p>
            <p v-if="histories[member.id]" class="merge-history-count">{{ (index===0?preview.target_members:preview.source_members).length }} 道原题 · {{ histories[member.id]?.sources.length }} 条来源 · {{ histories[member.id]?.practice_reviews.length }} 次自评 · {{ histories[member.id]?.session_items.length }} 条会话记录</p>
            <p v-else class="helper">历史摘要暂未读取，原始记录仍会保留。</p>
            <details v-if="(index===0?preview.target_members:preview.source_members).length>1"><summary>查看已有归并组原文</summary><p v-for="q in (index===0?preview.target_members:preview.source_members)" :key="q.id" class="helper">#{{ q.id }} · {{ q.text }}</p></details>
            <RouterLink :to="`/questions/${member.id}?history=1`" target="_blank">查看原题与来源 ↗</RouterLink>
          </article>
        </div>
        <fieldset v-if="(preview.pinned_answers?.length??0)>1" class="merge-pin-choice" :disabled="submitting || stale" aria-label="选择归并后置顶回答"><legend>选择唯一的首选回答</legend><p class="helper">双方都有置顶回答。请选择一条继续置顶，其他回答仅取消置顶，正文和版本全部保留。</p><label v-for="a in preview.pinned_answers" :key="a.id"><input v-model="pinnedAnswerId" type="radio" name="merge-pinned-answer" :value="a.id" :aria-label="`保留置顶回答 ${a.id}`" /><span><strong>回答 #{{ a.id }} · 原题 #{{ a.question_id }} · v{{ a.version_no }}</strong><span class="merge-pin-content">{{ a.content }}</span></span></label></fieldset>
        <section class="merge-taxonomy" aria-label="最终归并分类">
          <h3>规范题的最终分类</h3><p class="helper">默认选中双方分类并集，可以保留或移除，也可以补充分类。</p>
          <p v-if="hasInactive" class="merge-note">停用分类可保留为历史分类，或在本次归并中移除。</p>
          <div class="merge-taxonomy-columns">
            <fieldset :disabled="submitting || stale"><legend>Topic · 已选 {{ topicIds.length }}</legend><div class="merge-labels"><label v-for="t in unionFirst(preview.available_topics,preview.topic_union)" :key="t.id"><input v-model="topicIds" type="checkbox" :value="t.id" :aria-label="`最终 Topic ${t.name}`" />{{ t.name }}<span v-if="!t.is_active" class="badge warning">停用</span></label></div><p v-if="!preview.available_topics.length" class="helper">暂无 Topic</p></fieldset>
            <fieldset :disabled="submitting || stale"><legend>Tag · 已选 {{ tagIds.length }}</legend><div class="merge-labels"><label v-for="t in unionFirst(preview.available_tags,preview.tag_union)" :key="t.id"><input v-model="tagIds" type="checkbox" :value="t.id" :aria-label="`最终 Tag ${t.name}`" />{{ t.name }}<span v-if="!t.is_active" class="badge warning">停用</span></label></div><p v-if="!preview.available_tags.length" class="helper">暂无 Tag</p></fieldset>
          </div>
        </section>
        <div class="merge-result"><strong>归并后保留 #{{ preview.canonical_id }}</strong><p>#{{ preview.source_question_id }} 的原文、截图、OCR 与练习记录保留原始 ID。新搜索和新练习只显示规范题；收藏和错题按整个归并组汇总。</p></div>
      </template>
    </div>
    <footer class="merge-footer"><p class="helper">{{ submitting ? '正在归并，请等待完成…' : '取消仅关闭预览，同题审核结论会保留，可稍后继续或重新分类。' }}</p><div class="action-row"><button type="button" aria-label="取消归并" :disabled="submitting" @click="close">取消</button><button type="button" class="primary" aria-label="确认归并" :disabled="!preview || loading || submitting || stale || !!error || ((preview.pinned_answers?.length??0)>1 && pinnedAnswerId===null)" @click="confirm">{{ submitting?'正在归并…':'确认归并' }}</button></div></footer>
  </dialog>
</template>

<style scoped>
.merge-dialog { width:min(1024px,calc(100vw - 48px)); max-height:calc(100dvh - 48px); padding:0; border:1px solid var(--border); border-radius:16px; color:var(--ink); background:var(--surface); box-shadow:0 24px 80px #172b4d33; overflow:hidden; }
.merge-pin-choice{margin-top:20px;padding:16px;background:var(--brand-soft);}.merge-pin-choice label{display:flex;flex-direction:row;gap:12px;margin:12px 0;}.merge-pin-content{display:block;white-space:pre-wrap;overflow-wrap:anywhere;max-height:140px;overflow:auto;font-size:13px;margin-top:8px;}
.merge-dialog[open] {display:flex;flex-direction:column;}
.merge-dialog::backdrop {background:#172b4d70;}
.merge-header {flex-shrink:0;display:flex;justify-content:space-between;align-items:flex-start;gap:16px;padding:24px 28px;border-bottom:1px solid var(--border);}
.merge-header h2 {font-size:24px;} .merge-header p {margin:0;color:var(--muted);font-size:13px;} .merge-header button {flex-shrink:0;}
.merge-body {padding:24px 28px;overflow:auto;min-height:0;} .canonical-choice {display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:20px;padding:12px;}
.canonical-choice label {flex-direction:row;align-items:flex-start;gap:12px;padding:12px;border:1px solid var(--border);border-radius:8px;font-size:13px;overflow-wrap:anywhere;}
.canonical-choice label.selected {background:var(--brand-soft);border-color:var(--brand);} input[type=radio] {accent-color:var(--brand);min-height:18px;width:18px;height:18px;padding:0;margin-top:5px;flex-shrink:0;}
.merge-comparison {display:grid;grid-template-columns:1fr 1fr;gap:16px;} .merge-question {min-width:0;border:1px solid var(--border);border-radius:10px;padding:20px;background:#f8fafc;}
.merge-question.canonical {border-top:3px solid var(--brand);background:#f2fafa;} .merge-text {font-size:18px;white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.65;}
.merge-question p {margin-bottom:12px;} .merge-history-count {font-size:12px;color:var(--muted);} .merge-question a {font-size:13px;}
.merge-taxonomy {margin-top:24px;} .merge-taxonomy h3 {margin-bottom:8px;} .merge-taxonomy-columns {display:grid;grid-template-columns:1fr 1fr;gap:16px;}
.merge-labels {display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));max-height:200px;overflow:auto;gap:4px;padding:4px;}
.merge-labels label {font-size:13px;overflow-wrap:anywhere;} .merge-note {font-size:13px;background:var(--warning-soft);color:var(--warning);padding:12px 16px;border-radius:8px;}
.merge-result {margin-top:24px;padding:16px 20px;background:var(--brand-soft);border-radius:8px;}.merge-result p {font-size:13px;margin:8px 0 0;}
.merge-footer {flex-shrink:0;display:flex;gap:16px;align-items:center;justify-content:space-between;padding:20px 28px;border-top:1px solid var(--border);background:var(--surface);}.merge-footer p {max-width:52ch;margin:0;}.merge-footer .action-row {flex-shrink:0;}
@media(max-width:767px) {.merge-dialog {width:calc(100vw - 16px);max-height:calc(100dvh - 16px);border-radius:12px;}.merge-header,.merge-body,.merge-footer {padding:16px;}.merge-header h2 {font-size:21px;}.canonical-choice,.merge-comparison,.merge-taxonomy-columns {grid-template-columns:1fr;}.merge-footer {align-items:stretch;flex-direction:column;}.merge-footer .action-row {justify-content:flex-end;}.merge-labels {max-height:160px;}}
</style>
