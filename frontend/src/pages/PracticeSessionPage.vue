<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
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
  loading.value = true;
  errorMessage.value = "";
  try {
    practiceSession.value = await request<PracticeSession>(
      `/api/v1/practice-sessions/${sessionId.value}`,
    );
  } catch (error) {
    errorMessage.value = displayError(error);
  } finally {
    loading.value = false;
  }
}

async function skipCurrentItem(): Promise<void> {
  if (!currentItem.value || skipping.value || reviewing.value) return;
  errorMessage.value = "";
  skipping.value = true;
  try {
    await request(`/api/v1/session-items/${currentItem.value.id}/skip`, { method: "POST" });
    answerDraft.value = "";
    await loadSession();
  } catch (error) {
    errorMessage.value = displayError(error);
  } finally {
    skipping.value = false;
  }
}

async function recordRating(reviewRating: string): Promise<void> {
  if (!currentItem.value || skipping.value || reviewing.value) return;
  errorMessage.value = "";
  reviewing.value = true;
  try {
    await request(`/api/v1/session-items/${currentItem.value.id}/review`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ review_rating: reviewRating }),
    });
    answerDraft.value = "";
    await loadSession();
  } catch (error) {
    errorMessage.value = displayError(error);
  } finally {
    reviewing.value = false;
  }
}

function rewriteDraft(): void {
  answerDraft.value = "";
}

onMounted(loadSession);
</script>

<template>
  <section aria-labelledby="practice-session-title">
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
      <h2 id="practice-session-title">练习会话 #{{ practiceSession.id }}</h2>
      <p v-if="practiceSession.completed_at">本次练习已完成</p>
      <template v-else-if="currentItem">
        <p>第 {{ currentItem.ordinal }} 题</p>
        <h3>{{ currentItem.question.text }}</h3>
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

      <ol aria-label="练习题目顺序">
        <li v-for="item in practiceSession.items" :key="item.id">
          <span>{{ item.ordinal }}. {{ item.question.text }}</span>
          <span>{{ item.status }}</span>
        </li>
      </ol>
    </template>
  </section>
</template>
