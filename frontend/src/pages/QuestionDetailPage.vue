<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { RouterLink, useRoute } from "vue-router";
import { ApiError, request } from "../api/client";
import QuestionHistory from "../components/QuestionHistory.vue";
import type { CanonicalHistory, PracticeReviewItem } from "../api/question-history";
import QuestionRelationReview from "../components/QuestionRelationReview.vue";
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
  canonical_question_id: number | null;
  archived_at: string | null;
  topics: Array<TaxonomyItem & { parent_id: number | null; slug: string }>;
  tags: TaxonomyItem[];
  state: { is_favorite: boolean; is_wrong: boolean; user_note: string | null };
}

interface QuestionFormPayload {
  text: string;
  answer_type: string | null;
  difficulty: string | null;
  topic_ids: number[];
  tag_ids: number[];
}

const route = useRoute();
const question = ref<QuestionDetail | null>(null);
const reviews = ref<PracticeReviewItem[]>([]);
const history = ref<CanonicalHistory | null>(null);
const historyLoading = ref(false);
const historyLoadError = ref("");
const reviewRatingDrafts = ref<Record<number, PracticeReviewItem["review_rating"]>>({});
const topics = ref<TaxonomyItem[]>([]);
const tags = ref<TaxonomyItem[]>([]);
const errorMessage = ref("");
const loading = ref(true);

const questionId = computed(() => Number(route.params.id));
let questionLoadRevision = 0;
let historyLoadRevision = 0;
const readOnly = computed(() => question.value?.status === 'merged');

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

function sameIds(left: number[], right: number[]): boolean {
  return left.length === right.length && left.every((id) => right.includes(id));
}

function isCurrentQuestionRequest(requestedQuestionId: number, requestRevision: number): boolean {
  return (
    questionId.value === requestedQuestionId &&
    questionLoadRevision === requestRevision &&
    question.value?.id === requestedQuestionId
  );
}

async function loadQuestion(): Promise<void> {
  const requestedQuestionId = questionId.value;
  const requestRevision = ++questionLoadRevision;
  historyLoadRevision += 1;
  history.value = null;
  historyLoading.value = false;
  historyLoadError.value = "";
  question.value = null;
  reviews.value = [];
  topics.value = [];
  tags.value = [];
  reviewRatingDrafts.value = {};
  loading.value = true;
  errorMessage.value = "";
  try {
    const [questionResult, topicResult, tagResult] = await Promise.all([
      request<QuestionDetail>(`/api/v1/questions/${requestedQuestionId}`),
      request<TaxonomyItem[]>("/api/v1/topics"),
      request<TaxonomyItem[]>("/api/v1/tags"),
    ]);
    if (requestRevision !== questionLoadRevision || requestedQuestionId !== questionId.value) return;
    question.value = questionResult;
    topics.value = mergeHistoricalItems(topicResult, questionResult.topics);
    tags.value = mergeHistoricalItems(tagResult, questionResult.tags);
    void loadHistory(requestedQuestionId);
  } catch (error) {
    if (requestRevision === questionLoadRevision && requestedQuestionId === questionId.value) {
      errorMessage.value = displayError(error);
    }
  } finally {
    if (requestRevision === questionLoadRevision && requestedQuestionId === questionId.value) {
      loading.value = false;
    }
  }
}

async function loadHistory(requestedQuestionId = questionId.value): Promise<void> {
  const requestRevision = ++historyLoadRevision;
  historyLoading.value = true;
  historyLoadError.value = "";
  try {
    const result = await request<CanonicalHistory>(`/api/v1/questions/${requestedQuestionId}/history`);
    if (requestRevision !== historyLoadRevision || requestedQuestionId !== questionId.value) return;
    history.value = result;
    reviews.value = result.practice_reviews;
    reviewRatingDrafts.value = Object.fromEntries(result.practice_reviews.map(review => [review.id, review.review_rating]));
  } catch (error) {
    if (requestRevision === historyLoadRevision && requestedQuestionId === questionId.value) {
      historyLoadError.value = displayError(error);
    }
  } finally {
    if (requestRevision === historyLoadRevision && requestedQuestionId === questionId.value) {
      historyLoading.value = false;
    }
  }
}

