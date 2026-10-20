<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { ApiError } from "../../api/client";
import type { IngestionCandidate, IngestionOCRBlock, IngestionTaxonomyItem } from "../../api/ingestion";
import {
  reviewIngestionJob,
  type IngestionAiBatchReview,
  type IngestionAiCandidateReview,
  type IngestionAiOrphanReview,
  type IngestionAiSplitPart,
} from "../../api/ingestion-ai";

const props = defineProps<{
  jobId: number;
  candidates: IngestionCandidate[];
  ocrBlocks: IngestionOCRBlock[];
  topics: IngestionTaxonomyItem[];
  tags: IngestionTaxonomyItem[];
  ready: boolean;
  busy: boolean;
  draftDirty: boolean;
}>();

const emit = defineEmits<{
  "apply-candidate": [payload: {
    candidate_id: number;
    expected_revision: number;
    text: string;
    topic_ids?: number[];
    tag_ids?: number[];
    difficulty?: string | null;
  }];
  "archive-candidate": [payload: { candidate_id: number; expected_revision: number }];
  "split-candidate": [payload: {
    candidate_id: number;
    expected_revision: number;
    parts: IngestionAiSplitPart[];
  }];
  "create-candidate": [payload: { ocr_block_ids: string[]; text: string }];
  "open-candidate": [candidateId: number];
  "manual-create": [ocrBlockIds: string[]];
  conflict: [];
}>();

const loading = ref(false);
const error = ref("");
const result = ref<IngestionAiBatchReview | null>(null);
const candidateDrafts = ref<Record<number, string>>({});
const splitDrafts = ref<Record<number, IngestionAiSplitPart[]>>({});
const orphanDrafts = ref<Record<string, string>>({});
let requestSequence = 0;

const currentResult = computed(() => result.value?.job_id === props.jobId ? result.value : null);
const questionCount = computed(() => currentResult.value?.candidate_reviews.filter((item) => item.classification === "question").length ?? 0);
const notQuestionCount = computed(() =>
  (currentResult.value?.candidate_reviews.filter((item) => item.classification === "not_question").length ?? 0) +
  (currentResult.value?.orphan_reviews.filter((item) => item.classification === "not_question").length ?? 0),
);
const uncertainCount = computed(() =>
  (currentResult.value?.candidate_reviews.filter((item) => item.classification === "uncertain").length ?? 0) +
  (currentResult.value?.orphan_reviews.filter((item) => item.classification === "uncertain").length ?? 0),
);

watch(() => props.jobId, () => {
  requestSequence += 1;
  loading.value = false;
  result.value = null;
  candidateDrafts.value = {};
  splitDrafts.value = {};
  orphanDrafts.value = {};
  error.value = "";
}, { immediate: true });

function classificationLabel(value: string): string {
  return value === "question" ? "建议作为题目" : value === "not_question" ? "建议排除" : "需要人工判断";
}

function classificationClass(value: string): string {
  return value === "question" ? "success" : value === "not_question" ? "muted" : "warning";
}

function difficultyLabel(value: string | null): string {
  return value === "easy" ? "简单" : value === "medium" ? "中等" : value === "hard" ? "困难" : "未建议";
}

function topicName(id: number): string {
  return props.topics.find((topic) => topic.id === id && topic.is_active)?.name ?? `#${id}`;
}

function tagName(id: number): string {
  return props.tags.find((tag) => tag.id === id && tag.is_active)?.name ?? `#${id}`;
}

function currentCandidate(review: IngestionAiCandidateReview): IngestionCandidate | undefined {
  return props.candidates.find((candidate) => candidate.id === review.candidate_id);
}

function isStale(review: IngestionAiCandidateReview): boolean {
  const candidate = currentCandidate(review);
  return !candidate || candidate.candidate_revision !== review.candidate_revision ||
    candidate.candidate_state !== "pending_review" || candidate.archived_at !== null;
}

