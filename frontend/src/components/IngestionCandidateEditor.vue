<script setup lang="ts">
import { computed, ref, watch } from "vue";

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
  ocr_blocks: Array<{ id: string; text: string }>;
}

interface Candidate {
  id: number;
  text: string;
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
  confirm: [payload: { expected_revision: number }];
}>();

const textDraft = ref("");
const selectedTopicIds = ref<string[]>([]);
const selectedTagIds = ref<string[]>([]);
const correction = ref({ x: "0", y: "0", width: "0.1", height: "0.1" });
const splitEnabled = ref(false);
const splitPartOne = ref("");
const splitPartTwo = ref("");
const splitPartOneSourceText = ref("");
const splitPartTwoSourceText = ref("");
const splitPartOneBlockIds = ref<string[]>([]);
const splitPartTwoBlockIds = ref<string[]>([]);
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

function resetDrafts() {
  textDraft.value = props.candidate.text;
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
  splitPartOne.value = "";
  splitPartTwo.value = "";
  splitPartOneBlockIds.value = allBlockOptions.value.map((block) => block.id);
  splitPartTwoBlockIds.value = allBlockOptions.value.map((block) => block.id);
  splitPartOneSourceText.value = sourceTextForBlockIds(splitPartOneBlockIds.value);
  splitPartTwoSourceText.value = sourceTextForBlockIds(splitPartTwoBlockIds.value);
}

watch(
  () => [props.candidate.id, props.candidate.candidate_revision],
  resetDrafts,
  { immediate: true },
);

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

watch(
  splitPartOneBlockIds,
  (ids) => {
    splitPartOneSourceText.value = sourceTextForBlockIds(ids);
  },
  { deep: true },
);

watch(
  splitPartTwoBlockIds,
  (ids) => {
    splitPartTwoSourceText.value = sourceTextForBlockIds(ids);
  },
  { deep: true },
);

const dirty = computed(() => {
  const locator = selectedSource.value?.locator_correction_json ?? selectedSource.value?.locator_json;
  return textDraft.value !== props.candidate.text || !sameIds(selectedTopicIds.value, props.candidate.topics) ||
    !sameIds(selectedTagIds.value, props.candidate.tags) || !!locator && coordinates.some(key => Number(correction.value[key]) !== locator[key]);
});
watch(dirty, value => emit('dirty-change', value), {immediate:true});
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
    parts: [
      {
        text: splitPartOne.value,
        ocr_block_ids: splitPartOneBlockIds.value,
        source_text_snapshot: splitPartOneSourceText.value,
      },
      {
        text: splitPartTwo.value,
        ocr_block_ids: splitPartTwoBlockIds.value,
        source_text_snapshot: splitPartTwoSourceText.value,
      },
    ],
  });
}
</script>

<template>
  <section aria-label="候选题编辑" class="candidate-editor">
    <h3>校对正文</h3>
    <form aria-label="候选题正文与分类" @submit.prevent="save">
      <label>
        候选题正文
        <textarea v-model="textDraft" aria-label="候选题正文" />
      </label>
      <details class="candidate-classification"><summary>分类选择 <span class="helper">· {{ selectedTopicIds.length }} 个 Topic / {{ selectedTagIds.length }} 个 Tag</span></summary><div class="candidate-classification-grid">
      <label>
        Agent Topic
        <select v-model="selectedTopicIds" multiple aria-label="候选题 Topic">
          <option v-for="topic in topics" :key="topic.id" :value="String(topic.id)">
            {{ topic.name }}{{ topic.is_active ? "" : "（停用）" }}
          </option>
        </select>
      </label>
      <label>
        Tag
        <select v-model="selectedTagIds" multiple aria-label="候选题标签">
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
          />
        </label>
      </fieldset></details>
      <button type="submit" :disabled="busy || !dirty">保存候选修改</button>
    </form>

    <div class="candidate-decision-actions"><button
      type="button"
      aria-label="切换候选拆分"
      @click="splitEnabled = !splitEnabled"
    >
      {{ splitEnabled ? "取消拆分" : "拆分候选题" }}
    </button>
    <form v-if="splitEnabled" aria-label="拆分候选题" @submit.prevent="split">
      <label>
        第一题最终题目正文
        <textarea v-model="splitPartOne" aria-label="拆分第一部分正文" />
      </label>
      <label>
        第一题 OCR 来源片段（原文证据）
        <textarea v-model="splitPartOneSourceText" aria-label="拆分第一部分 OCR 来源片段" />
      </label>
      <label>
        第一题 OCR block
        <select v-model="splitPartOneBlockIds" multiple aria-label="拆分第一部分 OCR 块">
          <option v-for="block in allBlockOptions" :key="block.id" :value="block.id">
            {{ block.text }}
          </option>
        </select>
      </label>
      <label>
        第二题最终题目正文
        <textarea v-model="splitPartTwo" aria-label="拆分第二部分正文" />
      </label>
      <label>
        第二题 OCR 来源片段（原文证据）
        <textarea v-model="splitPartTwoSourceText" aria-label="拆分第二部分 OCR 来源片段" />
      </label>
      <label>
        第二题 OCR block
        <select v-model="splitPartTwoBlockIds" multiple aria-label="拆分第二部分 OCR 块">
          <option v-for="block in allBlockOptions" :key="block.id" :value="block.id">
            {{ block.text }}
          </option>
        </select>
      </label>
      <button type="submit" :disabled="busy">保存拆分结果</button>
    </form>

    <button
      type="button"
      aria-label="拒绝候选题"
      :disabled="busy"
      @click="emit('archive', { expected_revision: candidate.candidate_revision })"
    >
      拒绝候选题
    </button>
    <p v-if="dirty" role="status" class="confirmation-hint">正文、分类或定位尚未保存，请先保存修改，再审核相似题或确认入库。</p>
    <p v-else-if="confirmationBlocked" class="confirmation-hint" aria-label="确认受限原因">请先完成相似题审核；加载失败或未处理的同题建议会阻止独立确认。可排除误报、明确分类，或暂留待处理。</p>
    <button
      class="primary"
      type="button"
      aria-label="确认进入题库"
      :disabled="busy || confirmationBlocked || dirty"
      @click="emit('confirm', { expected_revision: candidate.candidate_revision })"
    >
      确认进入题库
    </button></div>
  </section>
</template>
