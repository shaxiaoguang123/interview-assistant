<script setup lang="ts">
import { RouterLink } from "vue-router";
</script>

<template>
  <section class="panel dashboard-welcome" aria-labelledby="dashboard-welcome-title">
    <div class="welcome-copy"><span class="eyebrow">欢迎开始</span><h3 id="dashboard-welcome-title">先把常用资料放进你的工作台</h3><p>可以从一道面试题开始，也可以导入截图、整理项目经历或上传简历。每一步都可以稍后完成。</p></div>
    <nav class="welcome-actions" aria-label="首次使用快捷入口">
      <RouterLink class="welcome-action welcome-action-primary" to="/questions?new=1"><strong>添加第一道题</strong><span>手动整理知识点</span></RouterLink>
      <RouterLink class="welcome-action" to="/inbox"><strong>导入截图</strong><span>识别后再确认入库</span></RouterLink>
      <RouterLink class="welcome-action" to="/projects?new=1"><strong>创建个人项目</strong><span>维护经历与技术细节</span></RouterLink>
      <RouterLink class="welcome-action" to="/materials?upload=1"><strong>上传简历或资料</strong><span>按需选择 AI 上下文</span></RouterLink>
    </nav>
  </section>
</template>

<style scoped>
.dashboard-welcome{display:grid;grid-template-columns:minmax(220px,.8fr) minmax(0,1.8fr);gap:24px;margin:0 0 20px;border-color:var(--brand-border,#c6d7f2);background:linear-gradient(115deg,var(--surface),var(--brand-soft,#edf4ff))}.welcome-copy h3{font-size:19px;margin:6px 0}.welcome-copy p{margin:0;color:var(--muted);font-size:13px;line-height:1.6}.welcome-actions{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.welcome-action{display:grid;align-content:center;gap:3px;min-height:64px;padding:10px 14px;border:1px solid var(--border);border-radius:8px;background:var(--surface);text-decoration:none}.welcome-action strong{font-size:13px}.welcome-action span{color:var(--muted);font-size:12px}.welcome-action-primary{border-color:var(--brand);background:var(--brand);color:#fff}.welcome-action-primary span{color:rgba(255,255,255,.82)}@media(max-width:767px){.dashboard-welcome{grid-template-columns:1fr;gap:16px}.welcome-actions{grid-template-columns:1fr}.welcome-action{min-height:58px}}
</style>