function candidateSourceBlocks(review: IngestionAiCandidateReview): string[] {
  const candidate = currentCandidate(review);
  if (!candidate) return [];
  const wanted = new Set(candidate.sources.flatMap((source) => source.ocr_blocks.map((block) => block.id)));
  return props.ocrBlocks.filter((block) => wanted.has(block.id)).map((block) => `${block.id} · ${block.text}`);
}

function orphanKey(review: IngestionAiOrphanReview, index: number): string {
  return `${index}:${review.ocr_block_ids.join(",")}`;
}

function orphanBlockText(blockId: string): string {
  const block = props.ocrBlocks.find((item) => item.id === blockId);
  return block ? `${block.reading_order + 1}. ${block.text}` : `缺少来源块 ${blockId}`;
}

function linkedCandidateIds(review: IngestionAiOrphanReview): number[] {
  const blockIds = new Set(review.ocr_block_ids);
  return props.candidates
    .filter((candidate) => candidate.sources.some((source) => source.ocr_blocks.some((block) => blockIds.has(block.id))))
    .map((candidate) => candidate.id);
}

async function analyze() {
  if (!props.ready || props.busy || props.draftDirty) return;
  const jobId = props.jobId;
  const sequence = ++requestSequence;
  error.value = "";
  loading.value = true;
  try {
    const response = await reviewIngestionJob(jobId);
    if (sequence !== requestSequence) return;
    if (response.job_id !== jobId) throw new Error("AI 返回结果与当前截图任务不一致。");
    result.value = response;
    candidateDrafts.value = Object.fromEntries(
      response.candidate_reviews.map((review) => [review.candidate_id, review.suggested_text ?? ""]),
    );
    splitDrafts.value = Object.fromEntries(
      response.candidate_reviews.map((review) => [review.candidate_id, review.split_parts.map((part) => ({ ...part, ocr_block_ids: [...part.ocr_block_ids] }))]),
    );
    orphanDrafts.value = Object.fromEntries(
      response.orphan_reviews.map((review, index) => [orphanKey(review, index), review.suggested_text ?? ""]),
    );
  } catch (caught) {
    if (sequence !== requestSequence) return;
    if (caught instanceof ApiError && caught.status === 409) {
      result.value = null;
      error.value = "候选或分类已变化，旧建议已丢弃；请重新读取并分析。";
      emit("conflict");
    } else if (caught instanceof ApiError && caught.code === "LLM_NOT_CONFIGURED") {
      error.value = "尚未配置 LLM。OCR 和人工校对仍可用；需要批量整理时请先前往设置配置模型。";
    } else if (caught instanceof ApiError && caught.code === "LLM_TIMEOUT") {
      error.value = "模型请求超时；OCR 数据和现有候选均已保留，可稍后重试。";
    } else if (caught instanceof ApiError) {
      error.value = caught.message;
    } else {
      error.value = caught instanceof Error ? caught.message : "AI 分流失败；候选与 OCR 来源未更改。";
    }
  } finally {
    if (sequence === requestSequence) loading.value = false;
  }
}

function applyCandidate(review: IngestionAiCandidateReview) {
  const text = candidateDrafts.value[review.candidate_id]?.trim();
  if (!text || isStale(review) || props.draftDirty) return;
  const payload: {
    candidate_id: number;
    expected_revision: number;
    text: string;
    topic_ids?: number[];
    tag_ids?: number[];
    difficulty?: string | null;
  } = {
    candidate_id: review.candidate_id,
    expected_revision: review.candidate_revision,
    text,
  };
  if (review.topic_ids.length) payload.topic_ids = [...review.topic_ids];
  if (review.tag_ids.length) payload.tag_ids = [...review.tag_ids];
  if (review.difficulty) payload.difficulty = review.difficulty;
  emit("apply-candidate", payload);
}

