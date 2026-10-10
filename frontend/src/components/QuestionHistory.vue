<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { RouterLink } from "vue-router";
import SourceImageViewer from "./SourceImageViewer.vue";
import type { CanonicalHistory, PracticeReviewItem, ReviewRating } from "../api/question-history";

const props = defineProps<{history: CanonicalHistory; ratingDrafts: Record<number, ReviewRating>}>();
const emit = defineEmits<{
  "rating-change": [id: number, rating: ReviewRating];
  "correct-review": [review: PracticeReviewItem];
}>();
const selectedSourceId = ref<number | null>(null);
const selectedSource = computed(() => props.history.sources.find(s => s.question_source_id === selectedSourceId.value) ?? props.history.sources[0] ?? null);
const ratingLabels = {dont_know:"不会",vague:"模糊",basic:"基本会",proficient:"熟练"};
function formatTime(value:string) { const date=new Date(value);return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat('zh-CN',{dateStyle:'medium',timeStyle:'short'}).format(date); }
const itemLabels = {shown:"待练习",completed:"已完成",skipped:"已跳过"};
function changeRating(id: number, event: Event) {
  emit("rating-change", id, (event.target as HTMLSelectElement).value as ReviewRating);
}
watch(() => props.history.sources, sources => {
  if (!sources.some(s => s.question_source_id === selectedSourceId.value)) {
    selectedSourceId.value = sources[0]?.question_source_id ?? null;
  }
}, { immediate:true });
</script>

<template>
  <div class="question-history">
    <section aria-label="题目来源证据" class="history-sources">
      <h3>截图来源与 OCR 证据</h3>
      <template v-if="history.sources.length">
        <p v-if="selectedSource" class="source-caption">
          {{ selectedSource.source_title || selectedSource.original_filename || ("截图 " + selectedSource.source_asset_id) }}
          <span class="badge">原题 #{{ selectedSource.question_id }}</span>
        </p>
        <SourceImageViewer
          :sources="history.sources" :selected-source-id="selectedSourceId"
          :image-width="selectedSource?.display_width ?? 0" :image-height="selectedSource?.display_height ?? 0"
          @select-source="selectedSourceId = $event"
        />
        <details v-if="selectedSource" aria-label="题目来源 OCR 原文">
          <summary>查看原始 OCR 文本</summary>
          <pre>{{ selectedSource.raw_ocr_text_snapshot }}</pre>
          <p class="mono">OCR block：{{ selectedSource.ocr_block_ids.join(", ") }}</p>
        </details>
      </template>
      <p v-else aria-label="暂无截图来源" class="empty-state">暂无截图来源</p>
    </section>
    <div class="history-records">
      <section aria-labelledby="practice-history-title">
        <h3 id="practice-history-title">练习掌握度历史</h3>
        <p v-if="!history.practice_reviews.length" class="empty-state">暂无练习记录</p>
        <ol v-else aria-label="练习历史" class="history-list">
          <li v-for="review in history.practice_reviews" :key="review.id" :data-review-id="review.id">
            <div class="record-meta"><span class="badge">原题 #{{ review.question_id }}</span><time :datetime="review.reviewed_at">{{ formatTime(review.reviewed_at) }}</time></div>
            <span class="rating-label">{{ ratingLabels[review.review_rating] }}</span>
            <div class="action-row">
              <select :value="ratingDrafts[review.id]" :aria-label="`更正掌握度 ${review.id}`" @change="changeRating(review.id, $event)">
                <option value="dont_know">不会</option><option value="vague">模糊</option>
                <option value="basic">基本会</option><option value="proficient">熟练</option>
              </select>
              <button type="button" :aria-label="`保存自评 ${review.id}`" :disabled="ratingDrafts[review.id] === review.review_rating" @click="emit('correct-review',review)">更正自评</button>
            </div>
          </li>
        </ol>
      </section>
      <section aria-label="归并组练习会话历史">
        <h3>练习会话记录</h3>
        <p v-if="!history.session_items.length" class="empty-state">暂无练习会话记录</p>
        <ul v-else class="history-list">
          <li v-for="item in history.session_items" :key="item.id" :data-session-item-id="item.id">
            <RouterLink :to="`/practice/sessions/${item.session_id}`">会话 #{{ item.session_id }} · 第 {{ item.ordinal }} 题</RouterLink>
            <div class="record-meta"><span>原题 #{{ item.question_id }}</span><span class="badge">{{ itemLabels[item.status] }}</span></div>
          </li>
        </ul>
      </section>
    </div>
  </div>
</template>
