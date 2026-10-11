<script setup lang="ts">
import { RouterLink } from "vue-router";
import { formatDashboardTime, materialKindLabels, type DashboardMaterial, type DashboardOutput } from "../../api/dashboard";

defineProps<{ projectCount: number; materials: DashboardMaterial[]; outputs: DashboardOutput[] }>();
</script>

<template>
  <section class="panel dashboard-library" aria-labelledby="dashboard-library-title">
    <header class="dashboard-panel-heading"><div><span class="eyebrow">个人资料库</span><h3 id="dashboard-library-title">项目与资料</h3></div><RouterLink to="/projects">管理资料</RouterLink></header>
    <RouterLink class="project-count" to="/projects"><strong>{{ projectCount }}</strong><span>个有效项目</span><span class="project-count-link">查看项目 →</span></RouterLink>
    <div class="dashboard-subheading"><h4>最近资料更新</h4><RouterLink to="/materials">全部资料</RouterLink></div>
    <p v-if="!materials.length" class="dashboard-empty">还没有资料。可上传简历或项目文档，按需选择是否用于 AI 上下文。</p>
    <ul v-else class="dashboard-list compact-list">
      <li v-for="material in materials" :key="material.version_id">
        <RouterLink class="dashboard-list-title" :to="material.is_system_managed && material.project_id ? `/projects/${material.project_id}` : `/materials?material_id=${material.id}&version_id=${material.version_id}`">{{ material.title }}</RouterLink>
        <div class="record-meta"><span>{{ materialKindLabels[material.kind] ?? '资料' }} · v{{ material.version_no }}</span><time :datetime="material.updated_at ?? undefined">{{ formatDashboardTime(material.updated_at) }}</time></div>
      </li>
    </ul>
    <section v-if="outputs.length" class="dashboard-ai" aria-label="最近 AI 输出"><div class="dashboard-subheading"><h4>最近 AI 辅助</h4></div><ul class="dashboard-list compact-list"><li v-for="output in outputs" :key="output.id"><RouterLink class="dashboard-list-title" :to="`/questions/${output.question_id}`">{{ output.preview }}</RouterLink><div class="record-meta"><time :datetime="output.created_at ?? undefined">{{ formatDashboardTime(output.created_at) }}</time><span>AI 建议不参与掌握度或复习计算</span></div></li></ul></section>
    <div class="dashboard-library-actions"><RouterLink to="/projects?new=1">新建项目</RouterLink><RouterLink to="/materials?upload=1">上传资料</RouterLink></div>
  </section>
</template>

<style scoped>
.dashboard-panel-heading,.dashboard-subheading{display:flex;align-items:center;justify-content:space-between;gap:12px}.dashboard-panel-heading h3{font-size:18px;margin:4px 0 0}.dashboard-panel-heading>a,.dashboard-subheading>a{font-size:13px;white-space:nowrap}.dashboard-subheading{margin-top:18px}.dashboard-subheading h4{font-size:14px;margin:0}.project-count{display:flex;align-items:baseline;gap:9px;margin:18px 0;padding:14px 16px;border-radius:8px;background:var(--brand-soft);text-decoration:none}.project-count strong{font-size:28px;line-height:1;color:var(--brand-hover)}.project-count span{font-size:13px;color:var(--muted)}.project-count .project-count-link{margin-left:auto;color:var(--brand-hover);font-weight:650}.dashboard-empty{margin:12px 0 0;color:var(--muted);font-size:13px}.dashboard-list{list-style:none;margin:0;padding:0}.dashboard-list li{padding:12px 0;border-bottom:1px solid var(--border)}.dashboard-list-title{display:block;font-size:14px;font-weight:650;line-height:1.5;text-decoration:none;overflow-wrap:anywhere}.record-meta{margin-top:6px}.dashboard-ai{margin-top:12px;padding-top:6px;border-top:1px solid var(--border)}.dashboard-ai .record-meta span:last-child{max-width:100%;}.dashboard-library-actions{display:flex;gap:16px;margin-top:18px;font-size:13px;font-weight:650}@media(max-width:480px){.project-count{align-items:flex-start;flex-wrap:wrap}.project-count .project-count-link{margin-left:0;width:100%}.dashboard-library-actions{flex-wrap:wrap}}
</style>
