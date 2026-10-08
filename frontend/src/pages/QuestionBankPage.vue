<script setup lang="ts">
import { onMounted, ref } from "vue";
import { RouterLink } from "vue-router";
import { ApiError, request } from "../api/client";
import QuestionForm from "../components/QuestionForm.vue";

interface TaxonomyItem {
  id: number;
  name: string;
  is_active: boolean;
}

interface QuestionItem {
  id: number;
  text: string;
  answer_type: string | null;
  difficulty: string | null;
  archived_at: string | null;
  topics: TaxonomyItem[];
  tags: TaxonomyItem[];
  state: { is_favorite: boolean; is_wrong: boolean };
}

const questions = ref<QuestionItem[]>([]);
const topics = ref<TaxonomyItem[]>([]);
const tags = ref<TaxonomyItem[]>([]);
const selectedTopicIds = ref<number[]>([]);
const selectedTagIds = ref<number[]>([]);
const searchQuery = ref("");
const includeArchived = ref(false);
const favoriteOnly = ref(false);
const wrongOnly = ref(false);
const errorMessage = ref("");
const loading = ref(false);
const showForm = ref(false);

function displayError(error: unknown): string {
  if (error instanceof ApiError) {
    const details = Object.values(error.fields);
    return details.length ? `${error.message}: ${details.join("；")}` : error.message;
  }
  return "请求失败，请稍后重试。";
}

async function loadTaxonomy(): Promise<void> {
  const [topicRows, tagRows] = await Promise.all([
    request<TaxonomyItem[]>("/api/v1/topics"),
    request<TaxonomyItem[]>("/api/v1/tags"),
  ]);
  topics.value = topicRows;
  tags.value = tagRows;
}

async function loadQuestions(): Promise<void> {
  loading.value = true;
  errorMessage.value = "";
  const params = new URLSearchParams();
  if (searchQuery.value.trim()) params.set("q", searchQuery.value.trim());
  if (includeArchived.value) params.set("include_archived", "true");
  if (favoriteOnly.value) params.set("is_favorite", "true");
  if (wrongOnly.value) params.set("is_wrong", "true");
  for (const id of selectedTopicIds.value) params.append("topic_ids", String(id));
  for (const id of selectedTagIds.value) params.append("tag_ids", String(id));
  try {
    const queryString = params.toString();
    const query = queryString ? `?${queryString}` : "";
    questions.value = await request<QuestionItem[]>(`/api/v1/questions${query}`);
  } catch (error) {
    errorMessage.value = displayError(error);
  } finally {
    loading.value = false;
  }
}

async function createQuestion(payload: {
  text: string;
  answer_type: string | null;
  difficulty: string | null;
  topic_ids: number[];
  tag_ids: number[];
}): Promise<void> {
  errorMessage.value = "";
  try {
    await request<QuestionItem>("/api/v1/questions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    showForm.value = false;
    await loadQuestions();
  } catch (error) {
    errorMessage.value = displayError(error);
  }
}

async function archiveQuestion(question: QuestionItem): Promise<void> {
  errorMessage.value = "";
  try {
    await request<QuestionItem>(`/api/v1/questions/${question.id}/archive`, { method: "POST" });
    await loadQuestions();
  } catch (error) {
    errorMessage.value = displayError(error);
  }
}

onMounted(async () => {
  try {
    await loadTaxonomy();
    await loadQuestions();
  } catch (error) {
    errorMessage.value = displayError(error);
  }
});
</script>

<template>
  <section aria-labelledby="question-bank-title">
    <h2 id="question-bank-title">Agent 面试题库</h2>
    <p v-if="errorMessage" role="alert">{{ errorMessage }}</p>

    <form role="search" aria-label="题库搜索" @submit.prevent="loadQuestions">
      <input v-model="searchQuery" aria-label="搜索题目" />
      <button type="submit" aria-label="搜索题库">搜索</button>
    </form>

    <div aria-label="题库筛选">
      <label>
        Topic
        <select v-model="selectedTopicIds" multiple aria-label="按 Topic 筛选">
          <option v-for="topic in topics.filter((item) => item.is_active)" :key="topic.id" :value="topic.id">
            {{ topic.name }}
          </option>
        </select>
      </label>
      <label>
        Tag
        <select v-model="selectedTagIds" multiple aria-label="按 Tag 筛选">
          <option v-for="tag in tags.filter((item) => item.is_active)" :key="tag.id" :value="tag.id">
            {{ tag.name }}
          </option>
        </select>
      </label>
      <label>
        <input v-model="includeArchived" type="checkbox" aria-label="显示归档题目" />
        显示归档题目
      </label>
      <label>
        <input v-model="favoriteOnly" type="checkbox" aria-label="仅显示收藏题目" />
        仅收藏
      </label>
      <label>
        <input v-model="wrongOnly" type="checkbox" aria-label="仅显示错题" />
        仅错题
      </label>
      <button type="button" @click="loadQuestions">筛选</button>
    </div>

    <button type="button" aria-label="切换新增题目表单" @click="showForm = !showForm">
      {{ showForm ? "取消新增" : "新增题目" }}
    </button>
    <QuestionForm v-if="showForm" :topics="topics" :tags="tags" @save="createQuestion" />

    <p v-if="loading">正在加载题目…</p>
    <p v-else-if="questions.length === 0">当前没有题目</p>
    <ul aria-label="题目列表">
      <li v-for="question in questions" :key="question.id">
        <RouterLink :to="`/questions/${question.id}`">{{ question.text }}</RouterLink>
        <span v-if="question.archived_at">已归档</span>
        <span v-for="topic in question.topics" :key="`topic-${topic.id}`">
          {{ topic.name }}<template v-if="!topic.is_active">（停用）</template>
        </span>
        <span v-for="tag in question.tags" :key="`tag-${tag.id}`">
          {{ tag.name }}<template v-if="!tag.is_active">（停用）</template>
        </span>
        <span v-if="question.state.is_favorite">已收藏</span>
        <span v-if="question.state.is_wrong">错题</span>
        <button
          v-if="!question.archived_at"
          type="button"
          :aria-label="`归档题目 ${question.id}`"
          @click="archiveQuestion(question)"
        >
          归档
        </button>
      </li>
    </ul>
  </section>
</template>
