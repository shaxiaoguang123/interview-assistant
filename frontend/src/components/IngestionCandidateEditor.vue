<script setup lang="ts">
import { computed, ref, watch } from "vue";
import CandidateAiAssist from "./ingestion/CandidateAiAssist.vue";
import type { IngestionAiSplitPart } from "../api/ingestion-ai";

interface TopicTag {
  id: number;
  name: string;
  is_active: boolean;
}

interface CandidateSource {
  question_source_id: number;
  source_asset_id: number;
  locator_json: { x: number; y: number; width: number; height: number };
  locator_correction_json: { x: number; y: number; width: number; height: number } | null;
  source_text_snapshot: string;
  raw_ocr_text_snapshot: string;
  ocr_blocks: Array<{
    id: string;
    text: string;
    reading_order: number;
    bbox: { x: number; y: number; width: number; height: number };
  }>;
}

interface Candidate {
  id: number;
  text: string;
  difficulty?: string | null;
  status: string;
  candidate_state: string;
  candidate_revision: number;
  topics: TopicTag[];
  tags: TopicTag[];
  sources: CandidateSource[];
}

const props = withDefaults(
  defineProps<{
    candidate: Candidate;
    topics?: TopicTag[];
    tags?: TopicTag[];
    selectedSourceId?: number | null;
    busy?: boolean;
    confirmationBlocked?: boolean;
  }>(),
  { topics: () => [], tags: () => [], selectedSourceId: null, busy: false },
);

const emit = defineEmits<{
  save: [payload: Record<string, unknown>];
  split: [payload: Record<string, unknown>];
  "select-source": [sourceId: number];
  archive: [payload: { expected_revision: number }];
  "dirty-change": [dirty: boolean];
  "ai-conflict": [];
  confirm: [payload: { expected_revision: number }];
}>();

const textDraft = ref("");
const difficultyDraft = ref("");
const selectedTopicIds = ref<string[]>([]);
const selectedTagIds = ref<string[]>([]);
const correction = ref({ x: "0", y: "0", width: "0.1", height: "0.1" });
const splitEnabled = ref(false);
interface SplitDraftPart extends IngestionAiSplitPart {}
const splitParts = ref<SplitDraftPart[]>([]);
const splitTouched = ref(false);
const candidateDraftUserEdited = ref(false);
const splitDraftUserEdited = ref(false);
const staleRevisionNotice = ref(false);
const coordinates = ["x", "y", "width", "height"] as const;

const allBlockOptions = computed(() => {
  const unique = new Map<string, { id: string; text: string }>();
  for (const source of props.candidate.sources) {
    for (const block of source.ocr_blocks) unique.set(block.id, block);
  }
  return [...unique.values()];
});
const selectedSource = computed(
  () =>
    props.candidate.sources.find((source) => source.question_source_id === props.selectedSourceId) ??
    props.candidate.sources[0] ??
    null,
);

function sourceTextForBlockIds(ids: string[]): string {
  const selected = new Set(ids);
  return allBlockOptions.value
    .filter((block) => selected.has(block.id))
    .map((block) => block.text)
    .join("\n");
}

function sameIds(left: string[], right: TopicTag[]): boolean {
  const leftIds = left.map(Number);
  const rightIds = right.map((item) => item.id);
  return (
    leftIds.length === rightIds.length &&
    leftIds.every((id) => Number.isInteger(id) && rightIds.includes(id))
  );
}

function resetCandidateDrafts() {
  textDraft.value = props.candidate.text;
  difficultyDraft.value = props.candidate.difficulty ?? "";
  selectedTopicIds.value = props.candidate.topics.map((topic) => String(topic.id));
  selectedTagIds.value = props.candidate.tags.map((tag) => String(tag.id));
  const locator =
    selectedSource.value?.locator_correction_json ??
    selectedSource.value?.locator_json ??
    { x: 0, y: 0, width: 0.1, height: 0.1 };
  correction.value = {
    x: String(locator.x),
    y: String(locator.y),
    width: String(locator.width),
    height: String(locator.height),
  };
  candidateDraftUserEdited.value = false;
}

function resetSplitDrafts() {
  splitEnabled.value = false;
  splitParts.value = [];
  splitTouched.value = false;
  splitDraftUserEdited.value = false;
}