async function update(payload: QuestionFormPayload): Promise<void> {
  const currentQuestion = question.value;
  if (!currentQuestion || readOnly.value) return;
  const requestedQuestionId = currentQuestion.id;
  const requestRevision = questionLoadRevision;

  const patch: Partial<QuestionFormPayload> = {
    text: payload.text,
    answer_type: payload.answer_type,
    difficulty: payload.difficulty,
  };
  const currentTopicIds = currentQuestion.topics.map((item) => item.id);
  const currentTagIds = currentQuestion.tags.map((item) => item.id);
  if (!sameIds(payload.topic_ids, currentTopicIds)) patch.topic_ids = payload.topic_ids;
  if (!sameIds(payload.tag_ids, currentTagIds)) patch.tag_ids = payload.tag_ids;

  errorMessage.value = "";
  try {
    const updated = await request<QuestionDetail>(`/api/v1/questions/${requestedQuestionId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    });
    if (!isCurrentQuestionRequest(requestedQuestionId, requestRevision)) return;
    question.value = updated;
  } catch (error) {
    if (isCurrentQuestionRequest(requestedQuestionId, requestRevision)) {
      errorMessage.value = displayError(error);
    }
  }
}

async function patchState(field: "is_favorite" | "is_wrong"): Promise<void> {
  const currentQuestion = question.value;
  if (!currentQuestion || readOnly.value) return;
  const requestedQuestionId = currentQuestion.id;
  const requestRevision = questionLoadRevision;
  const nextValue = !currentQuestion.state[field];
  errorMessage.value = "";
  try {
    const state = await request<QuestionDetail["state"]>(
      `/api/v1/questions/${requestedQuestionId}/state`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ [field]: nextValue }),
      },
    );
    const activeQuestion = question.value;
    if (!isCurrentQuestionRequest(requestedQuestionId, requestRevision) || !activeQuestion) return;
    activeQuestion.state = state;
  } catch (error) {
    if (isCurrentQuestionRequest(requestedQuestionId, requestRevision)) {
      errorMessage.value = displayError(error);
    }
  }
}

async function archiveQuestion(): Promise<void> {
  const currentQuestion = question.value;
  if (!currentQuestion || readOnly.value) return;
  const requestedQuestionId = currentQuestion.id;
  const requestRevision = questionLoadRevision;
  errorMessage.value = "";
  try {
    const archived = await request<QuestionDetail>(`/api/v1/questions/${requestedQuestionId}/archive`, {
      method: "POST",
    });
    if (!isCurrentQuestionRequest(requestedQuestionId, requestRevision)) return;
    question.value = archived;
  } catch (error) {
    if (isCurrentQuestionRequest(requestedQuestionId, requestRevision)) {
      errorMessage.value = displayError(error);
    }
  }
}

async function correctReview(review: PracticeReviewItem): Promise<void> {
  const currentQuestion = question.value;
  if (!currentQuestion || !history.value?.member_question_ids.includes(review.question_id)) return;
  const requestedQuestionId = currentQuestion.id;
  const requestRevision = questionLoadRevision;
  const reviewId = review.id;
  if (!reviews.value.some((item) => item.id === reviewId)) return;
  const reviewRating = reviewRatingDrafts.value[review.id];
  if (!reviewRating || reviewRating === review.review_rating) return;
  errorMessage.value = "";
  try {
    const updated = await request<PracticeReviewItem>(`/api/v1/practice-reviews/${reviewId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ review_rating: reviewRating }),
    });
    if (
      !isCurrentQuestionRequest(requestedQuestionId, requestRevision) ||
      updated.question_id !== review.question_id ||
      updated.id !== reviewId ||
      !reviews.value.some((item) => item.id === reviewId)
    ) return;
    reviews.value = reviews.value.map((item) => (item.id === reviewId ? updated : item));
    if (history.value) history.value.practice_reviews = reviews.value;
    reviewRatingDrafts.value[updated.id] = updated.review_rating;
  } catch (error) {
    if (isCurrentQuestionRequest(requestedQuestionId, requestRevision)) {
      errorMessage.value = displayError(error);
    }
  }
}

