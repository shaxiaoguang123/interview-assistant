<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { RouterLink } from "vue-router";
import { ApiError } from "../../api/client";
import { getSavedAnswers, type SavedAnswer } from "../../api/saved-answers";
import {
  exportMockInterviewAnswer,
  type MockInterviewAnswerExportResult,
  type MockInterviewTurn,
} from "../../api/mock-interviews";

interface SavedTurn extends MockInterviewTurn {
  id: number;
}

const props = defineProps<{ recordId: number; turn: SavedTurn }>();
const emit = defineEmits<{ saved: [result: MockInterviewAnswerExportResult] }>();

const open = ref(false);
const loading = ref(false);
const loadFailed = ref(false);
const saving = ref(false);
const errorMessage = ref("");
const answers = ref<SavedAnswer[]>([]);
const saveMode = ref<"new_answer" | "append_version">("new_answer");
const selectedAnswerId = ref<number | null>(null);
const content = ref(props.turn.text);
const selfRating = ref("");
const success = ref<MockInterviewAnswerExportResult | null>(null);
const canAppend = computed(() => answers.value.length > 0);
let revision = 0;

function errorText(error: unknown): string {
  return error instanceof ApiError ? error.message : "保存失败，编辑内容已保留，请重试。";
}

async function openEditor(): Promise<void> {
  if (props.turn.answer_export || success.value) return;
  const current = ++revision;
  open.value = true;
  loading.value = true;
  loadFailed.value = false;
  errorMessage.value = "";
  try {
    const result = await getSavedAnswers(props.turn.question_id);
    if (current !== revision) return;
    answers.value = result.filter((answer) => !answer.archived_at);
    if (answers.value.length) {
      selectedAnswerId.value = answers.value[0].id;
    } else {
      saveMode.value = "new_answer";
    }
  } catch (error) {
    if (current === revision) {
      loadFailed.value = true;
      errorMessage.value = errorText(error);
    }
  } finally {
    if (current === revision) loading.value = false;
  }
}

function changeMode(value: string): void {
  if (value === "append_version" && !canAppend.value) {
    saveMode.value = "new_answer";
    return;
  }
  saveMode.value = value === "append_version" ? "append_version" : "new_answer";
}

async function submit(): Promise<void> {
  if (saving.value || !content.value.trim() || !Number.isSafeInteger(props.turn.id)) return;
  if (saveMode.value === "append_version" && selectedAnswerId.value === null) {
    errorMessage.value = "请选择要追加版本的已有回答。";
    return;
  }
  const requestRevision = revision;
  saving.value = true;
  errorMessage.value = "";
  try {
    const result = await exportMockInterviewAnswer(props.recordId, props.turn.id, {
      save_mode: saveMode.value,
      ...(saveMode.value === "append_version" && selectedAnswerId.value !== null
        ? { saved_answer_id: selectedAnswerId.value }
        : {}),
      content: content.value.trim(),
      self_rating: selfRating.value ? Number(selfRating.value) : null,
    });
    if (requestRevision !== revision) return;
    success.value = result;
    open.value = false;
    emit("saved", result);
  } catch (error) {
    if (requestRevision === revision) errorMessage.value = errorText(error);
  } finally {
    if (requestRevision === revision) saving.value = false;
  }
}

watch(
  () => [props.recordId, props.turn.id] as const,
  () => {
    revision++;
    open.value = false;
    loading.value = false;
    loadFailed.value = false;
    saving.value = false;
    errorMessage.value = "";
    answers.value = [];
    saveMode.value = "new_answer";
    selectedAnswerId.value = null;
    content.value = props.turn.text;
    selfRating.value = "";
    success.value = null;
  },
);
onBeforeUnmount(() => { revision++; });

const exportState = computed(() => {
  if (success.value) return {
    answerId: success.value.saved_answer.id,
    versionNo: success.value.version.version_no,
  };
  const saved = props.turn.answer_export;
  return saved ? { answerId: saved.saved_answer_id, versionNo: saved.version_no } : null;
});
</script>

<template>
  <div class="mock-answer-export">
    <p v-if="exportState" class="exported-answer" role="status">
      已保存为题库回答 #{{ exportState.answerId }} · v{{ exportState.versionNo }}
      <span>来源：模拟面试 #{{ recordId }}</span>
      <RouterLink :to="`/questions/${turn.question_id}`">查看题目与回答</RouterLink>
    </p>
    <template v-else>
      <button type="button" :aria-expanded="open" @click="open ? (open = false) : openEditor()">{{ open ? "收起回答导出" : "保存为题库回答" }}</button>
      <section v-if="open" class="export-editor" aria-label="保存模拟面试回答">
        <h4>保存这条手写回答</h4>
        <p class="source-question"><strong>原题：</strong>{{ turn.question_text }}</p>
        <label>原始面试回答<textarea :value="turn.text" readonly rows="3" /></label>
        <label>最终保存内容<textarea v-model="content" aria-label="最终保存内容" maxlength="100000" rows="6" :disabled="saving" /></label>
        <label>保存方式
          <select :value="saveMode" aria-label="保存方式" :disabled="loading || saving" @change="changeMode(($event.target as HTMLSelectElement).value)">
            <option value="new_answer">保存为新回答</option>
            <option value="append_version" :disabled="!canAppend">追加为已有回答的新版本</option>
          </select>
        </label>
        <label v-if="saveMode === 'append_version'">追加到回答
          <select v-model.number="selectedAnswerId" aria-label="选择已有回答" :disabled="saving">
            <option v-for="answer in answers" :key="answer.id" :value="answer.id">
              回答 #{{ answer.id }} · 当前 v{{ answer.current_version.version_no }}
            </option>
          </select>
        </label>
        <label>答案质量评分（可选）
          <select v-model="selfRating" aria-label="答案质量评分" :disabled="saving">
            <option value="">不评分</option>
            <option v-for="rating in 5" :key="rating" :value="String(rating)">{{ rating }} 分</option>
          </select>
        </label>
        <p v-if="loading" role="status">正在读取这道题的已有回答…</p>
        <p v-if="errorMessage" role="alert">{{ errorMessage }} <button v-if="loadFailed" type="button" :disabled="loading" @click="openEditor">重试加载已有回答</button></p>
        <div class="action-row">
          <button type="button" class="primary" aria-label="确认保存回答" :disabled="loading || saving || loadFailed || !content.trim()" @click="submit">{{ saving ? "正在保存…" : "确认保存回答" }}</button>
          <button type="button" :disabled="saving" @click="open = false">取消</button>
        </div>
        <p class="helper">本次来源会关联到这场已保存的模拟面试和原题快照。质量评分不会改变练习掌握度或复习日期。</p>
      </section>
    </template>
  </div>
</template>

<style scoped>
.mock-answer-export { display: grid; gap: 10px; margin-top: 10px; }
.export-editor { display: grid; gap: 12px; margin-top: 10px; padding: 16px; border: 1px solid var(--border); border-radius: 10px; background: var(--canvas); }
.export-editor h4, .source-question { margin: 0; }
.export-editor textarea { margin-top: 6px; min-height: 82px; }
.export-editor select { margin-top: 6px; }
.export-editor .helper { margin: 0; }
.exported-answer { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 14px; margin: 0; color: var(--success); font-size: 13px; }
.exported-answer span { color: var(--muted); }
@media (max-width: 680px) { .export-editor { padding: 12px; } .export-editor .action-row { display: grid; grid-template-columns: 1fr; } .export-editor .action-row button { width: 100%; } }
</style>
