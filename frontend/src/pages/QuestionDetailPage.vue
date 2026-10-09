<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { ApiError, request } from "../api/client";
import SourceImageViewer from "../components/SourceImageViewer.vue";
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
  archived_at: string | null;
  topics: Array<TaxonomyItem & { parent_id: number | null; slug: string }>;
  tags: TaxonomyItem[];
  state: { is_favorite: boolean; is_wrong: boolean; user_note: string | null };
}

interface PracticeReviewItem {
  id: number;
  question_id: number;
  session_item_id: number;
  review_rating: "dont_know" | "vague" | "basic" | "proficient";
  reviewed_at: string;
  created_at: string;
  updated_at: string;
}

interface QuestionSourceItem {
  question_source_id: number;
  source_asset_id: number;
  source_title: string | null;
  original_filename: string | null;
  display_width: number;
  display_height: number;
  source_text_snapshot: string;
  raw_ocr_text_snapshot: string;
  locator_json: { x: number; y: number; width: number; height: number };
  locator_correction_json: { x: number; y: number; width: number; height: number } | null;
  ocr_block_ids: string[];
  ocr_blocks: Array<{
    id: string;
    text: string;
    bbox: { x: number; y: number; width: number; height: number };
    reading_order: number;
    confidence: number | null;
  }>;
  original_image_url: string;
  display_image_url: string;
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
const sources = ref<QuestionSourceItem[]>([]);
const sourceLoading = ref(false);
const sourceLoadError = ref("");
const selectedSourceId = ref<number | null>(null);
const reviewRatingDrafts = ref<Record<number, PracticeReviewItem["review_rating"]>>({});
const topics = ref<TaxonomyItem[]>([]);
const tags = ref<TaxonomyItem[]>([]);
const errorMessage = ref("");
const loading = ref(true);

const questionId = computed(() => Number(route.params.id));
let questionLoadRevision = 0;
let sourceLoadRevision = 0;
const selectedSource = computed(
  () => sources.value.find((source) => source.question_source_id === selectedSourceId.value) ?? sources.value[0] ?? null,
);

function displayError(error: unknown): string {
  if (error instanceof ApiError) {
    const details = Object.values(error.fields);
    return details.length ? `${error.message}: ${details.join("；")}` : error.message;
  }
  return "请求失败，请稍后重试。";
}

function ratingLabel(rating: PracticeReviewItem["review_rating"]): string {
  return {
    dont_know: "不会",
    vague: "模糊",
    basic: "基本会",
    proficient: "熟练",
  }[rating];
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
  sourceLoadRevision += 1;
  sources.value = [];
  selectedSourceId.value = null;
  sourceLoading.value = false;
  sourceLoadError.value = "";
  question.value = null;
  reviews.value = [];
  topics.value = [];
  tags.value = [];
  reviewRatingDrafts.value = {};
  loading.value = true;
  errorMessage.value = "";
  try {
    const [questionResult, topicResult, tagResult, reviewRows] = await Promise.all([
      request<QuestionDetail>(`/api/v1/questions/${requestedQuestionId}`),
      request<TaxonomyItem[]>("/api/v1/topics"),
      request<TaxonomyItem[]>("/api/v1/tags"),
      request<PracticeReviewItem[]>(`/api/v1/questions/${requestedQuestionId}/practice-reviews`),
    ]);
    if (requestRevision !== questionLoadRevision || requestedQuestionId !== questionId.value) return;
    question.value = questionResult;
    topics.value = mergeHistoricalItems(topicResult, questionResult.topics);
    tags.value = mergeHistoricalItems(tagResult, questionResult.tags);
    reviews.value = reviewRows;
    void loadQuestionSources(requestedQuestionId);
    reviewRatingDrafts.value = Object.fromEntries(
      reviewRows.map((review) => [review.id, review.review_rating]),
    );
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

async function loadQuestionSources(requestedQuestionId = questionId.value): Promise<void> {
  const requestRevision = ++sourceLoadRevision;
  sourceLoading.value = true;
  sourceLoadError.value = "";
  try {
    const sourceRows = await request<QuestionSourceItem[]>(
      "/api/v1/questions/" + requestedQuestionId + "/sources",
    );
    if (requestRevision !== sourceLoadRevision || requestedQuestionId !== questionId.value) return;
    sources.value = sourceRows;
    if (!sourceRows.some((source) => source.question_source_id === selectedSourceId.value)) {
      selectedSourceId.value = sourceRows[0]?.question_source_id ?? null;
    }
  } catch (error) {
    if (requestRevision === sourceLoadRevision && requestedQuestionId === questionId.value) {
      sourceLoadError.value = displayError(error);
    }
  } finally {
    if (requestRevision === sourceLoadRevision && requestedQuestionId === questionId.value) {
      sourceLoading.value = false;
    }
  }
}

async function update(payload: QuestionFormPayload): Promise<void> {
  const currentQuestion = question.value;
  if (!currentQuestion) return;
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
  if (!currentQuestion) return;
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
  if (!currentQuestion) return;
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
  if (!currentQuestion || review.question_id !== currentQuestion.id) return;
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
      updated.question_id !== requestedQuestionId ||
      updated.id !== reviewId ||
      !reviews.value.some((item) => item.id === reviewId)
    ) return;
    reviews.value = reviews.value.map((item) => (item.id === reviewId ? updated : item));
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
  <section aria-labelledby="question-detail-title">
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
      <QuestionRelationReview
        v-if="question.status === 'active' && !question.archived_at"
        :key="question.id"
        :question-id="question.id"
        :text="question.text"
      />
      <section aria-label="题目来源证据">
        <h3>截图来源与 OCR 证据</h3>
        <p v-if="sourceLoading" role="status">正在加载截图来源…</p>
        <template v-else-if="sourceLoadError">
          <p role="alert" aria-label="题目来源加载失败">截图来源加载失败：{{ sourceLoadError }}</p>
          <button
            type="button"
            aria-label="重试加载题目来源"
            :disabled="sourceLoading"
            @click="loadQuestionSources()"
          >
            重新加载来源
          </button>
        </template>
        <template v-else-if="sources.length">
          <p v-if="selectedSource">
            {{ selectedSource.source_title || selectedSource.original_filename || ("截图 " + selectedSource.source_asset_id) }}
          </p>
          <SourceImageViewer
            :sources="sources"
            :selected-source-id="selectedSourceId"
            :image-width="selectedSource?.display_width ?? 0"
            :image-height="selectedSource?.display_height ?? 0"
            @select-source="selectedSourceId = $event"
          />
          <details v-if="selectedSource" aria-label="题目来源 OCR 原文">
            <summary>查看原始 OCR 文本</summary>
            <pre>{{ selectedSource.raw_ocr_text_snapshot }}</pre>
            <p>OCR block：{{ selectedSource.ocr_block_ids.join(", ") }}</p>
          </details>
        </template>
        <p v-else aria-label="暂无截图来源">暂无截图来源</p>
      </section>
      <section aria-labelledby="practice-history-title">
        <h3 id="practice-history-title">练习掌握度历史</h3>
        <p v-if="reviews.length === 0">暂无练习记录</p>
        <ol v-else aria-label="练习历史">
          <li v-for="review in reviews" :key="review.id" :data-review-id="review.id">
            <time :datetime="review.reviewed_at">{{ review.reviewed_at }}</time>
            <span>{{ ratingLabel(review.review_rating) }}</span>
            <select
              v-model="reviewRatingDrafts[review.id]"
              :aria-label="`更正掌握度 ${review.id}`"
            >
              <option value="dont_know">不会</option>
              <option value="vague">模糊</option>
              <option value="basic">基本会</option>
              <option value="proficient">熟练</option>
            </select>
            <button
              type="button"
              :aria-label="`保存自评 ${review.id}`"
              :disabled="reviewRatingDrafts[review.id] === review.review_rating"
              @click="correctReview(review)"
            >
              更正自评
            </button>
          </li>
        </ol>
      </section>
    </template>
  </section>
</template>
