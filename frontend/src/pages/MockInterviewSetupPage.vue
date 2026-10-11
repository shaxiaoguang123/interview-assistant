<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from "vue";
import { RouterLink, useRouter } from "vue-router";
import { ApiError } from "../api/client";
import {
  getMockInterviewOptions,
  listSavedMockInterviews,
  startMockInterview,
  type MockInterviewOptions,
  type SavedMockInterview,
} from "../api/mock-interviews";
import MockInterviewSetupForm from "../components/mock-interview/MockInterviewSetupForm.vue";

const router = useRouter();
const options = ref<MockInterviewOptions | null>(null);
const records = ref<SavedMockInterview[]>([]);
const loading = ref(true);
const starting = ref(false);
const errorMessage = ref("");
let alive = true;

function errorText(error: unknown): string {
  return error instanceof ApiError ? error.message : "请求失败，请稍后重试。";
}

async function load(): Promise<void> {
  loading.value = true;
  errorMessage.value = "";
  try {
    const [loadedOptions, saved] = await Promise.all([getMockInterviewOptions(), listSavedMockInterviews()]);
    if (!alive) return;
    options.value = loadedOptions;
    records.value = saved;
  } catch (error) {
    if (alive) errorMessage.value = errorText(error);
  } finally {
    if (alive) loading.value = false;
  }
}

async function start(payload: { topic_id: number | null; question_count: number; context: { project_ids: number[]; material_ids: number[]; exclude_material_ids: number[] } }): Promise<void> {
  if (starting.value) return;
  starting.value = true;
  errorMessage.value = "";
  try {
    const interview = await startMockInterview(payload);
    if (alive) await router.push({ name: "mock-interview-room", params: { sessionId: interview.id } });
  } catch (error) {
    if (alive) errorMessage.value = errorText(error);
  } finally {
    if (alive) starting.value = false;
  }
}

function dateLabel(value: string | null): string {
  if (!value) return "时间未知";
  return new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

onMounted(() => void load());
onBeforeUnmount(() => { alive = false; });
</script>

<template>
  <section class="mock-setup-page" aria-labelledby="mock-setup-title">
    <header class="page-heading">
      <div><span class="eyebrow">AI Text Mock Interview</span><h2 id="mock-setup-title">文字模拟面试</h2><p>从真实题库出发，练习现场回答，并选择是否请 AI 面试官追问。</p></div>
      <RouterLink to="/practice">普通练习</RouterLink>
    </header>

    <p v-if="errorMessage" role="alert">{{ errorMessage }} <button type="button" @click="load">重新加载</button></p>
    <p v-if="loading" role="status">正在读取题库与已保存记录…</p>
    <template v-else-if="options">
      <MockInterviewSetupForm :options="options" :busy="starting" @start="start" />

      <section class="mock-history-section" aria-labelledby="mock-history-title">
        <header class="mock-history-heading"><div><span class="eyebrow">仅显示明确保存的面试</span><h3 id="mock-history-title">模拟面试记录</h3></div><button type="button" @click="load">刷新</button></header>
        <ul v-if="records.length" class="mock-history-list">
          <li v-for="record in records" :key="record.id">
            <div><strong>{{ record.title }}</strong><span>{{ record.topic_name || "综合面试" }} · {{ record.question_count }} 道题 · {{ dateLabel(record.created_at) }}</span><p v-if="record.summary">{{ record.summary.overview }}</p></div>
            <RouterLink :to="{ name: 'mock-interview-saved', params: { id: record.id } }">查看记录</RouterLink>
          </li>
        </ul>
        <p v-else class="empty-state">还没有已保存的模拟面试。临时会话不会自动进入这里。</p>
      </section>
    </template>
  </section>
</template>

<style scoped>
.mock-setup-page { display: grid; gap: 24px; }
.mock-history-section { display: grid; gap: 12px; }
.mock-history-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.mock-history-heading h3 { margin: 0; }
.mock-history-list { list-style: none; margin: 0; padding: 0; border: 1px solid var(--border); border-radius: 12px; background: var(--surface); }
.mock-history-list li { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 16px 20px; border-bottom: 1px solid var(--border); }
.mock-history-list li:last-child { border-bottom: 0; }
.mock-history-list li > div { min-width: 0; display: grid; gap: 4px; }
.mock-history-list li span,.mock-history-list li p { color: var(--muted); font-size: 13px; margin: 0; }
@media (max-width: 680px) { .mock-history-list li { align-items: flex-start; flex-direction: column; padding: 16px; } }
</style>
