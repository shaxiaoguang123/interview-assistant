<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import { ApiError, request } from "../api/client";
import QuestionForm from "../components/QuestionForm.vue";
import TopicTagPicker from "../components/TopicTagPicker.vue";

interface TaxonomyItem {
  id: number;
  name: string;
  is_active: boolean;
}

interface QuestionDetail {
  id: number;
  text: string;
  answer_type: string | null;
  difficulty: string | null;
  status: string;
  archived_at: string | null;
  topics: Array<TaxonomyItem & { parent_id: number | null; slug: string }>;
  tags: TaxonomyItem[];
  state: { is_favorite: boolean; is_wrong: boolean; user_note: string | null };
}

const route = useRoute();
const question = ref<QuestionDetail | null>(null);
const topics = ref<TaxonomyItem[]>([]);
const tags = ref<TaxonomyItem[]>([]);
const errorMessage = ref("");
const loading = ref(true);

const questionId = computed(() => Number(route.params.id));

function displayError(error: unknown): string {
  if (error instanceof ApiError) {
    const details = Object.values(error.fields);
    return details.length ? `${error.message}: ${details.join("；")}` : error.message;
  }
  return "请求失败，请稍后重试。";
}

function mergeHistoricalItems<T extends TaxonomyItem>(activeItems: T[], linkedItems: T[]): T[] {
  const byId = new Map(activeItems.map((item) => [item.id, item]));
  for (const item of linkedItems) if (!byId.has(item.id)) byId.set(item.id, item);
  return [...byId.values()];
}

async function loadQuestion(): Promise<void> {
  loading.value = true;
  errorMessage.value = "";
  try {
    const [questionResult, topicResult, tagResult] = await Promise.all([
      request<QuestionDetail>(`/api/v1/questions/${questionId.value}`),
      request<TaxonomyItem[]>("/api/v1/topics"),
      request<TaxonomyItem[]>("/api/v1/tags"),
    ]);
    question.value = questionResult;
    topics.value = mergeHistoricalItems(topicResult, questionResult.topics);
    tags.value = mergeHistoricalItems(tagResult, questionResult.tags);
  } catch (error) {
    errorMessage.value = displayError(error);
  } finally {
    loading.value = false;
  }
}

async function update(payload: {
  text: string;
  answer_type: string | null;
  difficulty: string | null;
  topic_ids: number[];
  tag_ids: number[];
}): Promise<void> {
  errorMessage.value = "";
  try {
    question.value = await request<QuestionDetail>(`/api/v1/questions/${questionId.value}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  } catch (error) {
    errorMessage.value = displayError(error);
  }
}

async function patchState(field: "is_favorite" | "is_wrong"): Promise<void> {
  if (!question.value) return;
  errorMessage.value = "";
  try {
    const state = await request<QuestionDetail["state"]>(
      `/api/v1/questions/${questionId.value}/state`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ [field]: !question.value.state[field] }),
      },
    );
    question.value.state = state;
  } catch (error) {
    errorMessage.value = displayError(error);
  }
}

async function archiveQuestion(): Promise<void> {
  errorMessage.value = "";
  try {
    question.value = await request<QuestionDetail>(`/api/v1/questions/${questionId.value}/archive`, {
      method: "POST",
    });
  } catch (error) {
    errorMessage.value = displayError(error);
  }
}

onMounted(loadQuestion);
</script>

<template>
  <section aria-labelledby="question-detail-title">
    <p v-if="loading">正在加载题目…</p>
    <p v-else-if="errorMessage" role="alert">{{ errorMessage }}</p>
    <template v-else-if="question">
      <h2 id="question-detail-title">题目详情</h2>
      <p v-if="question.archived_at">已归档</p>
      <p v-else>状态：{{ question.status }}</p>
      <TopicTagPicker :topics="question.topics" :tags="question.tags" />
      <button type="button" @click="patchState('is_favorite')">
        {{ question.state.is_favorite ? "取消收藏" : "收藏" }}
      </button>
      <button type="button" @click="patchState('is_wrong')">
        {{ question.state.is_wrong ? "取消错题标记" : "标记错题" }}
      </button>
      <button v-if="!question.archived_at" type="button" @click="archiveQuestion">归档</button>
      <QuestionForm
        :initial-text="question.text"
        :initial-answer-type="question.answer_type"
        :initial-difficulty="question.difficulty"
        :initial-topic-ids="question.topics.map((item) => item.id)"
        :initial-tag-ids="question.tags.map((item) => item.id)"
        :topics="topics"
        :tags="tags"
        @save="update"
      />
    </template>
  </section>
</template>