function archiveCandidate(review: IngestionAiCandidateReview) {
  if (isStale(review) || props.draftDirty) return;
  emit("archive-candidate", {
    candidate_id: review.candidate_id,
    expected_revision: review.candidate_revision,
  });
}

function splitCandidate(review: IngestionAiCandidateReview) {
  const parts = splitDrafts.value[review.candidate_id] ?? [];
  if (!parts.length || isStale(review) || props.draftDirty) return;
  emit("split-candidate", {
    candidate_id: review.candidate_id,
    expected_revision: review.candidate_revision,
    parts,
  });
}

function createCandidate(review: IngestionAiOrphanReview, index: number) {
  const text = orphanDrafts.value[orphanKey(review, index)]?.trim();
  if (review.classification !== "question" || !text || linkedCandidateIds(review).length || props.draftDirty) return;
  emit("create-candidate", { ocr_block_ids: [...review.ocr_block_ids], text });
}
</script>

<template>
  <section class="job-ai-triage" aria-label="整张截图 AI 分流">
    <header class="inbox-section-heading">
      <div>
        <span class="eyebrow">整张截图 · 一次分析</span>
        <h4>AI 识别题目与非题目</h4>
      </div>
      <span class="badge">只生成建议</span>
    </header>
    <p class="helper">点击后才会把本任务 OCR 文本、候选正文和来源位置发送给当前 LLM Provider，可能产生服务费用；不发送原图、简历或其他资料。建议不会自动确认入库。</p>
    <details class="ai-send-preview">
      <summary>查看本次会发送的内容</summary>
      <ol>
        <li v-for="block in ocrBlocks" :key="block.id">
          <code>{{ block.id }}</code> · 阅读顺序 {{ typeof block.reading_order === "number" ? block.reading_order + 1 : "未知" }} · OCR 分数 {{ typeof block.confidence === "number" ? block.confidence.toFixed(2) : "未知" }} · {{ block.text }}
        </li>
      </ol>
      <p>现有候选 {{ candidates.filter((candidate) => candidate.candidate_state === 'pending_review' && !candidate.archived_at).length }} 道；Topic {{ topics.filter((topic) => topic.is_active).length }} 个；Tag {{ tags.filter((tag) => tag.is_active).length }} 个。</p>
      <h5>已保存候选正文</h5>
      <ul><li v-for="candidate in candidates.filter((item) => item.candidate_state === 'pending_review' && !item.archived_at)" :key="candidate.id">候选 #{{ candidate.id }} · {{ candidate.text }}</li></ul>
      <p v-if="draftDirty" class="ai-draft-notice">当前有未保存草稿；批量分析只读取已保存候选，操作按钮会暂时禁用以保护草稿。</p>
    </details>
    <p v-if="draftDirty" class="ai-draft-notice">当前候选有未保存编辑。请先保存或取消草稿，再分析，避免模型基于旧正文生成建议。</p>
    <button type="button" class="ai-analyze-button" :disabled="!ready || busy || loading || draftDirty" @click="analyze">
      {{ loading ? "正在分析整张截图…" : !ready ? "正在读取 OCR 来源…" : currentResult ? "重新分析整张截图" : "AI 整理本张截图" }}
    </button>
    <p v-if="error" role="alert" class="ai-assist-error">{{ error }} <a v-if="error.includes('设置')" href="/settings">打开设置</a></p>

    <section v-if="currentResult" class="job-ai-results" aria-label="整张截图 AI 分流结果">
      <header class="job-ai-counts" role="status">
        <strong>分析建议</strong>
        <span class="badge success">{{ questionCount }} 可能是题目</span>
        <span class="badge">{{ notQuestionCount }} 可能不是题目</span>
        <span class="badge warning">{{ uncertainCount }} 需要判断</span>
      </header>
      <p class="helper">这些是模型分类建议，不是校准后的概率。候选只有在你明确确认后才进入正式题库。</p>

      <div v-if="currentResult.candidate_reviews.length" class="job-ai-review-list">
        <h5>已有候选</h5>
        <details v-for="review in currentResult.candidate_reviews" :key="review.candidate_id" class="job-ai-review-row">
          <summary>
            <span class="badge" :class="classificationClass(review.classification)">{{ classificationLabel(review.classification) }}</span>
            候选 #{{ review.candidate_id }} · {{ currentCandidate(review)?.text ?? "候选已不存在" }}
          </summary>
          <div class="job-ai-review-body">
            <p><strong>OCR 原文：</strong>{{ review.source_text_snapshot }}</p>
            <template v-if="review.classification === 'question'">
              <label>建议题干（可编辑）<textarea v-model="candidateDrafts[review.candidate_id]" :disabled="busy" /></label>
              <p class="helper">Topic：{{ review.topic_ids.map(topicName).join("、") || "未建议" }} · Tag：{{ review.tag_ids.map(tagName).join("、") || "未建议" }} · 难度：{{ difficultyLabel(review.difficulty) }}</p>
              <p v-if="review.reason" class="helper">{{ review.reason }}</p>
              <ul v-if="review.warnings.length" class="ai-warnings"><li v-for="(warning, index) in review.warnings" :key="index">{{ warning }}</li></ul>
              <p v-if="isStale(review)" role="alert">候选版本已变化，不能使用这条旧建议。请重新分析。</p>
              <p v-if="draftDirty" class="ai-draft-notice">先保存当前候选编辑，避免覆盖未保存草稿。</p>
              <div class="action-row">
                <button type="button" :disabled="busy || loading || isStale(review) || draftDirty" @click="applyCandidate(review)">应用建议到待审核候选</button>
                <button v-if="review.split_parts.length" type="button" :disabled="busy || loading || isStale(review) || draftDirty" @click="splitCandidate(review)">拆分为 {{ review.split_parts.length }} 道待审核题</button>
                <button type="button" :disabled="busy || loading || isStale(review) || draftDirty" @click="emit('open-candidate', review.candidate_id)">打开人工校对</button>
              </div>
              <details v-if="review.split_parts.length" class="candidate-extras">
                <summary>查看拆题来源</summary>
                <ol><li v-for="(part, index) in splitDrafts[review.candidate_id]" :key="index"><label>建议第 {{ index + 1 }} 题（可编辑）<textarea v-model="splitDrafts[review.candidate_id][index].text" :disabled="busy" /></label><blockquote>{{ part.source_text_snapshot }}</blockquote><ul><li v-for="blockId in part.ocr_block_ids" :key="blockId"><code>{{ blockId }}</code></li></ul></li></ol>
              </details>
            </template>
            <template v-else>
              <p v-if="review.reason">{{ review.reason }}</p>
              <ul v-if="review.warnings.length" class="ai-warnings"><li v-for="(warning, index) in review.warnings" :key="index">{{ warning }}</li></ul>
              <ul class="job-ai-source-list"><li v-for="block in candidateSourceBlocks(review)" :key="block"><code>{{ block }}</code></li></ul>
              <div class="action-row">
                <button type="button" :disabled="busy || loading || isStale(review) || draftDirty" @click="emit('open-candidate', review.candidate_id)">打开人工校对</button>
                <button v-if="review.classification === 'not_question'" type="button" :disabled="busy || loading || isStale(review) || draftDirty" @click="archiveCandidate(review)">确认不是题目并归档候选</button>
              </div>
            </template>
          </div>
        </details>
      </div>

      <div v-if="currentResult.orphan_reviews.length" class="job-ai-review-list">
        <h5>当前候选未覆盖的 OCR 文本</h5>
        <details v-for="(review, index) in currentResult.orphan_reviews" :key="orphanKey(review, index)" class="job-ai-review-row">
          <summary><span class="badge" :class="classificationClass(review.classification)">{{ classificationLabel(review.classification) }}</span>{{ review.source_text_snapshot }}</summary>
          <div class="job-ai-review-body">
            <ul class="job-ai-source-list"><li v-for="blockId in review.ocr_block_ids" :key="blockId"><code>{{ orphanBlockText(blockId) }}</code></li></ul>
            <p v-if="review.reason" class="helper">{{ review.reason }}</p>
            <ul v-if="review.warnings.length" class="ai-warnings"><li v-for="(warning, warningIndex) in review.warnings" :key="warningIndex">{{ warning }}</li></ul>
            <template v-if="review.classification === 'question'">
              <label>建议题干（可编辑）<textarea v-model="orphanDrafts[orphanKey(review, index)]" :disabled="busy" /></label>
              <p v-if="linkedCandidateIds(review).length" class="success-banner" role="status">这些 OCR 来源已关联候选 {{ linkedCandidateIds(review).map((id) => `#${id}`).join("、") }}。</p>
              <div class="action-row">
                <button type="button" :disabled="busy || loading || props.draftDirty || linkedCandidateIds(review).length > 0" @click="createCandidate(review, index)">从来源创建待审核候选</button>
                <button type="button" :disabled="busy || loading || props.draftDirty" @click="emit('manual-create', review.ocr_block_ids)">人工选择并校对</button>
              </div>
            </template>
            <button v-else-if="review.classification === 'uncertain'" type="button" :disabled="busy || loading || props.draftDirty" @click="emit('manual-create', review.ocr_block_ids)">人工选择并校对</button>
            <p v-else class="helper">原文仍保留在 OCR 来源中，没有创建或删除题目。</p>
          </div>
        </details>
      </div>
    </section>
  </section>
