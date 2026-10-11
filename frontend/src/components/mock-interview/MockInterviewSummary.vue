<script setup lang="ts">
import { RouterLink } from "vue-router";
import type { MockInterviewSummary } from "../../api/mock-interviews";

defineProps<{ summary: MockInterviewSummary }>();
</script>

<template>
  <section class="mock-summary panel" aria-labelledby="mock-summary-title">
    <header class="mock-summary-heading"><div><span class="eyebrow">AI 建议 · 不是客观评分</span><h3 id="mock-summary-title">本次模拟面试总结</h3></div><span class="badge accent">根据本场实际回答</span></header>
    <p class="mock-summary-overview">{{ summary.overview }}</p>
    <div class="mock-summary-items">
      <article v-for="item in summary.items" :key="item.question_id" class="mock-summary-item">
        <h4><RouterLink :to="`/questions/${item.question_id}`">{{ item.question_text }}</RouterLink></h4>
        <p><strong>回答摘要：</strong>{{ item.answer_summary }}</p>
        <div v-if="item.missing_points.length"><strong>可补充的知识点</strong><ul><li v-for="point in item.missing_points" :key="point">{{ point }}</li></ul></div>
        <div v-if="item.technical_concerns.length"><strong>建议核对的技术表述</strong><ul><li v-for="point in item.technical_concerns" :key="point">{{ point }}</li></ul></div>
        <div v-if="item.next_directions.length"><strong>可以继续深入</strong><ul><li v-for="point in item.next_directions" :key="point">{{ point }}</li></ul></div>
      </article>
    </div>
    <section v-if="summary.recommendations.length" class="mock-recommendations" aria-label="推荐复习的题目">
      <h4>推荐继续复习的原题</h4>
      <ul><li v-for="item in summary.recommendations" :key="item.question_id"><RouterLink :to="`/questions/${item.question_id}`">{{ item.question_text }}</RouterLink><span>{{ item.reason }}</span></li></ul>
    </section>
    <p class="helper">建议由模型生成，不会修改题目评分、练习掌握度或复习日期。</p>
  </section>
</template>

<style scoped>
.mock-summary { display: grid; gap: 16px; }
.mock-summary-heading { display: flex; align-items: flex-start; justify-content: space-between; flex-wrap: wrap; gap: 12px; }
.mock-summary-heading h3 { margin: 0; }
.mock-summary-overview { margin: 0; padding: 14px 16px; border-radius: 8px; background: var(--brand-soft); }
.mock-summary-items { display: grid; gap: 12px; }
.mock-summary-item { padding: 16px; border: 1px solid var(--border); border-radius: 8px; background: #fff; }
.mock-summary-item h4 { margin-bottom: 10px; line-height: 1.55; }
.mock-summary-item p { margin: 0 0 8px; }
.mock-summary-item ul,.mock-recommendations ul { margin: 4px 0 8px; padding-left: 22px; }
.mock-recommendations { padding-top: 8px; border-top: 1px solid var(--border); }
.mock-recommendations h4 { margin-bottom: 8px; }
.mock-recommendations li { margin-bottom: 8px; }
.mock-recommendations span { display: block; color: var(--muted); font-size: 13px; }
.mock-summary > .helper { margin: 0; }
</style>