function resetDrafts() {
  resetCandidateDrafts();
  resetSplitDrafts();
  staleRevisionNotice.value = false;
}

watch(() => props.candidate.id, resetDrafts, { immediate: true });

watch(selectedSource, (source) => {
  if (!source) return;
  const locator = source.locator_correction_json ?? source.locator_json;
  correction.value = {
    x: String(locator.x),
    y: String(locator.y),
    width: String(locator.width),
    height: String(locator.height),
  };
});

const dirty = computed(() => {
  const locator = selectedSource.value?.locator_correction_json ?? selectedSource.value?.locator_json;
  return textDraft.value !== props.candidate.text || difficultyDraft.value !== (props.candidate.difficulty ?? "") ||
    !sameIds(selectedTopicIds.value, props.candidate.topics) ||
    !sameIds(selectedTagIds.value, props.candidate.tags) || !!locator && coordinates.some(key => Number(correction.value[key]) !== locator[key]);
});
const unsavedWork = computed(() => dirty.value || splitTouched.value);
watch(unsavedWork, value => emit('dirty-change', value), {immediate:true});
watch(dirty, (value) => {
  if (!value) {
    candidateDraftUserEdited.value = false;
    if (!splitTouched.value) staleRevisionNotice.value = false;
  }
});
watch(() => props.candidate.candidate_revision, (revision, previousRevision) => {
  if (previousRevision === undefined || revision === previousRevision) return;
  const preserveCandidateDraft = dirty.value && candidateDraftUserEdited.value;
  const preserveSplitDraft = splitTouched.value && splitDraftUserEdited.value;
  if (!preserveCandidateDraft) resetCandidateDrafts();
  if (!preserveSplitDraft) resetSplitDrafts();
  staleRevisionNotice.value = preserveCandidateDraft || preserveSplitDraft;
});

function markDraftEdited() {
  candidateDraftUserEdited.value = true;
}

function applyAiSuggestion(payload: {
  text?: string;
  topic_ids?: number[];
  tag_ids?: number[];
  difficulty?: string | null;
}) {
  if (payload.text !== undefined) textDraft.value = payload.text;
  if (payload.topic_ids !== undefined) selectedTopicIds.value = payload.topic_ids.map(String);
  if (payload.tag_ids !== undefined) selectedTagIds.value = payload.tag_ids.map(String);
  if (payload.difficulty !== undefined) difficultyDraft.value = payload.difficulty ?? "";
  candidateDraftUserEdited.value = true;
  staleRevisionNotice.value = false;
}

function makeBlankSplitPart(): SplitDraftPart {
  const ids = allBlockOptions.value.map((block) => block.id);
  return { text: "", ocr_block_ids: ids, source_text_snapshot: sourceTextForBlockIds(ids) };
}

function markSplitEdited() {
  splitTouched.value = true;
  splitDraftUserEdited.value = true;
}

function toggleSplit() {
  splitEnabled.value = !splitEnabled.value;
  if (splitEnabled.value && splitParts.value.length === 0) {
    splitParts.value = [makeBlankSplitPart(), makeBlankSplitPart()];
    splitTouched.value = false;
  } else if (!splitEnabled.value) {
    splitParts.value = [];
    splitTouched.value = false;
    splitDraftUserEdited.value = false;
    if (!dirty.value) {
      candidateDraftUserEdited.value = false;
      staleRevisionNotice.value = false;
    }
  }
}

function addSplitPart() {
  splitParts.value.push(makeBlankSplitPart());
  markSplitEdited();
}

function removeSplitPart(index: number) {
  if (splitParts.value.length <= 2) return;
  splitParts.value.splice(index, 1);
  markSplitEdited();
}

function updateSplitSourceText(index: number) {
  const part = splitParts.value[index];
  if (!part) return;
  part.source_text_snapshot = sourceTextForBlockIds(part.ocr_block_ids);
  markSplitEdited();
}

function applyAiSplit(parts: IngestionAiSplitPart[]) {
  splitEnabled.value = true;
  splitParts.value = parts.map((part) => ({
    text: part.text,
    ocr_block_ids: [...part.ocr_block_ids],
    source_text_snapshot: part.source_text_snapshot,
  }));
  markSplitEdited();
}

