<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from "vue";
import { ApiError } from "../api/client";
import {
  getSimilarCandidates, reviewRelation,
  type DecisionStatus, type QuestionRelationItem, type RelationReviewState, type RelationType, type SimilarityResult,
} from "../api/question-relations";

const props = withDefaults(defineProps<{
  questionId: number;
  text: string;
  contextKey?: string;
  disabled?: boolean;
}>(), { contextKey: "", disabled: false });
const emit = defineEmits<{ state: [state: RelationReviewState] }>();
const data = ref<SimilarityResult | null>(null);
const loading = ref(false);
const reviewing = ref(false);
const errorMessage = ref("");
const deferredMessage = ref("");
let requestRevision = 0;
let alive = true;

function context() {
  return { questionId: props.questionId, text: props.text, contextKey: props.contextKey };
}

function isCurrent(start: ReturnType<typeof context>, revision: number): boolean {
  return alive && revision === requestRevision && start.questionId === props.questionId &&
    start.text === props.text && start.contextKey === props.contextKey;
}

function publish(canConfirm: boolean) {
  emit("state", { questionId: props.questionId, contextKey: props.contextKey, canConfirm });
}

function displayError(error: unknown): string {
  if (error instanceof ApiError) return [error.message, ...Object.values(error.fields)].join("；");
  return "请求失败，请重试。";
}

async function load(scan = false) {
  const start = context();
  const revision = ++requestRevision;
  data.value = null;
  loading.value = true;
  reviewing.value = false;
  errorMessage.value = "";
  deferredMessage.value = "";
  publish(false);
  try {
    const result = await getSimilarCandidates(start.questionId, scan);
    if (!isCurrent(start, revision)) return;
    if (result.question_id !== start.questionId || !Array.isArray(result.candidates) || typeof result.confirmation_blocked !== "boolean") {
      throw new Error("Invalid similarity response");
    }
    data.value = result;
    publish(!result.confirmation_blocked);
  } catch (error) {
    if (isCurrent(start, revision)) errorMessage.value = displayError(error);
  } finally {
    if (isCurrent(start, revision)) loading.value = false;
  }
}

async function decide(relation: QuestionRelationItem, type: RelationType, decision: DecisionStatus) {
  if (loading.value || reviewing.value || props.disabled || errorMessage.value) return;
  const start = context();
  const revision = ++requestRevision;
  reviewing.value = true;
  deferredMessage.value = "";
  publish(false);
  try {
    await reviewRelation(start.questionId, relation, type, decision);
    if (!isCurrent(start, revision)) return;
    // Reread the complete gate counts and the next unresolved row beyond Top-20.
    await load();
  } catch (error) {
    if (isCurrent(start, revision)) {
      errorMessage.value = error instanceof ApiError && error.status === 409
        ? "审核状态已变化，请重新加载或扫描后再审核。" + displayError(error)
        : displayError(error);
    }
  } finally {
    if (isCurrent(start, revision)) reviewing.value = false;
  }
}

function decisionLabel(relation: QuestionRelationItem): string {
  if (relation.decision_status === "suggested") return "规则建议，尚未确认";
  if (relation.decision_status === "rejected") return "人工审核：已排除误报";
  return { same_question: "同题待归并", related_question: "人工审核：相关题", different_question: "人工审核：不同题" }[relation.relation_type];
}

watch(() => [props.questionId, props.text, props.contextKey], () => void load(), { immediate: true, flush: "sync" });
onBeforeUnmount(() => { alive = false; requestRevision += 1; });
</script>

<template>
  <section aria-label="相似题审核">
    <h3>相似题审核</h3>
    <p v-if="loading" role="status">正在加载相似题…</p>
    <p v-if="errorMessage" role="alert">相似题加载或审核失败：{{ errorMessage }}</p>
    <button type="button" aria-label="重新加载相似题" :disabled="loading || reviewing || disabled" @click="load()">重新加载相似题</button>
    <button type="button" aria-label="重新扫描相似题" :disabled="loading || reviewing || disabled" @click="load(true)">重新扫描相似题</button>
    <template v-if="data && !loading">
      <p>关系 {{ data.total_count }} · 待处理 {{ data.unresolved_count }}</p>
      <p v-if="data.total_count > data.candidates.length">最多显示 20 条，优先展示待处理关系；处理后继续显示其余关系。</p>
      <p v-if="data.scan_required" role="alert">正文或题目状态已变化，请重新扫描与审核。</p>
      <p v-if="data.unresolved_count > 0">
        同题需等待后续规范题归并功能。可暂不处理；确定为误报时可排除，或明确标记为相关题、不同题。
      </p>
      <p v-if="!data.candidates.length && !data.scan_required && !errorMessage">暂无相似题建议</p>
      <p v-if="deferredMessage" role="status">{{ deferredMessage }}</p>
      <ul v-if="data.candidates.length" aria-label="相似关系列表">
        <li v-for="relation in data.candidates" :key="relation.id" :data-relation-id="relation.id">
          <p>{{ relation.match_kind === "exact" ? "完全重复（规范化文本）" : "近似建议" }} · 相似度 {{ relation.confidence?.toFixed(3) ?? "未知" }}</p>
          <p>{{ relation.other_question.text }} · #{{ relation.other_question.id }}</p>
          <a v-if="relation.other_question.canonical_question_id" :href="`/questions/${relation.other_question.canonical_question_id}`">查看题目</a>
          <p>{{ decisionLabel(relation) }}</p>
          <button type="button" :aria-label="`排除误报关系 ${relation.id}`" :disabled="loading || reviewing || disabled || !!errorMessage || data.scan_required" @click="decide(relation, 'same_question', 'rejected')">排除误报</button>
          <button type="button" :aria-label="`标记为相关题关系 ${relation.id}`" :disabled="loading || reviewing || disabled || !!errorMessage || data.scan_required" @click="decide(relation, 'related_question', 'accepted')">标记为相关题</button>
          <button type="button" :aria-label="`标记为不同题关系 ${relation.id}`" :disabled="loading || reviewing || disabled || !!errorMessage || data.scan_required" @click="decide(relation, 'different_question', 'accepted')">标记为不同题</button>
          <button type="button" :aria-label="`暂不处理关系 ${relation.id}`" :disabled="loading || reviewing || disabled" @click="deferredMessage = '保留建议，待规范题归并功能完成后处理。'">暂不处理</button>
        </li>
      </ul>
    </template>
  </section>
</template>
