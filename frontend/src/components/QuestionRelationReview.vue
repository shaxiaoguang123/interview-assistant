<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from "vue";
import { RouterLink } from "vue-router";
import QuestionMergeDialog from "./QuestionMergeDialog.vue";
import type { MergeOutcome } from "../api/question-merge";
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
const emit = defineEmits<{ state: [state: RelationReviewState]; merged: [outcome: MergeOutcome] }>();
const panelElement = ref<HTMLElement | null>(null);
const mergeRelation = ref<QuestionRelationItem | null>(null);
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
    return result;
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
    if (type !== "same_question" || decision !== "accepted" || relation.decision_status !== "accepted" || relation.relation_type !== "same_question") {
      await reviewRelation(start.questionId, relation, type, decision);
    }
    if (!isCurrent(start, revision)) return;
    // Reread the complete gate counts and the next unresolved row beyond Top-20.
    const refreshed = await load();
    if (refreshed && type === "same_question" && decision === "accepted") {
      mergeRelation.value = refreshed.candidates.find(row => row.id === relation.id) ?? null;
    }
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

async function cancelMerge() {
  const relationId = mergeRelation.value?.id;
  mergeRelation.value = null;
  await nextTick();
  panelElement.value?.querySelector<HTMLButtonElement>(`button[aria-label="确认为同题并归并关系 ${relationId}"]`)?.focus();
}
async function merged(outcome: MergeOutcome) {
  mergeRelation.value = null;
  emit("merged", outcome);
  // A surviving root can refresh its gate. A merged source is refreshed by its parent.
  if (outcome.canonicalId === props.questionId) await load();
}

watch(() => [props.questionId, props.text, props.contextKey], () => { mergeRelation.value = null; void load(); }, { immediate: true, flush: "sync" });
onBeforeUnmount(() => { alive = false; requestRevision += 1; });
</script>

<template>
  <section ref="panelElement" aria-label="相似题审核" class="relation-panel">
    <div class="relation-heading"><div><h3>相似题审核</h3><span v-if="data" class="helper">关系 {{ data.total_count }} · 待处理 {{ data.unresolved_count }}</span></div>
    <p v-if="loading" role="status">正在加载相似题…</p>
    <p v-if="errorMessage" role="alert">相似题加载或审核失败：{{ errorMessage }}</p>
    <div class="action-row"><button type="button" aria-label="重新加载相似题" :disabled="loading || reviewing || disabled" @click="load()">重新加载相似题</button>
    <button type="button" aria-label="重新扫描相似题" :disabled="loading || reviewing || disabled" @click="load(true)">重新扫描相似题</button></div></div>
    <template v-if="data && !loading">

      <p v-if="data.total_count > data.candidates.length">最多显示 20 条，优先展示待处理关系；处理后继续显示其余关系。</p>
      <p v-if="data.scan_required" role="alert">正文或题目状态已变化，请重新扫描与审核。</p>
      <p v-if="data.unresolved_count > 0" class="relation-hint">
        先判断是否同题；同题进入归并预览，相关或不同题可单独入库。规则建议不会自动归并。
      </p>
      <p v-if="!data.candidates.length && !data.scan_required && !errorMessage">暂无相似题建议</p>
      <p v-if="deferredMessage" role="status">{{ deferredMessage }}</p>
      <ul v-if="data.candidates.length" aria-label="相似关系列表" class="relation-list">
        <li v-for="(relation, index) in data.candidates" :key="relation.id" :data-relation-id="relation.id" class="relation-row">
          <details :open="index === 0"><summary class="relation-summary"><span class="relation-question">#{{ relation.other_question.id }} · {{ relation.other_question.text }}</span><span class="badge" :class="relation.decision_status === 'suggested' ? 'warning' : 'accent'">{{ decisionLabel(relation) }}</span></summary>
          <p class="badge accent">{{ relation.match_kind === "exact" ? "完全重复（规范化文本）" : "近似建议" }} · 相似度 {{ relation.confidence?.toFixed(3) ?? "未知" }}</p>
          <RouterLink v-if="relation.other_question.canonical_question_id" :to="`/questions/${relation.other_question.canonical_question_id}`">查看题目</RouterLink>
          <div class="relation-actions"><button type="button" class="primary" :aria-label="`确认为同题并归并关系 ${relation.id}`" :disabled="loading || reviewing || disabled || !!errorMessage || data.scan_required" @click="decide(relation, 'same_question', 'accepted')">{{ relation.decision_status === 'accepted' && relation.relation_type === 'same_question' ? '继续归并' : '确认为同题并归并' }}</button><button type="button" :aria-label="`排除误报关系 ${relation.id}`" :disabled="loading || reviewing || disabled || !!errorMessage || data.scan_required" @click="decide(relation, 'same_question', 'rejected')">排除误报</button>
          <button type="button" :aria-label="`标记为相关题关系 ${relation.id}`" :disabled="loading || reviewing || disabled || !!errorMessage || data.scan_required" @click="decide(relation, 'related_question', 'accepted')">标记为相关题</button>
          <button type="button" :aria-label="`标记为不同题关系 ${relation.id}`" :disabled="loading || reviewing || disabled || !!errorMessage || data.scan_required" @click="decide(relation, 'different_question', 'accepted')">标记为不同题</button>
          <button type="button" :aria-label="`暂不处理关系 ${relation.id}`" :disabled="loading || reviewing || disabled" @click="deferredMessage = '保留建议，可稍后继续审核或归并。'">暂不处理</button></div></details>
        </li>
      </ul>
    </template>
    <QuestionMergeDialog v-if="mergeRelation" :key="`${questionId}:${contextKey}:${mergeRelation.id}`" :question-id="questionId" :text="text" :other-question="mergeRelation.other_question" :relation-id="mergeRelation.id" :pending-candidate="data?.candidate_state === 'pending_review'" @close="cancelMerge" @merged="merged" />
  </section>
</template>
