<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { ApiError } from "../../api/client";
import {
  suggestIngestionCandidate,
  type IngestionAiCandidate,
  type IngestionAiSplitPart,
  type IngestionAiSuggestion,
  type IngestionAiTaxonomyItem,
} from "../../api/ingestion-ai";

const props = withDefaults(
  defineProps<{
    candidate: IngestionAiCandidate;
    topics?: IngestionAiTaxonomyItem[];
    tags?: IngestionAiTaxonomyItem[];
    draftDirty?: boolean;
    disabled?: boolean;
  }>(),
  { topics: () => [], tags: () => [], draftDirty: false, disabled: false },
);

const emit = defineEmits<{
  apply: [payload: {
    text?: string;
    topic_ids?: number[];
    tag_ids?: number[];
    difficulty?: string | null;
  }];
  "apply-split": [parts: IngestionAiSplitPart[]];
  conflict: [];
}>();

const loading = ref(false);
const result = ref<IngestionAiSuggestion | null>(null);
const error = ref("");
const notice = ref("");
const selectedText = ref(false);
const selectedTopics = ref(false);
const selectedTags = ref(false);
const selectedDifficulty = ref(false);
const overwriteAcknowledged = ref(false);
let requestSequence = 0;

const activeTopics = computed(() => props.topics.filter((item) => item.is_active));
const activeTags = computed(() => props.tags.filter((item) => item.is_active));
const currentResult = computed(() =>
  result.value?.candidate_id === props.candidate.id &&
  result.value.candidate_revision === props.candidate.candidate_revision
    ? result.value
    : null,
);
const hasSelectedEdits = computed(
  () => selectedText.value || selectedTopics.value || selectedTags.value || selectedDifficulty.value,
);
const canApply = computed(
  () => hasSelectedEdits.value && (!props.draftDirty || overwriteAcknowledged.value),
);

function resetResult() {
  requestSequence += 1;
  loading.value = false;
  result.value = null;
  error.value = "";
  notice.value = "";
  selectedText.value = false;
  selectedTopics.value = false;
  selectedTags.value = false;
  selectedDifficulty.value = false;
  overwriteAcknowledged.value = false;
}

watch(() => props.candidate.id, resetResult, { immediate: true });
watch(() => props.candidate.candidate_revision, (revision, previousRevision) => {
  if (previousRevision === undefined || revision === previousRevision) return;
  const conflictMessage = error.value.includes("候选已变化") ? error.value : "";
  resetResult();
  if (conflictMessage) error.value = conflictMessage;
});

onBeforeUnmount(() => {
  requestSequence += 1;
});

async function analyze() {
  const candidateId = props.candidate.id;
  const revision = props.candidate.candidate_revision;
  const sequence = ++requestSequence;
  result.value = null;
  error.value = "";
  notice.value = "";
  loading.value = true;
  try {
    const suggestion = await suggestIngestionCandidate(candidateId, revision);
    if (sequence !== requestSequence) return;
    if (suggestion.candidate_id !== candidateId || suggestion.candidate_revision !== revision) {
      throw new Error("AI 返回结果对应的候选版本不一致。");
    }
    result.value = suggestion;
  } catch (caught) {
    if (sequence !== requestSequence) return;
    result.value = null;
    if (caught instanceof ApiError && caught.status === 409) {
      error.value = "候选已变化：旧建议已丢弃。请检查当前草稿后重新分析。";
      emit("conflict");
    } else if (caught instanceof ApiError && caught.code === "LLM_NOT_CONFIGURED") {
      error.value = "尚未配置 LLM。你仍可继续使用 OCR、人工整理和确认入库；需要 AI 时可前往设置配置模型。";
    } else if (caught instanceof ApiError && caught.code === "LLM_TIMEOUT") {
      error.value = "模型请求超时，候选和草稿均已保留；可以稍后重试。";
    } else if (caught instanceof ApiError) {
      error.value = caught.message;
    } else {
      error.value = caught instanceof Error ? caught.message : "AI 建议生成失败；候选和草稿均已保留。";
    }
  } finally {
    if (sequence === requestSequence) loading.value = false;
  }
}

function applySelectedEdits() {
  const suggestion = currentResult.value;
  if (!suggestion || !canApply.value) return;
  const payload: {
    text?: string;
    topic_ids?: number[];
    tag_ids?: number[];
    difficulty?: string | null;
  } = {};
  if (selectedText.value) payload.text = suggestion.suggested_text;
  if (selectedTopics.value) payload.topic_ids = [...suggestion.topic_ids];
  if (selectedTags.value) payload.tag_ids = [...suggestion.tag_ids];
  if (selectedDifficulty.value) payload.difficulty = suggestion.difficulty;
  emit("apply", payload);
  notice.value = "已应用到可编辑草稿。点击“保存候选修改”后才会写入候选。";
  selectedText.value = false;
  selectedTopics.value = false;
  selectedTags.value = false;
  selectedDifficulty.value = false;
  overwriteAcknowledged.value = false;
}

