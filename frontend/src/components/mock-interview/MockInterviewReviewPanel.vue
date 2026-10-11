<script setup lang="ts">
import { computed } from "vue";
import { RouterLink } from "vue-router";
import MockInterviewConversation from "./MockInterviewConversation.vue";
import MockInterviewAnswerExport from "./MockInterviewAnswerExport.vue";
import type { MockInterviewAnswerExportResult, MockInterviewTurn } from "../../api/mock-interviews";

interface SavedTurn extends MockInterviewTurn {
  id: number;
}

interface QuestionReview {
  questionId: number;
  questionText: string;
  turns: SavedTurn[];
}

const props = defineProps<{ recordId: number; turns: SavedTurn[] }>();
const emit = defineEmits<{ exported: [result: MockInterviewAnswerExportResult] }>();

const groups = computed<QuestionReview[]>(() => {
  const grouped = new Map<number, QuestionReview>();
  for (const turn of props.turns) {
    let group = grouped.get(turn.question_id);
    if (!group) {
      group = { questionId: turn.question_id, questionText: turn.question_text, turns: [] };
      grouped.set(turn.question_id, group);
    }
    if (turn.kind === "question") {
      group.questionText = turn.question_text;
    } else {
      group.turns.push(turn);
    }
  }
  return [...grouped.values()];
});

const labels: Record<MockInterviewTurn["kind"], string> = {
  question: "原始面试题",
  answer: "你的回答",
  follow_up: "AI 面试官追问",
};
</script>

<template>
  <section class="mock-review-panel" aria-labelledby="mock-review-title">
    <header class="review-heading">
      <div><span class="eyebrow">按题目复盘</span><h3 id="mock-review-title">回答与追问</h3></div>
      <span class="badge">{{ groups.length }} 道题</span>
    </header>
    <p v-if="!groups.length" class="empty-state">这场记录没有可显示的对话。</p>
    <div v-else class="review-groups">
      <article v-for="group in groups" :key="group.questionId" class="review-question panel">
        <header class="question-heading">
          <div><span class="eyebrow">原题 #{{ group.questionId }}</span><h4>{{ group.questionText }}</h4></div>
          <RouterLink :to="`/questions/${group.questionId}`">查看原题</RouterLink>
        </header>
        <div class="review-turns">
          <section v-for="turn in group.turns" :key="turn.id" class="review-turn" :class="`turn-${turn.kind}`">
            <div class="turn-heading"><strong>{{ labels[turn.kind] }}</strong><time :datetime="turn.created_at">{{ new Date(turn.created_at).toLocaleString("zh-CN", { dateStyle: "short", timeStyle: "short" }) }}</time></div>
            <p>{{ turn.text }}</p>
            <MockInterviewAnswerExport
              v-if="turn.kind === 'answer'"
              :record-id="recordId"
              :turn="turn"
              @saved="emit('exported', $event)"
            />
          </section>
        </div>
      </article>
    </div>
    <details class="review-timeline">
      <summary>查看完整对话时间线</summary>
      <MockInterviewConversation :turns="turns" />
    </details>
  </section>
</template>

<style scoped>
.mock-review-panel { display: grid; gap: 16px; }
.review-heading, .question-heading, .turn-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.review-heading h3, .question-heading h4 { margin: 0; }
.review-groups { display: grid; gap: 14px; }
.review-question { display: grid; gap: 14px; }
.question-heading h4 { margin-top: 6px; line-height: 1.6; overflow-wrap: anywhere; }
.review-turns { display: grid; gap: 10px; }
.review-turn { min-width: 0; padding: 14px; border-radius: 9px; background: var(--canvas); }
.turn-follow_up { border-left: 3px solid var(--brand); }
.turn-heading { align-items: center; color: var(--muted); font-size: 12px; }
.review-turn p { margin: 8px 0 0; white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.75; }
.review-turn time { white-space: nowrap; }
.review-timeline { padding-top: 8px; border-top: 1px solid var(--border); }
.review-timeline summary { cursor: pointer; font-weight: 600; }
.review-timeline > :deep(.mock-conversation) { margin-top: 12px; }
@media (max-width: 680px) {
  .question-heading { flex-direction: column; }
  .review-question { padding: 14px; }
  .review-turn { padding: 12px; }
  .turn-heading { align-items: flex-start; flex-direction: column; gap: 4px; }
}
</style>
