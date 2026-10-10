<script setup lang="ts">
import { ref, watch } from "vue";

interface TaxonomyChoice {
  id: number;
  name: string;
  is_active: boolean;
}

const props = withDefaults(
  defineProps<{
    initialText?: string;
    initialAnswerType?: string | null;
    initialDifficulty?: string | null;
    initialTopicIds?: number[];
    initialTagIds?: number[];
    topics: TaxonomyChoice[];
    tags: TaxonomyChoice[];
    saving?: boolean;
  }>(),
  {
    initialText: "",
    initialAnswerType: null,
    initialDifficulty: null,
    initialTopicIds: () => [],
    initialTagIds: () => [],
    saving: false,
  },
);

const emit = defineEmits<{
  save: [payload: {
    text: string;
    answer_type: string | null;
    difficulty: string | null;
    topic_ids: number[];
    tag_ids: number[];
  }];
}>();

const text = ref(props.initialText);
const answerType = ref(props.initialAnswerType ?? "");
const difficulty = ref(props.initialDifficulty ?? "");
const topicIds = ref<number[]>([...props.initialTopicIds]);
const tagIds = ref<number[]>([...props.initialTagIds]);

watch(() => props.initialText, (value) => (text.value = value));
watch(() => props.initialAnswerType, (value) => (answerType.value = value ?? ""));
watch(() => props.initialDifficulty, (value) => (difficulty.value = value ?? ""));
watch(() => props.initialTopicIds, (value) => (topicIds.value = [...value]));
watch(() => props.initialTagIds, (value) => (tagIds.value = [...value]));

function save(): void {
  emit("save", {
    text: text.value,
    answer_type: answerType.value.trim() || null,
    difficulty: difficulty.value.trim() || null,
    topic_ids: [...topicIds.value],
    tag_ids: [...tagIds.value],
  });
}
</script>

<template>
  <form class="question-form" aria-label="题目表单" @submit.prevent="save">
    <label>
      题目正文
      <textarea v-model="text" aria-label="题目正文" required />
    </label>
    <div class="form-fields"><label>
      题型
      <input v-model="answerType" aria-label="题型" />
    </label>
    <label>
      难度
      <select v-model="difficulty" aria-label="难度">
        <option value="">未设置</option>
        <option value="easy">简单</option>
        <option value="medium">中等</option>
        <option value="hard">困难</option>
      </select>
    </label>

    </div><fieldset>
      <legend>Topic</legend>
      <div class="classification-choices">
      <label v-for="topic in topics" :key="topic.id">
        <input
          v-model="topicIds"
          type="checkbox"
          :value="topic.id"
          :disabled="!topic.is_active && !topicIds.includes(topic.id)"
        />
        {{ topic.name }}<template v-if="!topic.is_active">（停用，先移除或替换）</template>
      </label>
      </div>
    </fieldset>

    <fieldset>
      <legend>Tag</legend>
      <div class="classification-choices">
      <label v-for="tag in tags" :key="tag.id">
        <input
          v-model="tagIds"
          type="checkbox"
          :value="tag.id"
          :disabled="!tag.is_active && !tagIds.includes(tag.id)"
        />
        {{ tag.name }}<template v-if="!tag.is_active">（停用，先移除或替换）</template>
      </label>
      </div>
    </fieldset>

    <button type="submit" :disabled="saving">{{ saving ? "保存中…" : "保存题目" }}</button>
  </form>
</template>
