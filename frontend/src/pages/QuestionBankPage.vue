<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
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
  canonical_member_count?: number | null;
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
let questionListRevision = 0;
const filterCount = computed(() => selectedTopicIds.value.length + selectedTagIds.value.length + Number(includeArchived.value) + Number(favoriteOnly.value) + Number(wrongOnly.value));
function clearFilters() {searchQuery.value='';selectedTopicIds.value=[];selectedTagIds.value=[];includeArchived.value=false;favoriteOnly.value=false;wrongOnly.value=false;void loadQuestions();}

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
  const revision = ++questionListRevision;
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
    const rows = await request<QuestionItem[]>(`/api/v1/questions${query}`);
    if (revision === questionListRevision) questions.value = rows;
  } catch (error) {
    if (revision === questionListRevision) errorMessage.value = displayError(error);
  } finally {
    if (revision === questionListRevision) loading.value = false;
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
  if ((question.canonical_member_count ?? 1) > 1) return;
  errorMessage.value = "";
  try {
    await request<QuestionItem>(`/api/v1/questions/${question.id}/archive`, { method: "POST" });
    await loadQuestions();
  } catch (error) {
    errorMessage.value = displayError(error);
  }
}

async function reloadWorkspace() {
  errorMessage.value = "";
  try {
    await loadTaxonomy();
    await loadQuestions();
  } catch (error) {
    errorMessage.value = displayError(error);
  }
}

onMounted(reloadWorkspace);
</script>

<template>
  <section aria-labelledby="question-bank-title" class="question-bank">
    <header class="page-heading"><div><span class="eyebrow">Knowledge library</span><h2 id="question-bank-title">Agent 面试题库</h2><p>整理技术问题，保留来源证据，让每一次练习有据可循。</p></div>
      <button type="button" class="primary" aria-label="切换新增题目表单" @click="showForm = !showForm">{{ showForm ? "取消新增" : "新增题目" }}</button>
    </header>
    <div v-if="errorMessage"><p role="alert">{{ errorMessage }}</p><button type="button" aria-label="重试加载题库" @click="reloadWorkspace">重新加载题库</button></div>
    <section v-if="showForm" class="panel new-question" aria-label="新增题目"><h3>新增题目</h3><QuestionForm :topics="topics" :tags="tags" @save="createQuestion" /></section>
    <form role="search" aria-label="题库搜索" class="search-bar" @submit.prevent="loadQuestions">
      <input v-model="searchQuery" aria-label="搜索题目" placeholder="搜索题干、技术概念或归并前的历史正文…" type="search" />
      <button type="submit" aria-label="搜索题库">搜索</button>
    </form>
    <details class="filter-panel"><summary>筛选题库 <span v-if="filterCount" class="badge accent">{{ filterCount }}</span> <span class="muted">· Topic、Tag、收藏与错题</span></summary>
      <div aria-label="题库筛选" class="filter-grid">
        <label>Topic<select v-model="selectedTopicIds" multiple aria-label="按 Topic 筛选"><option v-for="topic in topics.filter(item => item.is_active)" :key="topic.id" :value="topic.id">{{ topic.name }}</option></select><small class="helper">按 Ctrl / ⌘ 可选择多个分类</small></label>
        <label>Tag<select v-model="selectedTagIds" multiple aria-label="按 Tag 筛选"><option v-for="tag in tags.filter(item => item.is_active)" :key="tag.id" :value="tag.id">{{ tag.name }}</option></select><small class="helper">分类以规范题最终选择为准</small></label>
        <div class="filter-toggles"><label><input v-model="includeArchived" type="checkbox" aria-label="显示归档题目" />显示归档题目</label><label><input v-model="favoriteOnly" type="checkbox" aria-label="仅显示收藏题目" />仅收藏</label><label><input v-model="wrongOnly" type="checkbox" aria-label="仅显示错题" />仅错题</label><div class="action-row"><button type="button" @click="loadQuestions">筛选</button><button type="button" @click="clearFilters">清空条件</button></div></div>
      </div>
    </details>
    <p v-if="loading" role="status">正在加载题目…</p>
    <template v-else-if="!errorMessage">
      <div class="results-heading"><span aria-label="题库结果数量">{{ questions.length }} 道题目</span><span>规范题去重 · 保留历史</span></div>
      <p v-if="!questions.length" class="empty-state">当前没有题目<br /><span class="helper">尝试调整搜索条件，或新增一道题目。</span></p>
      <ul v-else aria-label="题目列表" class="question-list">
        <li v-for="question in questions" :key="question.id" class="question-row">
          <div class="question-row-content"><RouterLink :to="`/questions/${question.id}`" class="question-title">{{ question.text }}</RouterLink>
            <div class="question-row-meta"><span class="mono">#{{ question.id }}</span><span v-if="(question.canonical_member_count ?? 1) > 1" class="badge accent">规范题 · {{ question.canonical_member_count }} 道原题</span><span v-if="question.archived_at" class="badge">已归档</span>
              <span v-for="topic in question.topics" :key="`topic-${topic.id}`" class="badge accent">{{ topic.name }}<template v-if="!topic.is_active">（停用）</template></span>
              <span v-for="tag in question.tags" :key="`tag-${tag.id}`" class="badge">{{ tag.name }}<template v-if="!tag.is_active">（停用）</template></span>
              <span v-if="question.state.is_favorite" class="badge success">已收藏</span><span v-if="question.state.is_wrong" class="badge warning">错题</span>
            </div>
          </div>
          <div class="row-archive"><button v-if="!question.archived_at" type="button" :aria-label="`归档题目 ${question.id}`" :disabled="(question.canonical_member_count ?? 1) > 1" @click="archiveQuestion(question)">归档</button><small v-if="(question.canonical_member_count ?? 1) > 1" class="helper">归并组暂不支持整组归档</small></div>
        </li>
      </ul>
    </template>
  </section>
</template>