function applySplitDraft() {
  const suggestion = currentResult.value;
  if (!suggestion?.split_parts.length || (props.draftDirty && !overwriteAcknowledged.value)) return;
  emit("apply-split", suggestion.split_parts.map((part) => ({
    text: part.text,
    ocr_block_ids: [...part.ocr_block_ids],
    source_text_snapshot: part.source_text_snapshot,
  })));
  notice.value = "拆分建议已填入可编辑草稿；检查每题正文和 OCR 来源后，再点击“保存拆分结果”。";
  overwriteAcknowledged.value = false;
}

function topicName(id: number): string {
  return activeTopics.value.find((item) => item.id === id)?.name ?? `#${id}`;
}

function tagName(id: number): string {
  return activeTags.value.find((item) => item.id === id)?.name ?? `#${id}`;
}

function blocksForPart(part: IngestionAiSplitPart): string[] {
  const wanted = new Set(part.ocr_block_ids);
  return props.candidate.sources.flatMap((source) =>
    source.ocr_blocks
      .filter((block) => wanted.has(block.id))
      .map((block) => `${block.id} · ${block.text}`),
  );
}

function difficultyLabel(value: string | null): string {
  if (value === "easy") return "简单";
  if (value === "medium") return "中等";
  if (value === "hard") return "困难";
  return "未设置";
}
</script>

<template>
  <section class="candidate-ai-assist" aria-label="AI 辅助整理">
    <header class="ai-assist-heading">
      <div>
        <span class="eyebrow">可选 · 用户主动触发</span>
        <h4>AI 辅助整理</h4>
      </div>
      <span class="badge">仅生成建议</span>
    </header>
    <p class="helper">只发送当前已保存候选正文、关联 OCR 文本和有效 Topic/Tag 名单。不会发送原图、简历、回答或练习记录。</p>
    <details class="ai-send-preview">
      <summary>查看本次将发送的内容</summary>
      <div class="ai-send-preview-grid">
        <section>
          <h5>已保存候选正文</h5>
          <pre>{{ candidate.text }}</pre>
        </section>
        <section>
          <h5>关联 OCR 原文块</h5>
          <ol>
            <li v-for="source in candidate.sources" :key="source.question_source_id">
              <ol>
                <li v-for="block in source.ocr_blocks" :key="block.id">
                  <code>{{ block.id }}</code><span>阅读顺序 {{ block.reading_order }} · 区域 {{ block.bbox.x }}, {{ block.bbox.y }}, {{ block.bbox.width }}, {{ block.bbox.height }} · {{ block.text }}</span>
                </li>
              </ol>
            </li>
          </ol>
        </section>
        <section>
          <h5>有效 Topic</h5>
          <ul><li v-for="topic in activeTopics" :key="topic.id">#{{ topic.id }} · {{ topic.name }}</li></ul>
        </section>
        <section>
          <h5>有效 Tag</h5>
          <ul><li v-for="tag in activeTags" :key="tag.id">#{{ tag.id }} · {{ tag.name }}</li></ul>
        </section>
      </div>
      <p v-if="draftDirty" class="ai-draft-notice">当前有未保存编辑；请求只使用上方已保存正文和 OCR 原文，不会读取或发送你的草稿。</p>
    </details>

    <button
      type="button"
      class="ai-analyze-button"
      aria-label="使用 AI 分析当前候选"
      :disabled="disabled || loading"
      @click="analyze"
    >
      {{ loading ? "正在分析候选…" : "使用 AI 分析" }}
    </button>
    <p v-if="error" role="alert" class="ai-assist-error">{{ error }} <a v-if="error.includes('前往设置')" href="/settings">打开设置</a></p>
    <p v-if="notice" role="status" class="ai-assist-notice">{{ notice }}</p>

    <article v-if="currentResult" class="ai-suggestion-result" aria-label="AI 建议结果">
      <h5>题干建议对比</h5>
      <div class="ai-text-comparison">
        <div><strong>当前候选</strong><p>{{ currentResult.original_text }}</p></div>
        <div><strong>AI 建议</strong><p>{{ currentResult.suggested_text }}</p></div>
      </div>
      <p v-if="currentResult.reason" class="helper">{{ currentResult.reason }}</p>
      <ul v-if="currentResult.warnings.length" class="ai-warnings">
        <li v-for="(warning, index) in currentResult.warnings" :key="index">{{ warning }}</li>
      </ul>
      <fieldset class="ai-apply-fields">
        <legend>选择要应用到候选编辑草稿的建议</legend>
        <label><input v-model="selectedText" type="checkbox" aria-label="应用建议题干" /> 应用题干</label>
        <label><input v-model="selectedTopics" type="checkbox" aria-label="应用建议 Topic" /> Topic：{{ currentResult.topic_ids.map(topicName).join("、") || "无建议（可清除现有选择）" }}</label>
        <label><input v-model="selectedTags" type="checkbox" aria-label="应用建议 Tag" /> Tag：{{ currentResult.tag_ids.map(tagName).join("、") || "无建议（可清除现有选择）" }}</label>
        <label><input v-model="selectedDifficulty" type="checkbox" aria-label="应用建议难度" /> 难度：{{ difficultyLabel(currentResult.difficulty) }}</label>
      </fieldset>
      <label v-if="draftDirty" class="ai-overwrite-confirmation">
        <input v-model="overwriteAcknowledged" type="checkbox" aria-label="确认将选中的建议用于未保存草稿" />
        我确认将选中的字段应用到当前未保存草稿；未选字段会保留。
      </label>
      <button
        type="button"
        aria-label="应用选中的 AI 建议到草稿"
        :disabled="disabled || !canApply"
        @click="applySelectedEdits"
      >应用选中的 AI 建议到草稿</button>

      <section class="ai-split-suggestion" aria-label="AI 拆题建议">
        <h5>多题拆分建议</h5>
        <p v-if="!currentResult.split_parts.length" class="helper">模型未发现有足够原文证据支持的多题拆分。</p>
        <ol v-else>
          <li v-for="(part, index) in currentResult.split_parts" :key="`${index}:${part.ocr_block_ids.join(',')}`">
            <strong>建议第 {{ index + 1 }} 题</strong>
            <p>{{ part.text }}</p>
            <blockquote>{{ part.source_text_snapshot }}</blockquote>
            <ul><li v-for="block in blocksForPart(part)" :key="block">来源 OCR 块：<code>{{ block }}</code></li></ul>
          </li>
        </ol>
        <button
          v-if="currentResult.split_parts.length"
          type="button"
          aria-label="应用拆分建议到可编辑草稿"
          :disabled="disabled || (draftDirty && !overwriteAcknowledged)"
          @click="applySplitDraft"
        >填入可编辑拆分草稿</button>
      </section>
    </article>
  </section>
