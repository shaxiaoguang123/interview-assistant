<script setup lang="ts">
import { RouterLink } from 'vue-router';
import { formatReviewTime, masteryLabels, type ReviewSchedule } from '../../api/progress';
defineProps<{schedule:ReviewSchedule}>();
</script>
<template>
  <section class="review-status" aria-label="复习状态">
    <div class="review-status-heading"><h3>复习安排</h3><span v-if="schedule.next_review_at" class="badge" :class="{accent:schedule.is_due}">{{ schedule.is_due?'已到期':'待复习' }}</span><span v-else class="muted">尚未复习</span></div>
    <template v-if="schedule.last_reviewed_at"><dl class="review-status-grid"><div><dt>最近练习</dt><dd>{{ formatReviewTime(schedule.last_reviewed_at) }}</dd></div><div><dt>最近掌握度</dt><dd>{{ schedule.last_review_rating ? masteryLabels[schedule.last_review_rating] : '—' }}</dd></div><div><dt>下次复习</dt><dd>{{ formatReviewTime(schedule.next_review_at) }}</dd></div></dl></template>
    <p v-else class="helper">先完成一次练习自评，系统会安排下次复习。</p>
    <div class="review-status-footer"><p class="helper">固定间隔：不会 1 天 · 模糊 2 天 · 基本会 7 天 · 熟练 14 天</p><RouterLink v-if="schedule.is_due" to="/practice?mode=due">进入到期复习</RouterLink></div>
  </section>
</template>
<style scoped>
.review-status{margin:20px 0;padding:20px 24px;border:1px solid var(--border);border-radius:12px;background:var(--surface);}
.review-status-heading,.review-status-footer{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;}.review-status-heading h3{margin:0;}.review-status-grid{display:grid;grid-template-columns:1fr .6fr 1fr;gap:20px;margin:20px 0;}.review-status-grid dt{font-size:13px;color:var(--muted);}.review-status-grid dd{margin:6px 0 0;font-weight:600;}.review-status-footer p{margin:0;}
@media(max-width:600px){.review-status{padding:16px;}.review-status-grid{grid-template-columns:1fr;gap:12px;}}
</style>
