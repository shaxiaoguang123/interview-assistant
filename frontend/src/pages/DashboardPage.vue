<script setup lang="ts">
import { onBeforeUnmount, onMounted, shallowRef } from "vue";
import { RouterLink } from "vue-router";
import { ApiError } from "../api/client";
import { getDashboard, type DashboardData } from "../api/dashboard";
import DashboardActivity from "../components/dashboard/DashboardActivity.vue";
import DashboardFocus from "../components/dashboard/DashboardFocus.vue";
import DashboardLibrary from "../components/dashboard/DashboardLibrary.vue";

const data = shallowRef<DashboardData | null>(null);
const loading = shallowRef(true);
const error = shallowRef("");
let revision = 0;

async function load() {
  const requestId = ++revision;
  loading.value = true;
  error.value = "";
  try {
    const result = await getDashboard();
    if (requestId === revision) data.value = result;
  } catch (caught) {
    if (requestId === revision) {
      error.value = caught instanceof ApiError ? caught.message : "工作台暂时无法加载，请重试。";
    }
  } finally {
    if (requestId === revision) loading.value = false;
  }
}

onMounted(() => void load());
onBeforeUnmount(() => { revision += 1; });
</script>

<template>
  <section class="dashboard-page" aria-labelledby="dashboard-title">
    <header class="dashboard-hero">
      <div><span class="eyebrow">个人学习工作台</span><h2 id="dashboard-title">今天，从一个小目标开始</h2><p>查看待复习题、截图审核和最近的学习记录，接着上次的进度继续。</p></div>
      <RouterLink to="/questions?new=1" class="dashboard-add-question">＋ 新建题目</RouterLink>
    </header>
    <p v-if="loading && !data" role="status" class="panel dashboard-loading">正在读取你的工作台…</p>
    <div v-else-if="error" class="panel dashboard-error"><p role="alert">{{ error }}</p><button type="button" aria-label="重试加载工作台" @click="load">重新加载</button></div>
    <template v-else-if="data">
      <div class="dashboard-grid">
        <div class="dashboard-primary-column">
          <DashboardFocus :due-count="data.due_question_count" :pending-candidate-count="data.pending_candidate_count" />
          <DashboardActivity :answers="data.recent_answers" :sessions="data.recent_sessions" />
        </div>
        <DashboardLibrary :project-count="data.active_project_count" :materials="data.recent_materials" :outputs="data.recent_ai_outputs" />
      </div>
      <footer class="dashboard-footer"><span>数据来自本机题库与练习记录</span><RouterLink to="/settings">备份与模型设置</RouterLink></footer>
    </template>
  </section>
</template>

<style scoped>
.dashboard-page{max-width:1360px;margin:0 auto}.dashboard-hero{display:flex;align-items:flex-end;justify-content:space-between;gap:24px;margin-bottom:26px;padding:8px 0 20px;border-bottom:1px solid var(--border)}.dashboard-hero h2{font-size:30px;line-height:1.25;margin:8px 0}.dashboard-hero p{max-width:66ch;margin:0;color:var(--muted)}.dashboard-add-question{display:inline-flex;min-height:44px;align-items:center;justify-content:center;padding:8px 16px;border-radius:8px;background:var(--brand);color:#fff;font-weight:650;text-decoration:none;white-space:nowrap}.dashboard-grid{display:grid;grid-template-columns:minmax(0,1.3fr) minmax(320px,.85fr);gap:24px;align-items:start}.dashboard-primary-column{display:grid;gap:24px;min-width:0}.dashboard-activity,.dashboard-library{min-width:0}.dashboard-loading{color:var(--muted)}.dashboard-error{display:flex;align-items:center;justify-content:space-between;gap:16px}.dashboard-footer{display:flex;justify-content:space-between;gap:16px;margin-top:24px;color:var(--muted);font-size:12px}@media(max-width:1023px){.dashboard-grid{grid-template-columns:minmax(0,1fr) minmax(280px,.8fr);gap:16px}.dashboard-hero h2{font-size:27px}}@media(max-width:767px){.dashboard-hero{display:grid;align-items:start;gap:16px;margin-bottom:20px}.dashboard-hero h2{font-size:24px}.dashboard-add-question{width:100%}.dashboard-grid{grid-template-columns:1fr;gap:16px}.dashboard-footer{align-items:flex-start;flex-direction:column}.dashboard-error{align-items:flex-start;flex-direction:column}}
</style>
