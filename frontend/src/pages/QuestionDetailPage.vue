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

interface PracticeReviewItem {
  id: number;
  question_id: number;
  session_item_id: number;
  review_rating: "dont_know" | "vague" | "basic" | "proficient";
  reviewed_at: string;
  created_at: string;
  updated_at: string;
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
const reviewRatingDrafts = ref<Record<number, PracticeReviewItem["review_rating"]>>({});
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

async function loadQuestion(): Promise<void> {
  loading.value = true;
  errorMessage.value = "";
  try {
    const [questionResult, topicResult, tagResult, reviewRows] = await Promise.all([
      request<QuestionDetail>(`/api/v1/questions/${questionId.value}`),
      request<TaxonomyItem[]>("/api/v1/topics"),
      request<TaxonomyItem[]>("/api/v1/tags"),
      request<PracticeReviewItem[]>(`/api/v1/questions/${questionId.value}/practice-reviews`),
    ]);
    question.value = questionResult;
    topics.value = mergeHistoricalItems(topicResult, questionResult.topics);
    tags.value = mergeHistoricalItems(tagResult, questionResult.tags);
    reviews.value = reviewRows;
    reviewRatingDrafts.value = Object.fromEntries(
      reviewRows.map((review) => [review.id, review.review_rating]),
    );
  } catch (error) {
    errorMessage.value = displayError(error);
  } finally {
    loading.value = false;
  }
}

async function update(payload: QuestionFormPayload): Promise<void> {
  const currentQuestion = question.value;
  if (!currentQuestion) return;

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
    question.value = await request<QuestionDetail>(`/api/v1/questions/${questionId.value}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
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

async function correctReview(review: PracticeReviewItem): Promise<void> {
  const reviewRating = reviewRatingDrafts.value[review.id];
  if (!reviewRating || reviewRating === review.review_rating) return;
  errorMessage.value = "";
  try {
    const updated = await request<PracticeReviewItem>(`/api/v1/practice-reviews/${review.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ review_rating: reviewRating }),
    });
    reviews.value = reviews.value.map((item) => (item.id === updated.id ? updated : item));
    reviewRatingDrafts.value[updated.id] = updated.review_rating;
  } catch (error) {
    errorMessage.value = displayError(error);
  }
}

onMounted(loadQuestion);
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
