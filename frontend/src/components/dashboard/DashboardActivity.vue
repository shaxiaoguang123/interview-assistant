<script setup lang="ts">
import { RouterLink } from "vue-router";
import { formatDashboardTime, practiceModeLabels, type DashboardAnswer, type DashboardSession } from "../../api/dashboard";

defineProps<{ answers: DashboardAnswer[]; sessions: DashboardSession[] }>();
</script>

<template>
  <section class="panel dashboard-activity" aria-labelledby="dashboard-activity-title">
    <header class="dashboard-panel-heading"><div><span class="eyebrow">最近活动</span><h3 id="dashboard-activity-title">练习与回答</h3></div><RouterLink to="/practice">开始练习</RouterLink></header>
    <section class="dashboard-subsection" aria-labelledby="dashboard-answers-title">
      <div class="dashboard-subheading"><h4 id="dashboard-answers-title">最近保存的回答</h4><RouterLink to="/questions">查看题库</RouterLink></div>
      <p v-if="!answers.length" class="dashboard-empty">还没有保存的回答。完成一道练习后，可以选择保留自己的答案。</p>
      <ul v-else class="dashboard-list">
        <li v-for="answer in answers" :key="answer.id">
          <RouterLink class="dashboard-list-title" :to="`/questions/${answer.question_id}`">{{ answer.question_text }}</RouterLink>
          <p v-if="answer.preview" class="dashboard-preview">{{ answer.preview }}</p>
          <div class="record-meta"><time :datetime="answer.updated_at ?? undefined">{{ formatDashboardTime(answer.updated_at) }}</time><span v-if="answer.self_rating !== null">答案质量 {{ answer.self_rating }}/5</span><span v-if="answer.is_pinned" class="badge accent">置顶</span></div>
        </li>
      </ul>
    </section>
    <section class="dashboard-subsection" aria-labelledby="dashboard-sessions-title">
      <div class="dashboard-subheading"><h4 id="dashboard-sessions-title">最近练习</h4><RouterLink to="/progress">查看进度</RouterLink></div>
      <p v-if="!sessions.length" class="dashboard-empty">还没有练习记录。随机练习可以从任意题目开始。</p>
      <ul v-else class="dashboard-list dashboard-session-list">
        <li v-for="session in sessions" :key="session.id">
          <RouterLink class="dashboard-list-title" :to="`/practice/sessions/${session.id}`">{{ practiceModeLabels[session.mode] ?? '练习' }} · {{ session.completed_count }}/{{ session.item_count }} 题</RouterLink>
          <div class="record-meta"><time :datetime="session.started_at ?? undefined">{{ formatDashboardTime(session.started_at) }}</time><span>{{ session.completed_at ? '已完成' : '进行中' }}</span></div>
        </li>
      </ul>
    </section>
  </section>
</template>

<style scoped>
.dashboard-panel-heading,.dashboard-subheading{display:flex;align-items:center;justify-content:space-between;gap:12px}.dashboard-panel-heading h3{font-size:18px;margin:4px 0 0}.dashboard-panel-heading>a,.dashboard-subheading>a{font-size:13px;white-space:nowrap}.dashboard-subsection{margin-top:22px}.dashboard-subheading h4{font-size:14px;margin:0}.dashboard-empty{margin:12px 0 0;color:var(--muted);font-size:13px}.dashboard-list{list-style:none;margin:0;padding:0}.dashboard-list li{padding:14px 0;border-bottom:1px solid var(--border)}.dashboard-list-title{display:block;font-size:14px;font-weight:650;line-height:1.5;text-decoration:none}.dashboard-preview{margin:6px 0;color:var(--muted);font-size:13px;line-height:1.55;white-space:pre-wrap;overflow-wrap:anywhere}.record-meta{margin-top:7px}.dashboard-session-list li:last-child{border-bottom:0;padding-bottom:0}
</style>