watch(questionId, () => void loadQuestion(), { immediate: true });
</script>

<template>
  <section aria-labelledby="question-detail-title" class="question-detail">
    <p v-if="loading">正在加载题目…</p>
    <template v-if="errorMessage">
      <p role="alert">{{ errorMessage }}</p>
      <button
        v-if="!question"
        type="button"
        aria-label="重试加载题目详情"
        @click="loadQuestion"
      >
        重试加载
      </button>
    </template>
    <template v-if="!loading && question">
      <header class="page-heading"><div><span class="eyebrow">Question workspace · #{{ question.id }}</span><h2 id="question-detail-title">题目详情</h2></div><RouterLink to="/">返回题库</RouterLink></header>
      <p v-if="question.archived_at">已归档</p>
      <p v-else class="badge">{{ readOnly ? "归并历史" : "正式题目" }}</p>
      <p class="question-reading" aria-label="当前题目正文">{{ question.text }}</p>
      <p v-if="readOnly" role="status">此题已归并，原始内容只读。<RouterLink :to="`/questions/${question.canonical_question_id}`">打开规范题 #{{ question.canonical_question_id }}</RouterLink></p>
      <p v-else class="group-scope">取消收藏和取消错题标记作用于整个归并组。</p>
      <TopicTagPicker :topics="question.topics" :tags="question.tags" />
      <button v-if="!readOnly" type="button" :aria-label="question.state.is_favorite ? '取消收藏' : '收藏'" @click="patchState('is_favorite')">
        {{ question.state.is_favorite ? "取消收藏" : "收藏" }}
      </button>
      <button v-if="!readOnly" type="button" :aria-label="question.state.is_wrong ? '取消错题标记' : '标记错题'" @click="patchState('is_wrong')">
        {{ question.state.is_wrong ? "取消错题标记" : "标记错题" }}
      </button>
      <button v-if="!readOnly && !question.archived_at" type="button" :disabled="historyLoading || !!historyLoadError || (history?.member_question_ids.length ?? 0) > 1" @click="archiveQuestion">归档</button>
      <p v-if="history && history.member_question_ids.length > 1" class="helper">归并组暂不支持整组归档，原始题目与历史继续保留。</p>
      <details v-if="!readOnly" class="editor-panel"><summary>编辑题目与分类</summary>
      <QuestionForm
        :initial-text="question.text"
        :initial-answer-type="question.answer_type"
        :initial-difficulty="question.difficulty"
        :initial-topic-ids="question.topics.map((item) => item.id)"
        :initial-tag-ids="question.tags.map((item) => item.id)"
        :topics="topics"
        :tags="tags"
        @save="update"
      /></details>
      <QuestionRelationReview
        v-if="question.status === 'active' && !question.archived_at"
        :key="question.id"
        :question-id="question.id"
        :text="question.text"
      />
      <section aria-label="归并组历史" class="group-history">
        <p v-if="historyLoading" role="status">正在加载题目历史…</p>
        <template v-else-if="historyLoadError">
          <p role="alert" aria-label="题目历史加载失败">题目历史加载失败：{{ historyLoadError }}</p>
          <button type="button" aria-label="重试加载题目历史" @click="loadHistory()">重新加载历史</button>
        </template>
        <QuestionHistory v-else-if="history" :history="history" :rating-drafts="reviewRatingDrafts"
          @rating-change="(id, rating) => reviewRatingDrafts[id] = rating" @correct-review="correctReview" />
      </section>
    </template>
  </section>
</template>
