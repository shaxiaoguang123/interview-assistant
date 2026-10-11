<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { RouterLink } from "vue-router";
import type { MockInterviewContextSelection, MockInterviewOptions } from "../../api/mock-interviews";

const props = defineProps<{ options: MockInterviewOptions; busy?: boolean }>();
const emit = defineEmits<{
  start: [payload: { topic_id: number | null; question_count: number; context: MockInterviewContextSelection }];
}>();

const topicChoice = ref("all");
const questionCount = ref(3);
const selectedProjectIds = ref<number[]>([]);
const selectedMaterialIds = ref<number[]>([]);
const excludedMaterialIds = ref<number[]>([]);

const topicId = computed(() => topicChoice.value === "all" ? null : Number(topicChoice.value));
const availableCount = computed(() => topicId.value === null
  ? props.options.available_question_count
  : props.options.topic_question_counts[topicId.value] ?? 0);
const countChoices = computed(() => {
  if (availableCount.value <= 0) return [];
  if (availableCount.value < 3) return Array.from({ length: availableCount.value }, (_, index) => index + 1);
  return [3, 5, 10].filter((count) => count <= availableCount.value);
});
const includedMaterials = computed(() => props.options.materials.filter(isMaterialIncluded));

watch(availableCount, (count) => {
  if (count <= 0) return;
  if (!countChoices.value.includes(questionCount.value)) {
    questionCount.value = countChoices.value.at(-1) ?? Math.min(count, 3);
  }
}, { immediate: true });

function projectIsSelected(projectId: number): boolean {
  return selectedProjectIds.value.includes(projectId);
}

function toggleProject(projectId: number, checked: boolean): void {
  selectedProjectIds.value = checked
    ? [...new Set([...selectedProjectIds.value, projectId])]
    : selectedProjectIds.value.filter((id) => id !== projectId);
}

function isMaterialIncluded(material: MockInterviewOptions["materials"][number]): boolean {
  const selectedByProject = material.project_id !== null && selectedProjectIds.value.includes(material.project_id);
  return !excludedMaterialIds.value.includes(material.id)
    && (selectedByProject || selectedMaterialIds.value.includes(material.id));
}

function toggleMaterial(material: MockInterviewOptions["materials"][number], checked: boolean): void {
  const selectedByProject = material.project_id !== null && selectedProjectIds.value.includes(material.project_id);
  if (selectedByProject) {
    excludedMaterialIds.value = checked
      ? excludedMaterialIds.value.filter((id) => id !== material.id)
      : [...new Set([...excludedMaterialIds.value, material.id])];
    return;
  }
  selectedMaterialIds.value = checked
    ? [...new Set([...selectedMaterialIds.value, material.id])]
    : selectedMaterialIds.value.filter((id) => id !== material.id);
}

function start(): void {
  if (props.busy || countChoices.value.length === 0) return;
  emit("start", {
    topic_id: topicId.value,
    question_count: questionCount.value,
    context: {
      project_ids: [...selectedProjectIds.value],
      material_ids: [...selectedMaterialIds.value],
      exclude_material_ids: [...excludedMaterialIds.value],
    },
  });
}
</script>

