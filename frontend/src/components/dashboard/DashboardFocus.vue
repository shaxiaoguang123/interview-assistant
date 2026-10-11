<script setup lang="ts">
import { RouterLink } from "vue-router";
import { practiceModeLabels, type DashboardSession } from "../../api/dashboard";

withDefaults(defineProps<{ dueCount: number; pendingCandidateCount: number; unfinishedSession: DashboardSession | null }>(), {
  unfinishedSession: null,
});
</script>

<template>
  <section class="dashboard-focus" aria-labelledby="dashboard-focus-title">
    <div class="dashboard-section-heading"><div><span class="eyebrow">今日重点</span><h3 id="dashboard-focus-title">先处理最重要的一步</h3></div></div>
    <article class="dashboard-task dashboard-task-due">
      <div class="dashboard-task-count"><strong>{{ dueCount }}</strong><span>道题</span></div>
      <div class="dashboard-task-copy"><h4>到期复习</h4><p>{{ dueCount ? '按计划回顾之前练过的题目。' : '今天暂时没有到期题目，也可以开始一次随机练习。' }}</p></div>
      <RouterLink class="button-link primary" :to="dueCount ? '/practice?mode=due' : '/practice'">{{ dueCount ? '开始复习' : '开始练习' }}</RouterLink>
    </article>
    <article v-if="unfinishedSession" class="dashboard-task dashboard-task-resume">
      <div class="dashboard-task-count"><strong>{{ unfinishedSession.completed_count }}</strong><span>/ {{ unfinishedSession.item_count }}</span></div>
      <div class="dashboard-task-copy"><h4>继续上次练习</h4><p>{{ practiceModeLabels[unfinishedSession.mode] ?? '练习' }} 还有未完成题目。</p></div>
      <RouterLink class="button-link" :to="`/practice/sessions/${unfinishedSession.id}`">继续练习</RouterLink>
    </article>
    <article class="dashboard-task dashboard-task-inbox">
      <div class="dashboard-task-count"><strong>{{ pendingCandidateCount }}</strong><span>道题</span></div>
      <div class="dashboard-task-copy"><h4>截图待审核</h4><p>{{ pendingCandidateCount ? '确认 OCR 识别内容后加入题库。' : '收件箱已清空，可以继续整理新的截图。' }}</p></div>
      <RouterLink class="button-link" to="/inbox">{{ pendingCandidateCount ? '继续审核' : '打开收件箱' }}</RouterLink>
    </article>
    <nav class="dashboard-shortcuts" aria-label="常用操作">
      <RouterLink to="/questions?new=1">新建题目</RouterLink>
      <RouterLink to="/projects?new=1">新建项目</RouterLink>
      <RouterLink to="/materials?upload=1">上传资料</RouterLink>
    </nav>
  </section>
</template>

<style scoped>
.dashboard-focus{display:grid;gap:12px}.dashboard-section-heading{display:flex;align-items:center;justify-content:space-between;margin:0 0 4px}.dashboard-section-heading h3{font-size:18px;margin:4px 0 0}.dashboard-task{display:grid;grid-template-columns:74px minmax(0,1fr) auto;gap:16px;align-items:center;background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:18px 20px}.dashboard-task-due{border-left:4px solid var(--brand)}.dashboard-task-inbox{border-left:4px solid #d6a24a}.dashboard-task-count{display:flex;align-items:baseline;gap:5px;color:var(--brand-hover)}.dashboard-task-inbox .dashboard-task-count{color:var(--warning)}.dashboard-task-count strong{font-size:28px;line-height:1;font-variant-numeric:tabular-nums}.dashboard-task-count span{font-size:12px;color:var(--muted)}.dashboard-task-copy h4{margin:0;font-size:15px}.dashboard-task-copy p{margin:4px 0 0;color:var(--muted);font-size:13px;line-height:1.5}.button-link{display:inline-flex;min-height:44px;align-items:center;justify-content:center;padding:8px 14px;border:1px solid var(--border);border-radius:var(--control-radius);background:var(--surface);font-weight:600;text-decoration:none;white-space:nowrap}.button-link.primary{background:var(--brand);border-color:var(--brand);color:#fff}.dashboard-shortcuts{display:flex;flex-wrap:wrap;gap:8px 20px;padding:8px 2px}.dashboard-shortcuts a{font-size:13px;font-weight:600}@media(max-width:767px){.dashboard-task{grid-template-columns:60px minmax(0,1fr);gap:12px;padding:16px}.dashboard-task-count strong{font-size:25px}.dashboard-task .button-link{grid-column:1/-1;width:100%}.dashboard-shortcuts{gap:8px 16px}}
</style>
