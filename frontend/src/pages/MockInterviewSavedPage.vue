<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from "vue";
import { RouterLink, useRoute } from "vue-router";
import { ApiError } from "../api/client";
import { getSavedMockInterview, type SavedMockInterview } from "../api/mock-interviews";
import MockInterviewConversation from "../components/mock-interview/MockInterviewConversation.vue";
import MockInterviewSummary from "../components/mock-interview/MockInterviewSummary.vue";

const route = useRoute();
const record = ref<SavedMockInterview | null>(null);
const loading = ref(true);
const errorMessage = ref("");
let revision = 0;
let alive = true;

function errorText(error: unknown): string {
  return error instanceof ApiError ? error.message : "请求失败，请稍后重试。";
}

async function load(): Promise<void> {
  const id = Number(route.params.id);
  const current = ++revision;
  record.value = null;
  loading.value = true;
  errorMessage.value = "";
  try {
    const result = await getSavedMockInterview(id);
    if (alive && current === revision) record.value = result;
  } catch (error) {
    if (alive && current === revision) errorMessage.value = errorText(error);
  } finally {
    if (alive && current === revision) loading.value = false;
  }
}

watch(() => route.params.id, () => void load(), { immediate: true });
onBeforeUnmount(() => { alive = false; revision++; });
</script>

<template>
  <section class="mock-saved-page" aria-labelledby="mock-saved-title">
    <header class="page-heading"><div><span class="eyebrow">已保存的本地记录</span><h2 id="mock-saved-title">模拟面试回顾</h2></div><RouterLink to="/mock-interview">返回模拟面试</RouterLink></header>
    <p v-if="loading" role="status">正在加载面试记录…</p>
    <p v-if="errorMessage" role="alert">{{ errorMessage }}</p>
    <template v-if="record">
      <section class="panel mock-saved-meta">
        <div><span class="badge">{{ record.topic_name || "综合面试" }}</span><h3>{{ record.title }}</h3><p>{{ record.question_count }} 道题 · {{ record.created_at ? new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short" }).format(new Date(record.created_at)) : "时间未知" }}</p></div>
        <p v-if="record.model" class="helper">AI Provider：{{ record.model }}</p>
      </section>
      <MockInterviewSummary v-if="record.summary" :summary="record.summary" />
      <section v-else class="empty-state">本次记录未生成 AI 总结，完整对话仍保存在下方。</section>
      <MockInterviewConversation :turns="record.turns ?? []" />
      <section v-if="record.summary_sources?.length" class="panel mock-saved-sources">
        <h3>总结引用的资料版本</h3>
        <ul><li v-for="source in record.summary_sources" :key="source.material_version_id">{{ source.title }} · 第 {{ source.version_no }} 版 · 片段 {{ source.chunk_ids.join(", ") || "无片段" }}</li></ul>
        <p class="helper">保存的是来源版本和片段引用快照，不包含原始资料正文副本。</p>
      </section>
    </template>
  </section>
</template>

<style scoped>
.mock-saved-page { display: grid; gap: 20px; }
.mock-saved-meta { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.mock-saved-meta h3 { margin: 8px 0 4px; overflow-wrap: anywhere; }
.mock-saved-meta p { margin: 0; color: var(--muted); font-size: 13px; }
.mock-saved-meta .helper { text-align: right; }
.mock-saved-sources h3 { margin-bottom: 8px; }
.mock-saved-sources ul { margin: 0 0 8px; overflow-wrap: anywhere; }
.mock-saved-sources p { margin: 0; }
@media (max-width: 680px) { .mock-saved-meta { flex-direction: column; } .mock-saved-meta .helper { text-align: left; } }
</style>