const canSubmitSplit = computed(() => splitParts.value.length >= 2 && splitParts.value.every(
  (part) => part.text.trim() && part.ocr_block_ids.length > 0 && part.source_text_snapshot.trim(),
));

function save() {
  const source = selectedSource.value;
  const locatorCorrection = {
    x: Number(correction.value.x),
    y: Number(correction.value.y),
    width: Number(correction.value.width),
    height: Number(correction.value.height),
  };
  const payload: Record<string, unknown> = {
    expected_revision: props.candidate.candidate_revision,
  };
  if (textDraft.value !== props.candidate.text) payload.text = textDraft.value;
  if (difficultyDraft.value !== (props.candidate.difficulty ?? "")) {
    payload.difficulty = difficultyDraft.value || null;
  }
  if (!sameIds(selectedTopicIds.value, props.candidate.topics)) {
    payload.topic_ids = selectedTopicIds.value.map(Number);
  }
  if (!sameIds(selectedTagIds.value, props.candidate.tags)) {
    payload.tag_ids = selectedTagIds.value.map(Number);
  }
  if (source) {
    const currentLocator = source.locator_correction_json ?? source.locator_json;
    const locatorChanged = coordinates.some(
      (coordinate) => locatorCorrection[coordinate] !== currentLocator[coordinate],
    );
    if (locatorChanged) {
      payload.source_locator_corrections = [
        {
          question_source_id: source.question_source_id,
          locator_correction_json: locatorCorrection,
        },
      ];
    }
  }
  if (Object.keys(payload).length > 1) emit("save", payload);
}

function onSourceChange(event: Event) {
  const value = Number((event.target as HTMLSelectElement).value);
  if (Number.isInteger(value) && value > 0) emit("select-source", value);
}

function split() {
  emit("split", {
    expected_revision: props.candidate.candidate_revision,
    parts: splitParts.value.map((part) => ({
      text: part.text,
      ocr_block_ids: [...part.ocr_block_ids],
      source_text_snapshot: part.source_text_snapshot,
    })),
  });
}
</script>