<template>
  <form class="mock-setup-form panel" aria-label="模拟面试设置" @submit.prevent="start">
    <header class="mock-form-heading">
      <div><span class="eyebrow">独立训练模式</span><h3>开始一场文字模拟面试</h3></div>
      <span class="badge accent">只选用题库规范题</span>
    </header>
    <p class="helper">AI 追问不会进入题库，也不会改变自评、答案质量或复习安排。每次生成都由你主动点击。</p>

    <div class="mock-form-grid">
      <label>面试方向
        <select v-model="topicChoice" aria-label="面试方向" :disabled="busy">
          <option value="all">综合面试</option>
          <option v-for="topic in options.topics" :key="topic.id" :value="String(topic.id)">{{ topic.name }}</option>
        </select>
      </label>
      <label>题目数量
        <select v-model.number="questionCount" aria-label="题目数量" :disabled="busy || !countChoices.length">
          <option v-for="count in countChoices" :key="count" :value="count">{{ count }} 道</option>
        </select>
      </label>
    </div>
    <p class="mock-availability" role="status">{{ availableCount }} 道当前可用的规范题</p>

    <details class="mock-context-picker">
      <summary>可选：选择个人 Project / Material 作为面试上下文</summary>
      <p class="helper">未选择时不会发送个人资料。选择项目会包含其中允许加入上下文的资料；你可以单独排除某份资料。模型仅收到当前问题相关的资料片段。</p>
      <fieldset v-if="options.projects.length" class="mock-context-list">
        <legend>Project</legend>
        <label v-for="project in options.projects" :key="project.id" class="mock-check-row">
          <input type="checkbox" :checked="projectIsSelected(project.id)" :disabled="busy" @change="toggleProject(project.id, ($event.target as HTMLInputElement).checked)" />
          <span><strong>{{ project.name }}</strong><small>项目 Profile 与已启用资料</small></span>
        </label>
      </fieldset>
      <fieldset v-if="options.materials.length" class="mock-context-list">
        <legend>单独选择或排除资料</legend>
        <label v-for="material in options.materials" :key="material.id" class="mock-check-row">
          <input type="checkbox" :checked="isMaterialIncluded(material)" :disabled="busy" @change="toggleMaterial(material, ($event.target as HTMLInputElement).checked)" />
          <span><strong>{{ material.title }}</strong><small>{{ material.kind }} · 第 {{ material.version_no }} 版{{ material.project_id ? " · 属于项目" : "" }}</small></span>
        </label>
      </fieldset>
      <p v-if="includedMaterials.length" class="mock-selected-materials"><strong>本次已选资料：</strong>{{ includedMaterials.map((material) => material.title).join("、") }}</p>
      <p v-else class="mock-selected-materials">当前没有资料会加入 AI 上下文。</p>
    </details>

    <div v-if="!options.llm_configured" class="mock-llm-notice" role="status">
      <span>未配置 AI Provider：你仍可使用题库、开始面试、记录回答并保存文字记录；AI 追问和总结暂不可用。</span>
      <RouterLink to="/settings">前往模型设置</RouterLink>
    </div>
    <p v-if="availableCount === 0" class="empty-state">这个方向还没有可用题目。先去题库添加或确认几道题，再回来开始模拟面试。</p>
    <div class="action-row mock-form-actions">
      <button class="primary" type="submit" :disabled="busy || availableCount === 0">{{ busy ? "正在准备…" : "开始模拟面试" }}</button>
      <RouterLink to="/questions">整理题库</RouterLink>
    </div>
  </form>
</template>

<style scoped>
.mock-setup-form { display: grid; gap: 18px; }
.mock-form-heading { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px; }
.mock-form-heading h3 { margin: 0; }
.mock-form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.mock-availability { margin: 0; color: var(--muted); font-size: 13px; }
.mock-context-picker { border-top: 1px solid var(--border); padding-top: 8px; }
.mock-context-picker > .helper { max-width: 80ch; margin: 4px 0 14px; }
.mock-context-list { display: grid; gap: 4px; margin: 12px 0; }
.mock-check-row { display: flex; align-items: flex-start; gap: 10px; min-height: 44px; padding: 8px; border-radius: 8px; }
.mock-check-row span { display: grid; gap: 2px; min-width: 0; }
.mock-check-row small { color: var(--muted); overflow-wrap: anywhere; }
.mock-selected-materials { margin: 8px 0 0; padding: 10px 12px; border-radius: 8px; background: var(--brand-soft); font-size: 13px; overflow-wrap: anywhere; }
.mock-llm-notice { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px 16px; padding: 12px 14px; color: var(--warning); background: var(--warning-soft); border-radius: 8px; font-size: 13px; }
.mock-form-actions { margin-top: 4px; }
@media (max-width: 680px) { .mock-form-grid { grid-template-columns: minmax(0, 1fr); } .mock-form-actions { display: grid; grid-template-columns: 1fr; } .mock-form-actions > * { text-align: center; } }
</style>
