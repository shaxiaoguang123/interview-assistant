<script setup lang="ts">
import { shallowRef, watch, onBeforeUnmount } from 'vue';
import { RouterLink } from 'vue-router';
import { ApiError } from '../api/client';
import { getProgress, formatReviewTime, type ProgressData } from '../api/progress';
import ProgressOverview from '../components/review/ProgressOverview.vue';
import TopicProgressList from '../components/review/TopicProgressList.vue';
const data=shallowRef<ProgressData|null>(null), loading=shallowRef(false), error=shallowRef(''), windowDays=shallowRef(30);
let revision=0;
async function load(){const requestId=++revision;loading.value=true;error.value='';try{const result=await getProgress(windowDays.value);if(requestId===revision)data.value=result;}catch(e){if(requestId===revision)error.value=e instanceof ApiError?e.message:'无法加载学习进度，请重试。';}finally{if(requestId===revision)loading.value=false;}}
watch(windowDays,()=>void load(),{immediate:true});onBeforeUnmount(()=>revision++);
</script>
<template>
  <section class="progress-page" aria-labelledby="progress-title"><header class="page-heading"><div><span class="eyebrow">学习进度</span><h2 id="progress-title">保持练习，看见积累</h2><p>根据真实练习记录了解覆盖情况，优先巩固到期题与薄弱知识点。</p></div><button :disabled="loading" @click="load">{{ loading?'正在更新…':'刷新进度' }}</button></header>
    <p v-if="error" role="alert">{{ error }}</p><p v-if="loading && !data" role="status">正在加载学习进度…</p>
    <template v-if="data"><ProgressOverview :data="data"/><section v-if="data.due_questions.length" class="panel due-list" aria-label="到期题目"><div class="action-row"><h3>待复习题目</h3><RouterLink to="/practice?mode=due">查看复习设置</RouterLink></div><ol><li v-for="question in data.due_questions" :key="question.id"><RouterLink :to="`/questions/${question.id}`">{{ question.text }}</RouterLink><time :datetime="question.next_review_at??undefined">{{ formatReviewTime(question.next_review_at) }} 到期</time></li></ol><p v-if="data.due_question_count>data.due_list_limit" class="helper">展示最早到期的 {{ data.due_list_limit }} 道题，完整队列可在练习中选择。</p></section>
    <div class="progress-window"><label>弱项统计窗口<select v-model.number="windowDays" aria-label="弱项统计窗口"><option :value="7">最近 7 天</option><option :value="30">最近 30 天</option><option :value="90">最近 90 天</option></select></label><span class="helper">数据更新于 {{ formatReviewTime(data.as_of) }}</span></div><TopicProgressList :topics="data.topics" :window-days="data.window_days" /></template>
  </section>
</template>
<style scoped>
.due-list{margin-top:24px;}.due-list ol{margin:0;padding:0;list-style:none;}.due-list li{display:flex;gap:24px;justify-content:space-between;padding:16px 0;border-top:1px solid var(--border);}.due-list a{overflow-wrap:anywhere;}.due-list time{font-size:13px;color:var(--muted);flex-shrink:0;}.progress-window{display:flex;justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap;margin-top:32px;}.progress-window label{display:flex;gap:12px;align-items:center;}.progress-window select{width:auto;}
@media(max-width:767px){.due-list li{flex-direction:column;gap:8px;}}
</style>
