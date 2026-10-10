<script setup lang="ts">
import { computed } from 'vue';
import { RouterLink } from 'vue-router';
import { masteryLabels, type TopicProgress } from '../../api/progress';
const props=defineProps<{topics:TopicProgress[];windowDays:number}>();
const relevantTopics=computed(()=>props.topics.filter(t=>t.question_count>0||t.review_count>0));
const emptyTopics=computed(()=>props.topics.filter(t=>t.question_count===0&&t.review_count===0));
</script>
<template>
  <section class="panel topic-progress" aria-label="Topic 覆盖与弱项"><h3>Topic 覆盖与薄弱知识点</h3><p class="helper">最近 {{ windowDays }} 天按「不会 + 模糊」占比排序；少于 3 次自评不参与弱项排序。归并题按规范题当前分类计数。</p>
    <p v-if="!topics.length" class="empty-state">还没有启用的 Topic，可先在分类管理中添加。</p>
    <div v-for="topic in relevantTopics" :key="topic.id" class="topic-progress-row"><div class="topic-progress-name"><strong>{{ topic.name }}</strong><span class="helper">已练习 {{ topic.reviewed_question_count }} / {{ topic.question_count }} 道题</span><progress :aria-label="`${topic.name}覆盖`" :value="topic.reviewed_question_count" :max="Math.max(1,topic.question_count)" /></div><div class="topic-progress-evidence"><span v-if="!topic.has_enough_records" class="badge">练习记录不足 · {{ topic.review_count }} 次</span><template v-else><span class="badge accent">不会或模糊 {{ Math.round((topic.weak_ratio??0)*100) }}% · {{ topic.review_count }} 次</span><p class="helper"><span v-for="(label,rating) in masteryLabels" :key="rating">{{ label }} {{ topic.mastery_counts[rating] }} </span></p></template></div><RouterLink v-if="topic.question_count" :to="`/practice?mode=topic&topic_id=${topic.id}`">练习此 Topic</RouterLink></div>
    <details v-if="emptyTopics.length" class="empty-topics"><summary>其他启用 Topic · {{ emptyTopics.length }} 个暂无题目</summary><p class="helper">练习记录不足。添加题目后，这些 Topic 会出现在覆盖列表中。</p><div class="empty-topic-tags"><span v-for="topic in emptyTopics" :key="topic.id" class="badge">{{ topic.name }}</span></div></details>
  </section>
</template>
<style scoped>
.topic-progress{margin-top:24px;}.topic-progress-row{display:grid;grid-template-columns:minmax(160px,1fr) minmax(210px,1.2fr) auto;align-items:center;gap:24px;padding:20px 0;border-top:1px solid var(--border);}.topic-progress-name{display:flex;flex-direction:column;gap:5px;}.topic-progress-name progress{width:100%;max-width:220px;height:6px;margin:4px 0;accent-color:var(--brand);}.topic-progress-evidence p{margin:8px 0 0;}.topic-progress-evidence p span{margin-right:8px;}.empty-topic-tags{display:flex;gap:8px;flex-wrap:wrap;}.empty-topics{margin-top:16px;}.topic-progress-row a{white-space:nowrap;}
@media(max-width:767px){.topic-progress-row{grid-template-columns:1fr;gap:12px;}}
</style>
