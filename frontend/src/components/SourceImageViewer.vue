<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";

interface Locator {
  x: number;
  y: number;
  width: number;
  height: number;
}

interface OCRBlock {
  id: string;
  text: string;
  bbox: Locator;
  reading_order: number;
}

interface QuestionSource {
  question_source_id: number;
  source_asset_id: number;
  locator_json: Locator;
  locator_correction_json: Locator | null;
  source_text_snapshot: string;
  raw_ocr_text_snapshot: string;
  ocr_blocks: OCRBlock[];
}

const props = withDefaults(
  defineProps<{
    sources: QuestionSource[];
    selectedSourceId: number | null;
    imageWidth?: number;
    imageHeight?: number;
    containerWidth?: number;
    containerHeight?: number;
  }>(),
  {
    imageWidth: 0,
    imageHeight: 0,
    containerWidth: 0,
    containerHeight: 0,
  },
);

const emit = defineEmits<{
  "select-source": [sourceId: number];
}>();

const stage = ref<HTMLElement | null>(null);
const stageWidth = ref(props.containerWidth);
const stageHeight = ref(props.containerHeight);
const naturalWidth = ref(props.imageWidth);
const naturalHeight = ref(props.imageHeight);
let resizeObserver: ResizeObserver | undefined;

const selectedSource = computed(
  () =>
    props.sources.find((source) => source.question_source_id === props.selectedSourceId) ??
    props.sources[0],
);
const displayedAssetId = computed(() => selectedSource.value?.source_asset_id ?? null);
const displayedSources = computed(() =>
  props.sources.filter((source) => source.source_asset_id === displayedAssetId.value),
);
const blockOverlays = computed(() => {
  const unique = new Map<string, OCRBlock>();
  for (const source of displayedSources.value) {
    for (const block of source.ocr_blocks) unique.set(block.id, block);
  }
  return [...unique.values()].sort(
    (left, right) => left.reading_order - right.reading_order || left.id.localeCompare(right.id),
  );
});
const contentRect = computed(() => {
  const width = stageWidth.value;
  const height = stageHeight.value;
  const imageWidth = naturalWidth.value || 1;
  const imageHeight = naturalHeight.value || 1;
  if (width <= 0 || height <= 0) return { left: 0, top: 0, width: 0, height: 0 };
  const scale = Math.min(width / imageWidth, height / imageHeight);
  const renderedWidth = imageWidth * scale;
  const renderedHeight = imageHeight * scale;
  return {
    left: (width - renderedWidth) / 2,
    top: (height - renderedHeight) / 2,
    width: renderedWidth,
    height: renderedHeight,
  };
});
const overlayStyle = computed(() => ({
  left: String(contentRect.value.left) + "px",
  top: String(contentRect.value.top) + "px",
  width: String(contentRect.value.width) + "px",
  height: String(contentRect.value.height) + "px",
}));

function measureStage() {
  if (!stage.value) return;
  const bounds = stage.value.getBoundingClientRect();
  if (bounds.width > 0) stageWidth.value = bounds.width;
  if (bounds.height > 0) stageHeight.value = bounds.height;
}

function onImageLoad(event: Event) {
  const image = event.target as HTMLImageElement;
  if (!props.imageWidth && image.naturalWidth) naturalWidth.value = image.naturalWidth;
  if (!props.imageHeight && image.naturalHeight) naturalHeight.value = image.naturalHeight;
  measureStage();
}

watch(
  () => [props.containerWidth, props.containerHeight, props.imageWidth, props.imageHeight],
  ([containerWidth, containerHeight, imageWidth, imageHeight]) => {
    if (containerWidth) stageWidth.value = containerWidth;
    if (containerHeight) stageHeight.value = containerHeight;
    if (imageWidth) naturalWidth.value = imageWidth;
    if (imageHeight) naturalHeight.value = imageHeight;
    measureStage();
  },
);

onMounted(() => {
  measureStage();
  if (stage.value && typeof ResizeObserver !== "undefined") {
    resizeObserver = new ResizeObserver(measureStage);
    resizeObserver.observe(stage.value);
  }
});
onBeforeUnmount(() => resizeObserver?.disconnect());
</script>

<template>
  <section
    class="source-image-viewer"
    :data-source-asset-id="displayedAssetId ?? undefined"
    aria-label="截图来源定位"
  >
    <div class="source-row-list" aria-label="题目来源区域">
      <button
        v-for="source in sources"
        :key="source.question_source_id"
        type="button"
        :aria-label="'来源区域 ' + source.question_source_id"
        :aria-pressed="source.question_source_id === selectedSource?.question_source_id"
        @click="emit('select-source', source.question_source_id)"
      >
        来源 {{ source.question_source_id }} · 截图 {{ source.source_asset_id }}
      </button>
    </div>
    <p v-if="selectedSource" class="source-evidence">
      {{ selectedSource.source_text_snapshot }}
    </p>
    <div
      ref="stage"
      class="image-stage"
      :style="{
        width: containerWidth ? String(containerWidth) + 'px' : '100%',
        height: containerHeight ? String(containerHeight) + 'px' : 'min(70vh, 720px)',
      }"
    >
      <img
        v-if="displayedAssetId"
        :src="'/api/v1/sources/' + displayedAssetId + '/display'"
        :data-orientation-normalized="true"
        alt="EXIF 方向校正后的截图预览"
        @load="onImageLoad"
      />
      <svg
        v-if="displayedAssetId && naturalWidth && naturalHeight"
        data-overlay
        class="source-overlay"
        :style="overlayStyle"
        :viewBox="'0 0 ' + naturalWidth + ' ' + naturalHeight"
        preserveAspectRatio="none"
        aria-label="题目区域高亮"
      >
        <rect
          v-for="source in displayedSources"
          :key="'region-' + source.question_source_id"
          :data-source-region-id="source.question_source_id"
          :data-selected="source.question_source_id === selectedSource?.question_source_id ? 'true' : 'false'"
          :x="(source.locator_correction_json ?? source.locator_json).x * naturalWidth"
          :y="(source.locator_correction_json ?? source.locator_json).y * naturalHeight"
          :width="(source.locator_correction_json ?? source.locator_json).width * naturalWidth"
          :height="(source.locator_correction_json ?? source.locator_json).height * naturalHeight"
          class="question-region"
        />
        <rect
          v-for="block in blockOverlays"
          :key="block.id"
          :data-block-id="block.id"
          :x="block.bbox.x * naturalWidth"
          :y="block.bbox.y * naturalHeight"
          :width="block.bbox.width * naturalWidth"
          :height="block.bbox.height * naturalHeight"
          class="ocr-block-region"
        />
      </svg>
    </div>
    <a v-if="displayedAssetId" :href="'/api/v1/sources/' + displayedAssetId + '/original'">
      查看原始图片
    </a>
  </section>
</template>

<style scoped>
.image-stage {
  position: relative;
  overflow: hidden;
  min-width: 0;
  box-shadow: inset 0 0 0 1px #d4d8df;
  background: #17191d;
}

.image-stage img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.source-overlay {
  position: absolute;
  pointer-events: none;
}

.question-region {
  fill: rgb(255 210 40 / 13%);
  stroke: #f4ca27;
  stroke-width: 4;
  vector-effect: non-scaling-stroke;
}

.question-region[data-selected="true"] {
  stroke: #ff3e30;
  stroke-width: 5;
}

.ocr-block-region {
  fill: transparent;
  stroke: rgb(55 155 255 / 75%);
  stroke-width: 2;
  vector-effect: non-scaling-stroke;
}
</style>