</template>

<style scoped>
.candidate-ai-assist { display: grid; gap: 12px; margin: 18px 0; padding: 16px; border: 1px solid var(--border); border-radius: 10px; background: var(--canvas); min-width: 0; }
.ai-assist-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.ai-assist-heading h4 { margin: 2px 0 0; font-size: 16px; }
.candidate-ai-assist p { margin: 0; }
.ai-send-preview { border-top: 1px solid var(--border); padding-top: 10px; }
.ai-send-preview summary { cursor: pointer; min-height: 32px; font-weight: 600; }
.ai-send-preview-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; margin-top: 10px; }
.ai-send-preview-grid section { min-width: 0; padding: 12px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface); }
.ai-send-preview-grid h5,.ai-suggestion-result h5 { margin: 0 0 8px; font-size: 14px; }
.ai-send-preview pre,.ai-send-preview code,.ai-suggestion-result code { white-space: pre-wrap; overflow-wrap: anywhere; font: inherit; }
.ai-send-preview ol,.ai-send-preview ul,.ai-suggestion-result ol,.ai-suggestion-result ul { margin: 0; padding-left: 20px; }
.ai-send-preview ol ol { display: grid; gap: 8px; }
.ai-send-preview ol ol li { display: grid; gap: 2px; }
.ai-send-preview code,.ai-suggestion-result code { color: var(--muted); font-size: 12px; }
.ai-send-preview-grid ul { max-height: 180px; overflow: auto; }
.ai-draft-notice,.ai-overwrite-confirmation { color: var(--warning); background: var(--warning-soft); border-radius: 7px; padding: 10px; }
.ai-analyze-button { justify-self: start; }
.ai-assist-error { color: var(--danger); }
.ai-assist-notice { color: var(--success); }
.ai-suggestion-result { display: grid; gap: 12px; border-top: 1px solid var(--border); padding-top: 14px; }
.ai-text-comparison { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.ai-text-comparison > div { min-width: 0; padding: 12px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface); }
.ai-text-comparison p { margin-top: 6px; white-space: pre-wrap; overflow-wrap: anywhere; }
.ai-apply-fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px 16px; border: 1px solid var(--border); border-radius: 8px; padding: 12px; }
.ai-apply-fields label,.ai-overwrite-confirmation { display: flex; align-items: flex-start; gap: 8px; overflow-wrap: anywhere; }
.ai-apply-fields input,.ai-overwrite-confirmation input { margin-top: 3px; }
.ai-warnings { color: var(--warning); }
.ai-split-suggestion { display: grid; gap: 8px; padding-top: 10px; border-top: 1px dashed var(--border); }
.ai-split-suggestion > ol { display: grid; gap: 10px; }
.ai-split-suggestion > ol > li { padding: 12px; border-radius: 8px; background: var(--surface); border: 1px solid var(--border); }
.ai-split-suggestion p { margin: 6px 0; white-space: pre-wrap; overflow-wrap: anywhere; }
.ai-split-suggestion blockquote { margin: 8px 0; padding-left: 10px; border-left: 3px solid var(--border); color: var(--muted); }
@media (max-width: 767px) {
  .candidate-ai-assist { padding: 12px; }
  .ai-send-preview-grid,.ai-text-comparison,.ai-apply-fields { grid-template-columns: minmax(0, 1fr); }
  .ai-analyze-button,.ai-suggestion-result > button,.ai-split-suggestion > button { width: 100%; }
}
</style>
