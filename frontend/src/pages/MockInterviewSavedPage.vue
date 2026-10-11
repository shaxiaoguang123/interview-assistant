<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { RouterLink, useRoute } from "vue-router";
import { ApiError, request } from "../api/client";
import { getSavedMockInterview, type SavedMockInterview } from "../api/mock-interviews";
import type { MockInterviewTurn } from "../api/mock-interviews";
import MockInterviewReviewPanel from "../components/mock-interview/MockInterviewReviewPanel.vue";
import MockInterviewSummary from "../components/mock-interview/MockInterviewSummary.vue";

const route = useRoute();
const record = ref<SavedMockInterview | null>(null);
const loading = ref(true);
const errorMessage = ref("");
const reviewActionError = ref("");
const questionStates = ref<Record<number, { canonicalQuestionId: number; is_wrong: boolean; writable: boolean }>>({});
const markingQuestionIds = ref<number[]>([]);
let revision = 0;
let alive = true;

interface SavedTurn extends MockInterviewTurn { id: number }
interface QuestionReviewDetail {
  id: number;
  status: string;
  canonical_question_id: number | null;
  archived_at: string | null;
  state: { is_wrong: boolean };
}

const savedTurns = computed<SavedTurn[]>(() => (record.value?.turns ?? []).filter(
  (turn): turn is SavedTurn => Number.isSafeInteger(turn.id) && (turn.id as number) > 0,
));
const allowedQuestionIds = computed(() => new Set(savedTurns.value.map((turn) => turn.question_id)));
const safeSummary = computed(() => {
  const summary = record.value?.summary;
  if (!summary) return null;
  return {
    ...summary,
    items: summary.items.filter((item) => allowedQuestionIds.value.has(item.question_id)),
    recommendations: summary.recommendations.filter((item) => allowedQuestionIds.value.has(item.question_id)),
  };
});

function errorText(error: unknown): string {
  return error instanceof ApiError ? error.message : "请求失败，请稍后重试。";
}

async function load(): Promise<void> {
  const id = Number(route.params.id);
  const current = ++revision;
  record.value = null;
  questionStates.value = {};
  markingQuestionIds.value = [];
  reviewActionError.value = "";
  loading.value = true;
  errorMessage.value = "";
  try {
    const result = await getSavedMockInterview(id);
    if (alive && current === revision) {
      record.value = result;
      if (result.summary) void loadQuestionStates(result, current);
    }
  } catch (error) {
    if (alive && current === revision) errorMessage.value = errorText(error);
  } finally {
    if (alive && current === revision) loading.value = false;
  }
}

async function loadQuestionStates(sourceRecord: SavedMockInterview, current: number): Promise<void> {
  const turns = (sourceRecord.turns ?? []).filter((turn): turn is SavedTurn => Number.isSafeInteger(turn.id) && (turn.id as number) > 0);
  const validTurnQuestions = new Set(turns.map((turn) => turn.question_id));
  const ids = [...new Set([
    ...(sourceRecord.summary?.items.map((item) => item.question_id) ?? []),
    ...(sourceRecord.summary?.recommendations.map((item) => item.question_id) ?? []),
  ])].filter((id) => validTurnQuestions.has(id));
  const pairs = await Promise.all(ids.map(async (id) => {
    try {
      const original = await request<QuestionReviewDetail>(`/api/v1/questions/${id}`);
      const canonicalId = original.status === "merged" && original.canonical_question_id
        ? original.canonical_question_id
        : original.id;
      const canonical = canonicalId === original.id
        ? original
        : await request<QuestionReviewDetail>(`/api/v1/questions/${canonicalId}`);
      return [id, {
        canonicalQuestionId: canonical.id,
        is_wrong: canonical.state?.is_wrong === true,
        writable: canonical.status === "active" && canonical.canonical_question_id === canonical.id && !canonical.archived_at,
      }] as const;
    } catch {
      return [id, { canonicalQuestionId: id, is_wrong: false, writable: false }] as const;
    }
  }));
  if (!alive || current !== revision) return;
  questionStates.value = Object.fromEntries(pairs);
}

async function markQuestionWrong(questionId: number): Promise<void> {
  const state = questionStates.value[questionId];
  const current = revision;
  if (!state?.writable || state.is_wrong || markingQuestionIds.value.includes(questionId)) return;
  reviewActionError.value = "";
  markingQuestionIds.value = [...markingQuestionIds.value, questionId];
  try {
    await request(`/api/v1/questions/${state.canonicalQuestionId}/state`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ is_wrong: true }),
    });
    if (!alive || current !== revision) return;
    for (const [id, value] of Object.entries(questionStates.value)) {
      if (value.canonicalQuestionId === state.canonicalQuestionId) {
        questionStates.value[Number(id)] = { ...value, is_wrong: true };
      }
    }
  } catch (error) {
    if (alive && current === revision) reviewActionError.value = errorText(error);
  } finally {
    if (alive && current === revision) {
      markingQuestionIds.value = markingQuestionIds.value.filter((id) => id !== questionId);
    }
  }
}

function answerExported(): void {
  if (record.value) void load();
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
      <p v-if="reviewActionError" role="alert">{{ reviewActionError }}</p>
      <MockInterviewSummary v-if="safeSummary" :summary="safeSummary" :question-states="Object.fromEntries(Object.entries(questionStates).map(([id, state]) => [id, { is_wrong: state.is_wrong, writable: state.writable }]))" :marking-question-ids="markingQuestionIds" @mark-wrong="markQuestionWrong" />
      <section v-else class="empty-state">本次记录未生成 AI 总结，完整对话仍保存在下方。</section>
      <MockInterviewReviewPanel :record-id="record.id" :turns="savedTurns" @exported="answerExported" />
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