<template>
  <section aria-label="候选题编辑" class="candidate-editor">
    <h3>校对正文</h3>
    <form aria-label="候选题正文与分类" @submit.prevent="save">
      <label>
        候选题正文
        <textarea v-model="textDraft" aria-label="候选题正文" @input="markDraftEdited" />
      </label>
      <CandidateAiAssist
        :candidate="candidate"
        :topics="topics"
        :tags="tags"
        :draft-dirty="dirty || splitTouched"
        :disabled="busy"
        @apply="applyAiSuggestion"
        @apply-split="applyAiSplit"
        @conflict="emit('ai-conflict')"
      />
      <details class="candidate-classification"><summary>分类选择 <span class="helper">· {{ selectedTopicIds.length }} 个 Topic / {{ selectedTagIds.length }} 个 Tag</span></summary><div class="candidate-classification-grid">
      <label>
        难度
        <select v-model="difficultyDraft" aria-label="候选题难度" @change="markDraftEdited">
          <option value="">未设置</option>
          <option value="easy">简单</option>
          <option value="medium">中等</option>
          <option value="hard">困难</option>
        </select>
      </label>
      <label>
        Agent Topic
        <select v-model="selectedTopicIds" multiple aria-label="候选题 Topic" @change="markDraftEdited">
          <option v-for="topic in topics" :key="topic.id" :value="String(topic.id)">
            {{ topic.name }}{{ topic.is_active ? "" : "（停用）" }}
          </option>
        </select>
      </label>
      <label>
        Tag
        <select v-model="selectedTagIds" multiple aria-label="候选题标签" @change="markDraftEdited">
          <option v-for="tag in tags" :key="tag.id" :value="String(tag.id)">
            {{ tag.name }}{{ tag.is_active ? "" : "（停用）" }}
          </option>
        </select>
      </label>

      </div></details>
      <details v-if="candidate.sources.length" class="locator-tools"><summary>修正来源区域定位</summary><fieldset aria-label="来源区域修正">
        <legend>选择要修正的来源区域</legend>
        <label>
          来源区域
          <select
            :value="selectedSource?.question_source_id ?? ''"
            aria-label="选择来源定位"
            @change="onSourceChange"
          >
            <option
              v-for="source in candidate.sources"
              :key="source.question_source_id"
              :value="source.question_source_id"
            >
              来源 {{ source.question_source_id }} · 图片 {{ source.source_asset_id }}
            </option>
          </select>
        </label>
        <p v-if="selectedSource">{{ selectedSource.source_text_snapshot }}</p>
        <label v-for="coordinate in coordinates" :key="coordinate">
          {{ coordinate }}
          <input
            v-model="correction[coordinate]"
            type="number"
            min="0"
            max="1"
            step="any"
            :aria-label="'来源定位 ' + coordinate"
            @input="markDraftEdited"
          />
        </label>
      </fieldset></details>
      <button type="submit" :disabled="busy || !dirty">保存候选修改</button>
    </form>

    <div class="candidate-decision-actions"><button
      type="button"
      aria-label="切换候选拆分"
      @click="toggleSplit"
    >
      {{ splitEnabled ? "取消拆分" : "拆分候选题" }}
    </button>
    <form v-if="splitEnabled" aria-label="拆分候选题" @submit.prevent="split">
        <fieldset v-for="(part, index) in splitParts" :key="index" class="split-part-editor">
          <legend>第 {{ index + 1 }} 题</legend>
          <label>
            最终题目正文
            <textarea v-model="part.text" :aria-label="index === 0 ? '拆分第一部分正文' : index === 1 ? '拆分第二部分正文' : `拆分第${index + 1}题最终正文`" @input="markSplitEdited" />
          </label>
          <label>
            OCR 来源片段（原文证据）
            <textarea v-model="part.source_text_snapshot" :aria-label="index === 0 ? '拆分第一部分 OCR 来源片段' : index === 1 ? '拆分第二部分 OCR 来源片段' : `拆分第${index + 1}题 OCR 来源片段`" @input="markSplitEdited" />
          </label>
          <label>
            对应 OCR block
            <select v-model="part.ocr_block_ids" multiple :aria-label="index === 0 ? '拆分第一部分 OCR 块' : index === 1 ? '拆分第二部分 OCR 块' : `拆分第${index + 1}题 OCR 块`" @change="updateSplitSourceText(index)">
              <option v-for="block in allBlockOptions" :key="block.id" :value="block.id">
                {{ block.text }}
              </option>
            </select>
          </label>
          <button v-if="splitParts.length > 2" type="button" :aria-label="`移除拆分第${index + 1}题`" @click="removeSplitPart(index)">移除该题</button>
        </fieldset>
        <div class="split-actions">
          <button type="button" @click="addSplitPart">再加一道题</button>
          <button type="submit" :disabled="busy || !canSubmitSplit">保存拆分结果</button>
        </div>
    </form>

    <button
      type="button"
      aria-label="拒绝候选题"
      :disabled="busy"
      @click="emit('archive', { expected_revision: candidate.candidate_revision })"
    >
      拒绝候选题
    </button>
    <p v-if="staleRevisionNotice" role="status" class="confirmation-hint">候选已在其他操作中更新；当前未保存草稿已保留。请对照上方已保存题目后，再决定是否保存本地修改。</p>
    <p v-else-if="dirty" role="status" class="confirmation-hint">正文、分类、难度或定位尚未保存，请先保存修改，再审核相似题或确认入库。</p>
    <p v-else-if="splitTouched" role="status" class="confirmation-hint">拆分内容仍是可编辑草稿，尚未改变候选。请检查来源后提交拆分，或取消。</p>
    <p v-else-if="confirmationBlocked" class="confirmation-hint" aria-label="确认受限原因">请先完成相似题审核；加载失败或未处理的同题建议会阻止独立确认。可排除误报、明确分类，或暂留待处理。</p>
    <button
      class="primary"
      type="button"
      aria-label="确认进入题库"
      :disabled="busy || confirmationBlocked || dirty || splitTouched"
      @click="emit('confirm', { expected_revision: candidate.candidate_revision })"
    >
      确认进入题库
    </button></div>
  </section>
</template>

<style scoped>
.candidate-editor .split-part-editor { display: grid; grid-template-columns: minmax(0, 1fr); gap: 12px; }
.candidate-editor .split-part-editor > label { grid-column: 1 / -1; }
.candidate-editor .split-actions { display: flex; flex-wrap: wrap; gap: 8px; }
@media (max-width: 767px) {
  .candidate-editor .split-actions { display: grid; grid-template-columns: 1fr; }
}
</style>
