<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue';
import { getAnswerVersions, type SavedAnswer, type AnswerVersion } from '../../api/saved-answers';
import SavedAnswerEditor from './SavedAnswerEditor.vue';
const props = defineProps<{answer:SavedAnswer;busy:boolean;readOnly:boolean}>();
const emit = defineEmits<{edit:[id:number,content:string];rate:[id:number,rating:number|null];pin:[id:number,pinned:boolean];archive:[id:number]}>();
const editing=ref(false), historyOpen=ref(false), historyLoading=ref(false), historyError=ref(''), confirmArchive=ref(false);
const versions=ref<AnswerVersion[]>([]), selectedVersion=ref<number|null>(null);
let revision=0;
const date=(value:string)=>new Date(value).toLocaleString('zh-CN',{dateStyle:'medium',timeStyle:'short'});
async function loadVersions(preserveSelection=false) {
  const r=++revision; historyLoading.value=true;historyError.value='';
  try {const result=await getAnswerVersions(props.answer.id);if(r===revision){versions.value=result;if(!preserveSelection||!result.some(v=>v.id===selectedVersion.value))selectedVersion.value=result[0]?.id??null;}}
  catch {if(r===revision)historyError.value='版本历史加载失败，请重试。';}
  finally {if(r===revision)historyLoading.value=false;}
}
function toggleHistory(){historyOpen.value=!historyOpen.value;if(historyOpen.value)void loadVersions();}
function ratingChanged(event:Event){const value=(event.target as HTMLSelectElement).value;emit('rate',props.answer.current_version.id,value?Number(value):null);}
watch(()=>props.answer.current_version.id,()=>{editing.value=false;if(historyOpen.value)void loadVersions();});
watch(()=>props.answer.current_version.self_rating,()=>{if(historyOpen.value)void loadVersions(true);});
onBeforeUnmount(()=>revision++);
</script>
<template>
  <article class="saved-answer" :class="{pinned:answer.is_pinned, archived:answer.archived_at}" :aria-label="`保存回答 ${answer.id}`" :aria-busy="busy">
    <header class="answer-heading"><div class="answer-meta"><strong>回答 #{{ answer.id }}</strong><span v-if="answer.is_pinned" class="badge accent">置顶 · 首选</span><span v-if="answer.archived_at" class="badge">已归档</span><span class="muted">当前 v{{ answer.current_version.version_no }}</span><span class="muted">原题 #{{ answer.question_id }}</span></div><time class="muted">{{ date(answer.updated_at) }}</time></header>
    <SavedAnswerEditor v-if="editing" :initial="answer.current_version.content" :busy="busy" editing @save="emit('edit',answer.id,$event)" @cancel="editing=false" />
    <p v-else class="answer-content">{{ answer.current_version.content }}</p>
    <div class="answer-origin helper"><span>手写回答</span><span v-if="answer.current_version.source_session_item_id">练习项 #{{ answer.current_version.source_session_item_id }} · 自评事件 #{{ answer.current_version.source_practice_review_id }}</span><span v-else>当前版本来自题目详情</span><span v-if="answer.source_session_item_id && !answer.current_version.source_session_item_id">首次保存于练习项 #{{ answer.source_session_item_id }}</span></div>
    <div class="answer-controls">
      <label class="quality-rating">答案质量<select :value="answer.current_version.self_rating??''" :aria-label="`回答 ${answer.id} 质量评分`" :disabled="busy || readOnly || !!answer.archived_at" @change="ratingChanged"><option value="">未评分</option><option v-for="n in 5" :key="n" :value="n">{{ n }} 分</option></select></label>
      <div class="action-row"><template v-if="!readOnly && !answer.archived_at"><button :disabled="busy" @click="editing=!editing">{{ editing?'收起编辑':'编辑回答' }}</button><button :disabled="busy" :aria-pressed="answer.is_pinned" @click="emit('pin',answer.id,!answer.is_pinned)">{{ answer.is_pinned?'取消置顶':'设为首选' }}</button></template><button :disabled="busy" :aria-expanded="historyOpen" @click="toggleHistory">版本历史 · {{ answer.version_count }}</button><button v-if="!readOnly && !answer.archived_at" :disabled="busy" class="quiet danger" @click="confirmArchive=true">归档</button></div>
    </div>
    <div v-if="confirmArchive" class="archive-confirm"><span>归档后隐藏在默认列表中，历史版本会保留。</span><button :disabled="busy" @click="emit('archive',answer.id);confirmArchive=false">确认归档</button><button @click="confirmArchive=false">取消</button></div>
    <section v-if="historyOpen" class="answer-versions" aria-label="回答版本历史"><p v-if="historyLoading" role="status">正在加载版本…</p><div v-else-if="historyError"><p role="alert">{{ historyError }}</p><button @click="loadVersions()">重试版本历史</button></div><template v-else><label>查看版本<select v-model="selectedVersion" :aria-label="`回答 ${answer.id} 历史版本`"><option v-for="v in versions" :key="v.id" :value="v.id">v{{ v.version_no }} · {{ v.self_rating?`${v.self_rating} 分`:'未评分' }} · {{ date(v.created_at) }}</option></select></label><template v-for="v in versions" :key="v.id"><div v-if="selectedVersion===v.id"><p class="helper">只读版本 v{{ v.version_no }} · {{ v.source_session_item_id?`练习项 #${v.source_session_item_id} / 自评 #${v.source_practice_review_id}`:'题目详情保存' }}</p><p class="answer-content">{{ v.content }}</p></div></template></template></section>
  </article>
</template>
<style scoped>
.saved-answer {padding:24px 0;border-top:1px solid var(--border);}
.saved-answer.pinned {padding:24px;border:1px solid var(--brand);border-radius:12px;background:var(--brand-soft);margin:16px 0;}
.saved-answer.archived {opacity:.8;}
.answer-heading,.answer-controls {display:flex;justify-content:space-between;gap:16px;align-items:center;flex-wrap:wrap;}
.answer-meta,.answer-origin {display:flex;flex-wrap:wrap;gap:8px 16px;align-items:center;}
.answer-content {white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.85;margin:20px 0;font-size:15px;}
.answer-origin {margin-bottom:16px;}
.saved-answer .quality-rating {display:flex;flex-direction:row;gap:12px;align-items:center;font-size:13px;}
.answer-controls button {font-size:13px;}
.answer-versions {margin-top:20px;padding:20px;border-left:3px solid var(--border);background:var(--canvas);}
.archive-confirm {display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin:16px 0;padding:12px;background:var(--warning-soft);}
@media(max-width:767px){.saved-answer.pinned{padding:16px;}.answer-versions{padding:12px;}.answer-controls{gap:12px;}.answer-controls .action-row{gap:8px;}}
</style>
