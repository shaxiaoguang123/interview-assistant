<script setup lang="ts">
import type { MockInterviewTurn } from "../../api/mock-interviews";

defineProps<{ turns: MockInterviewTurn[] }>();
const labels = { question: "题库原题", answer: "你的回答", follow_up: "AI 面试官追问" } as const;
</script>

<template>
  <ol class="mock-conversation" aria-label="模拟面试对话">
    <li v-for="turn in turns" :key="turn.ordinal" class="mock-turn" :class="`turn-${turn.kind}`">
      <div class="mock-turn-heading"><strong>{{ labels[turn.kind] }}</strong><span>题目 #{{ turn.question_id }}</span></div>
      <p class="mock-turn-content">{{ turn.text }}</p>
      <ul v-if="turn.sources.length" class="mock-turn-sources" aria-label="追问参考资料">
        <li v-for="source in turn.sources" :key="source.material_version_id">
          引用：{{ source.title }} · 第 {{ source.version_no }} 版 · 资料片段 {{ source.chunk_ids.join(", ") || "已选版本" }}
        </li>
      </ul>
    </li>
  </ol>
</template>

<style scoped>
.mock-conversation { display: grid; gap: 12px; margin: 0; padding: 0; list-style: none; }
.mock-turn { min-width: 0; padding: 16px 18px; background: var(--surface); border: 1px solid var(--border); border-left: 3px solid #9babc0; border-radius: 10px; }
.turn-answer { background: #f9fbfd; border-left-color: var(--brand); }
.turn-follow_up { border-left-color: #8b72b4; }
.mock-turn-heading { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 12px; font-size: 13px; }
.mock-turn-heading span { color: var(--muted); font-size: 12px; }
.mock-turn-content { margin: 8px 0 0; white-space: pre-wrap; overflow-wrap: anywhere; }
.mock-turn-sources { padding-left: 18px; margin: 10px 0 0; color: var(--muted); font-size: 12px; }
@media (max-width: 680px) { .mock-turn { padding: 14px; } }
</style>
