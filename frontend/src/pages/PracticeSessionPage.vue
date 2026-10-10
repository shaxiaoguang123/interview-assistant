<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { ApiError, request } from "../api/client";
import PracticeRating from "../components/PracticeRating.vue";

interface SessionItem {
  id: number;
  question_id: number;
  ordinal: number;
  status: "shown" | "completed" | "skipped";
  question: { id: number; text: string; status: string; archived_at: string | null };
}

interface PracticeSession {
  id: number;
  mode: string;
  selector_version: string;
  selection_seed: number | null;
  started_at: string;
  completed_at: string | null;
  items: SessionItem[];
}

const route = useRoute();
const practiceSession = ref<PracticeSession | null>(null);
const answerDraft = ref("");
const errorMessage = ref("");
const loading = ref(true);
const skipping = ref(false);
const reviewing = ref(false);
const sessionId = computed(() => Number(route.params.id));
let loadRevision = 0;
const completedCount = computed(() => practiceSession.value?.items.filter(i => i.status !== 'shown').length ?? 0);
function currentRequest(id: number, revision: number) { return sessionId.value === id && loadRevision === revision; }
const currentItem = computed(
  () => practiceSession.value?.items.find((item) => item.status === "shown") ?? null,
);

function displayError(error: unknown): string {
  if (error instanceof ApiError) {
    const details = Object.values(error.fields);
    return details.length ? `${error.message}: ${details.join("；")}` : error.message;
  }
  return "请求失败，请稍后重试。";
}

async function loadSession(): Promise<void> {
  const id = sessionId.value;
  const revision = ++loadRevision;
  practiceSession.value = null;
  answerDraft.value = "";
  skipping.value = false;
  reviewing.value = false;
  loading.value = true;
  errorMessage.value = "";
  try {
    const result = await request<PracticeSession>(`/api/v1/practice-sessions/${id}`);
    if (currentRequest(id, revision)) practiceSession.value = result;
  } catch (error) {
    if (currentRequest(id, revision)) errorMessage.value = displayError(error);
  } finally {
    if (currentRequest(id, revision)) loading.value = false;
  }
}

async function skipCurrentItem(): Promise<void> {
  if (!currentItem.value || skipping.value || reviewing.value) return;
  const id = sessionId.value;
  const revision = loadRevision;
  const itemId = currentItem.value.id;
  errorMessage.value = "";
  skipping.value = true;
  try {
    await request(`/api/v1/session-items/${itemId}/skip`, { method: "POST" });
    if (!currentRequest(id, revision)) return;
    answerDraft.value = "";
    await loadSession();
  } catch (error) {
    if (currentRequest(id, revision)) errorMessage.value = displayError(error);
  } finally {
    if (currentRequest(id, revision)) skipping.value = false;
  }
}

async function recordRating(reviewRating: string): Promise<void> {
  if (!currentItem.value || skipping.value || reviewing.value) return;
  const id = sessionId.value;
  const revision = loadRevision;
  const itemId = currentItem.value.id;
  errorMessage.value = "";
  reviewing.value = true;
  try {
    await request(`/api/v1/session-items/${itemId}/review`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ review_rating: reviewRating }),
    });
    if (!currentRequest(id, revision)) return;
    answerDraft.value = "";
    await loadSession();
  } catch (error) {
    if (currentRequest(id, revision)) errorMessage.value = displayError(error);
  } finally {
    if (currentRequest(id, revision)) reviewing.value = false;
  }
}

function rewriteDraft(): void {
  answerDraft.value = "";
}

watch(sessionId, () => void loadSession(), {immediate:true});
</script>

<template>
  <section aria-labelledby="practice-session-title" class="practice-session">
    <p v-if="loading">正在加载练习…</p>
    <template v-if="errorMessage">
      <p role="alert">{{ errorMessage }}</p>
      <button
        v-if="!practiceSession"
        type="button"
        aria-label="重试加载练习"
        @click="loadSession"
      >
        重试加载
      </button>
    </template>
    <template v-if="!loading && practiceSession">
      <header class="page-heading"><div><span class="eyebrow">Practice room</span><h2 id="practice-session-title">练习会话 #{{ practiceSession.id }}</h2><p>完成 {{ completedCount }} / {{ practiceSession.items.length }} · 掌握程度由你自己判断</p></div></header>
      <progress aria-label="练习完成进度" :value="completedCount" :max="Math.max(1, practiceSession.items.length)" />
      <div class="practice-workspace"><div class="practice-question">
      <p v-if="practiceSession.completed_at">本次练习已完成</p>
      <template v-else-if="currentItem">
        <p>第 {{ currentItem.ordinal }} 题</p>
        <h3>{{ currentItem.question.text }}</h3>
        <p v-if="currentItem.question.status === 'merged'" class="helper">这是归并前的历史题目，仍可完成本次练习；记录保留原题 #{{ currentItem.question_id }}。</p>
        <p v-if="currentItem.question.archived_at">此题已归档；仍可完成当前练习。</p>
        <label>
          临时回答
          <textarea v-model="answerDraft" aria-label="临时回答" />
        </label>
        <button type="button" @click="rewriteDraft">重新回答</button>
        <PracticeRating :disabled="reviewing || skipping" @rate="recordRating" />
        <button type="button" :disabled="skipping || reviewing" @click="skipCurrentItem">
          {{ skipping ? "正在跳过…" : "跳过此题" }}
        </button>
      </template>
      <p v-else>当前会话没有待练习题目。</p>

      </div><aside aria-label="本次练习队列"><h3>本次题目</h3><ol aria-label="练习题目顺序" class="practice-queue">
        <li v-for="item in practiceSession.items" :key="item.id">
          <span>{{ item.ordinal }}. {{ item.question.text }}</span>
          <span class="muted">{{ {shown:"待练习",completed:"已完成",skipped:"已跳过"}[item.status] }} · 原题 #{{ item.question_id }}</span>
        </li>
      </ol></aside></div>
    </template>
  </section>
</template>
