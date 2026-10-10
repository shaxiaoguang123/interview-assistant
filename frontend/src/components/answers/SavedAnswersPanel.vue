<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue';
import { ApiError } from '../../api/client';
import { getSavedAnswers, createSavedAnswer, appendAnswerVersion, rateAnswer, pinAnswer, archiveAnswer, type SavedAnswer } from '../../api/saved-answers';
import SavedAnswerEditor from './SavedAnswerEditor.vue';
import SavedAnswerCard from './SavedAnswerCard.vue';
const props=withDefaults(defineProps<{questionId:number;questionText?:string;readOnly?:boolean}>(),{readOnly:false,questionText:''});
const emit=defineEmits<{changed:[]}>();
const answers = ref<SavedAnswer[]>([]);
const creating = ref(false);
const loading = ref(true);
const busy = ref(false);
const error = ref('');
const success = ref('');
const includeArchived = ref(false);
let revision = 0;
let alive = true;

async function load() {
  const r = ++revision;
  loading.value = true;
  error.value = '';
  try {
    const data = await getSavedAnswers(props.questionId, includeArchived.value);
    if (!Array.isArray(data)) throw new Error('Invalid answers response');
    if (alive && r === revision) answers.value = data;
  } catch (e) {
    if (alive && r === revision) error.value = e instanceof ApiError ? e.message : '回答加载失败，请重试。';
  } finally {
    if (alive && r === revision) loading.value = false;
  }
}

async function mutate(action:()=>Promise<unknown>, message:string, closeCreate=false) {
  if (busy.value) return;
  const id = props.questionId;
  const r = revision;
  busy.value = true;
  error.value = '';
  success.value = '';
  try {
    await action();
    if (!alive || id !== props.questionId || r !== revision) return;
    if (closeCreate) creating.value = false;
    success.value = message;
    await load();
    if (alive && id === props.questionId) emit('changed');
  } catch (e) {
    if (alive && id === props.questionId && r === revision)
      error.value = e instanceof ApiError ? e.message : '操作失败，正文已保留，请重试。';
  } finally {
    if (alive && id === props.questionId) busy.value = false;
  }
}

watch(() => props.questionId, () => {
  answers.value = [];
  creating.value = false;
  busy.value = false;
  success.value = '';
  void load();
}, {immediate:true, flush:'sync'});
watch(includeArchived, () => void load());
onBeforeUnmount(() => { alive = false; revision++; });
</script>
<template>
  <section class="saved-answers-panel" aria-labelledby="saved-answers-title" :aria-busy="busy">
    <header class="answer-panel-heading"><div><h3 id="saved-answers-title">保存回答 <span class="muted">{{ answers.length }}</span></h3><p class="helper">每条回答独立保留版本。1–5 分评价答案质量，与练习掌握程度无关。</p></div><button v-if="!readOnly" class="primary" :disabled="busy || creating" @click="creating=true">新建回答</button></header>
    <p v-if="questionText" class="answer-question-context">{{ questionText }}</p>
    <div class="answer-panel-tools"><span class="helper">置顶优先 · 当前版本评分由高到低 · 未评分在后</span><label><input v-model="includeArchived" type="checkbox" :disabled="busy" /> 包含已归档</label></div>
    <p v-if="error" role="alert" class="error-banner">{{ error }} <button v-if="!busy" @click="load">重新加载</button></p><p v-if="success" role="status" class="success-banner">{{ success }}</p>
    <SavedAnswerEditor v-if="creating" :busy="busy" @save="mutate(()=>createSavedAnswer(questionId,{content:$event}),'回答已保存。',true)" @cancel="creating=false" />
    <p v-if="loading && !answers.length" role="status">正在加载回答…</p><p v-else-if="!answers.length && !error && !creating" class="answer-empty">还没有保存回答。留下简短要点或完整表达，逐次完善自己的答案。</p>
    <SavedAnswerCard v-for="answer in answers" :key="`${questionId}:${answer.id}`" :answer="answer" :busy="busy" :read-only="readOnly" @edit="(id,content)=>mutate(()=>appendAnswerVersion(id,content),'新版本已保存，旧版本继续保留。')" @rate="(id,rating)=>mutate(()=>rateAnswer(id,rating),'答案质量评分已更新。')" @pin="(id,pinned)=>mutate(()=>pinAnswer(id,pinned),pinned?'已设为首选；本归并组的其他回答已取消置顶。':'已取消置顶。')" @archive="id=>mutate(()=>archiveAnswer(id),'回答已归档，版本历史仍保留。')" />
  </section>
</template>
<style scoped>
.saved-answers-panel{margin:32px 0;padding:24px;background:var(--surface);border:1px solid var(--border);border-radius:12px;}
.answer-panel-heading,.answer-panel-tools{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:16px;}
.answer-panel-heading h3{margin:0;}.answer-panel-heading h3 span{font-size:14px;margin-left:8px;}.answer-panel-heading p{margin-bottom:0;}
.answer-panel-tools{margin:20px 0;font-size:13px;}.answer-panel-tools label{display:flex;align-items:center;gap:8px;}.answer-empty{padding:24px 0;color:var(--muted);}
.answer-question-context{margin:20px 0 0;padding:12px 16px;border-left:3px solid var(--brand);background:var(--canvas);white-space:pre-wrap;overflow-wrap:anywhere;}
@media(max-width:767px){.saved-answers-panel{padding:16px;}.answer-panel-heading{align-items:flex-start;}}
</style>