</template>

<style scoped>
.job-ai-triage { display: grid; gap: 12px; margin: 16px 0 20px; padding: 16px; border: 1px solid var(--border); border-left: 3px solid var(--brand); border-radius: 10px; background: var(--canvas); min-width: 0; }
.job-ai-triage > p { margin: 0; }
.job-ai-triage .ai-analyze-button { justify-self: start; }
.job-ai-results { display: grid; gap: 14px; border-top: 1px solid var(--border); padding-top: 14px; }
.job-ai-counts { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.job-ai-counts strong { margin-right: auto; }
.job-ai-review-list { display: grid; gap: 8px; }
.job-ai-review-list > h5 { margin: 4px 0; font-size: 14px; }
.job-ai-review-row { min-width: 0; border: 1px solid var(--border); border-radius: 8px; background: var(--surface); padding: 0 12px; }
.job-ai-review-row > summary { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; overflow-wrap: anywhere; }
.job-ai-review-body { display: grid; gap: 10px; padding: 4px 0 14px; }
.job-ai-review-body > p { margin: 0; overflow-wrap: anywhere; }
.job-ai-review-body label { gap: 6px; }
.job-ai-review-body textarea { min-height: 84px; }
.job-ai-review-body .action-row { gap: 8px; }
.job-ai-review-body .action-row button { font-size: 13px; }
.job-ai-source-list { display: grid; gap: 4px; max-height: 160px; overflow: auto; padding-left: 20px; margin: 0; }
.job-ai-source-list code { font: inherit; font-size: 12px; color: var(--muted); white-space: pre-wrap; overflow-wrap: anywhere; }
.job-ai-review-row blockquote { margin: 6px 0; padding-left: 10px; border-left: 3px solid var(--border); color: var(--muted); }
.job-ai-triage .badge.muted { background: var(--canvas); color: var(--muted); }
@media (max-width: 767px) {
  .job-ai-triage { padding: 12px; }
  .job-ai-triage .ai-analyze-button,.job-ai-review-body .action-row button { width: 100%; }
  .job-ai-counts strong { flex-basis: 100%; }
  .job-ai-review-row { padding-inline: 10px; }
}
</style>
