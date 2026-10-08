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
  }>(),
  { topics: () => [], tags: () => [], selectedSourceId: null, busy: false },
);

const emit = defineEmits<{
  save: [payload: Record<string, unknown>];
  split: [payload: Record<string, unknown>];
  "select-source": [sourceId: number];
  archive: [payload: { expected_revision: number }];
  confirm: [payload: { expected_revision: number }];
}>();

const textDraft = ref("");
const selectedTopicIds = ref<string[]>([]);
const selectedTagIds = ref<string[]>([]);
const correction = ref({ x: "0", y: "0", width: "0.1", height: "0.1" });
const splitEnabled = ref(false);
const splitPartOne = ref("");
const splitPartTwo = ref("");
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

function save() {
  const source = selectedSource.value;
  const locatorCorrection = {
    x: Number(correction.value.x),
    y: Number(correction.value.y),
    width: Number(correction.value.width),
    height: Number(correction.value.height),
  };
  emit("save", {
    expected_revision: props.candidate.candidate_revision,
    text: textDraft.value,
    topic_ids: selectedTopicIds.value.map(Number),
    tag_ids: selectedTagIds.value.map(Number),
    source_locator_corrections: source
      ? [
          {
            question_source_id: source.question_source_id,
            locator_correction_json: locatorCorrection,
          },
        ]
      : [],
  });
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
        source_text_snapshot: splitPartOne.value,
      },
      {
        text: splitPartTwo.value,
        ocr_block_ids: splitPartTwoBlockIds.value,
        source_text_snapshot: splitPartTwo.value,
      },
    ],
  });
}
</script>

<template>
  <section aria-label="候选题编辑">
    <form aria-label="候选题正文与分类" @submit.prevent="save">
      <label>
        候选题正文
        <textarea v-model="textDraft" aria-label="候选题正文" />
      </label>
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

      <fieldset v-if="candidate.sources.length" aria-label="来源区域修正">
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
      </fieldset>
      <button type="submit" :disabled="busy">保存候选修改</button>
    </form>

    <button
      type="button"
      aria-label="切换候选拆分"
      @click="splitEnabled = !splitEnabled"
    >
      {{ splitEnabled ? "取消拆分" : "拆分候选题" }}
    </button>
    <form v-if="splitEnabled" aria-label="拆分候选题" @submit.prevent="split">
      <label>
        第一题正文和 OCR 来源片段
        <textarea v-model="splitPartOne" aria-label="拆分第一部分正文" />
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
        第二题正文和 OCR 来源片段
        <textarea v-model="splitPartTwo" aria-label="拆分第二部分正文" />
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
    <button
      type="button"
      aria-label="确认进入题库"
      :disabled="busy"
      @click="emit('confirm', { expected_revision: candidate.candidate_revision })"
    >
      确认进入题库
    </button>
  </section>
</template>
