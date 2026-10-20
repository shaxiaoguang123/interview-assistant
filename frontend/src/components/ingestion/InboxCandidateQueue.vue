<script setup lang="ts">
import { computed } from "vue";
import type { IngestionCandidate } from "../../api/ingestion";

const props = defineProps<{
  jobId: number;
  candidates: IngestionCandidate[];
  loaded: boolean;
  pendingCount: number;
  selectedCandidateId: number | null;
  selectedMergeIds: number[];
  mergeFinalText: string;
  busy: boolean;
}>();

const emit = defineEmits<{
  select: [candidate: IngestionCandidate];
  "update:selectedMergeIds": [ids: number[]];
  "update:mergeFinalText": [text: string];
  merge: [];
}>();

const selectedCandidate = computed(() =>
  props.candidates.find((candidate) => candidate.id === props.selectedCandidateId) ?? null,
);

function stateLabel(value: string): string {
  return ({ pending_review: "待审核", confirmed: "已确认", rejected: "已拒绝", superseded: "已替换" } as Record<string, string>)[value] ?? value;
}

function toggleMerge(id: number, event: Event) {
  const checked = (event.target as HTMLInputElement).checked;
  emit(
    "update:selectedMergeIds",
    checked
      ? [...new Set([...props.selectedMergeIds, id])]
      : props.selectedMergeIds.filter((item) => item !== id),
  );
}
</script>

<template>
  <section class="candidate-queue" aria-label="当前任务候选题">
    <header class="inbox-section-heading">
      <div><span class="eyebrow">任务 {{ jobId }}</span><h3>候选题</h3></div>
      <span class="badge warning">{{ pendingCount }} 待确认</span>
    </header>
    <p v-if="loaded" class="queue-count" aria-label="候选数量统计">
      历史候选 {{ candidates.length }} · 待确认 {{ pendingCount }}
    </p>
    <ul aria-label="候选题历史" class="candidate-list">
      <li v-for="candidate in candidates" :key="candidate.id">
        <input
          v-if="candidate.candidate_state === 'pending_review' && !candidate.archived_at"
          type="checkbox"
          :checked="selectedMergeIds.includes(candidate.id)"
          :aria-label="'选择 OCR 候选区域 ' + candidate.id"
          @change="toggleMerge(candidate.id, $event)"
        />
        <button
          type="button"
          :aria-label="'查看候选题 ' + candidate.id"
          :aria-pressed="candidate.id === selectedCandidateId"
          @click="emit('select', candidate)"
        >
          <span class="candidate-title">{{ candidate.text }}</span>
          <span class="badge" :class="candidate.status === 'merged' ? 'accent' : candidate.candidate_state === 'pending_review' ? 'warning' : candidate.candidate_state === 'confirmed' ? 'success' : ''">
            {{ candidate.status === "merged" ? "已归并" : stateLabel(candidate.candidate_state) }}
          </span>
        </button>
        <span class="candidate-source-label">来源区域 {{ candidate.sources.map((item) => item.question_source_id).join(", ") }}</span>
        <span v-if="candidate.split_from_candidate_id" class="candidate-lineage">拆分自候选 #{{ candidate.split_from_candidate_id }}</span>
        <span v-if="candidate.split_child_ids.length" class="candidate-lineage">
          已拆分为候选 {{ candidate.split_child_ids.map((id) => "#" + id).join("、") }}
        </span>
        <span v-if="candidate.superseded_by_candidate_id" class="candidate-lineage">
          已合并至候选 #{{ candidate.superseded_by_candidate_id }}
        </span>
      </li>
    </ul>
    <p v-if="loaded && candidates.length === 0" class="empty-state">当前任务还没有候选题。</p>
    <details
      v-if="selectedCandidate && selectedCandidate.candidate_state === 'pending_review' && !selectedCandidate.archived_at"
      class="candidate-extras"
    >
      <summary>合并同一截图的候选边界</summary>
      <form aria-label="候选题同任务合并" @submit.prevent="emit('merge')">
        <label>
          合并后正文
          <textarea
            aria-label="合并后题目正文"
            :value="mergeFinalText"
            @input="emit('update:mergeFinalText', ($event.target as HTMLTextAreaElement).value)"
          />
        </label>
        <button type="submit" :disabled="busy">合并 OCR 候选区域</button>
      </form>
    </details>
  </section>
</template>
