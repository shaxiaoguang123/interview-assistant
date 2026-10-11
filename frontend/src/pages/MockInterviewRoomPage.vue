<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { onBeforeRouteLeave, RouterLink, useRoute, useRouter } from "vue-router";
import { ApiError } from "../api/client";
import {
  askMockInterviewFollowUp,
  finishMockInterview,
  generateMockInterviewSummary,
  getMockInterview,
  moveToNextMockQuestion,
  saveMockInterview,
  type MockInterviewState,
} from "../api/mock-interviews";
import MockInterviewConversation from "../components/mock-interview/MockInterviewConversation.vue";
import MockInterviewSummary from "../components/mock-interview/MockInterviewSummary.vue";

const route = useRoute();
const router = useRouter();
const session = ref<MockInterviewState | null>(null);
const answerDraft = ref("");
const recordTitle = ref("");
const errorMessage = ref("");
const loading = ref(true);
const followingUp = ref(false);
const progressing = ref(false);
const summarizing = ref(false);
const saving = ref(false);
let loadRevision = 0;
const sessionId = computed(() => String(route.params.sessionId ?? ""));
const currentQuestion = computed(() => session.value?.current_question ?? null);
const isLastQuestion = computed(() => !!session.value && session.value.current_index >= session.value.question_count - 1);
const activeAction = computed(() => followingUp.value || progressing.value || summarizing.value || saving.value);

function describeError(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return "请求失败，请稍后重试。";
}

async function loadSession(): Promise<void> {
  const id = sessionId.value;
  const revision = ++loadRevision;
  loading.value = true;
  errorMessage.value = "";
  try {
    const result = await getMockInterview(id);
    if (revision !== loadRevision || id !== sessionId.value) return;
    session.value = result;
    recordTitle.value = `${result.topic_name} · 模拟面试`;
  } catch (error) {
    if (revision === loadRevision && id === sessionId.value) errorMessage.value = describeError(error);
  } finally {
    if (revision === loadRevision && id === sessionId.value) loading.value = false;
  }
}

async function refreshAfterFailure(): Promise<void> {
  const id = sessionId.value;
  try {
    const result = await getMockInterview(id);
    if (id === sessionId.value) session.value = result;
  } catch {
    // Preserve the local answer draft and the original request error.
  }
}

async function askFollowUp(): Promise<void> {
  const current = session.value;
  if (!current || !currentQuestion.value || followingUp.value || !answerDraft.value.trim()) return;
  const id = sessionId.value;
  const revision = current.revision;
  followingUp.value = true;
  errorMessage.value = "";
  try {
    const result = await askMockInterviewFollowUp(id, answerDraft.value, revision);
    if (id !== sessionId.value) return;
    session.value = result.session;
    answerDraft.value = "";
  } catch (error) {
    if (id === sessionId.value) {
      errorMessage.value = describeError(error);
      await refreshAfterFailure();
    }
  } finally {
    if (id === sessionId.value) followingUp.value = false;
  }
}

async function goNext(): Promise<void> {
  const current = session.value;
  if (!current || progressing.value || isLastQuestion.value) return;
  const id = sessionId.value;
  progressing.value = true;
  errorMessage.value = "";
  try {
    const result = await moveToNextMockQuestion(id, answerDraft.value, current.revision);
    if (id !== sessionId.value) return;
    session.value = result;
    answerDraft.value = "";
  } catch (error) {
    if (id === sessionId.value) {
      errorMessage.value = describeError(error);
      await refreshAfterFailure();
    }
  } finally {
    if (id === sessionId.value) progressing.value = false;
  }
}

async function endInterview(): Promise<void> {
  const current = session.value;
  if (!current || current.status === "ended" || activeAction.value) return;
  const id = sessionId.value;
  progressing.value = true;
  errorMessage.value = "";
  try {
    session.value = await finishMockInterview(id, answerDraft.value, current.revision);
    answerDraft.value = "";
  } catch (error) {
    errorMessage.value = describeError(error);
    await refreshAfterFailure();
  } finally {
    progressing.value = false;
  }
}

async function createSummary(): Promise<void> {
  if (!session.value || session.value.status !== "ended" || summarizing.value || session.value.summary) return;
  summarizing.value = true;
  errorMessage.value = "";
  const id = sessionId.value;
  try {
    const result = await generateMockInterviewSummary(id);
    if (id === sessionId.value) session.value = result.session;
  } catch (error) {
    if (id === sessionId.value) errorMessage.value = describeError(error);
  } finally {
    if (id === sessionId.value) summarizing.value = false;
  }
}

async function saveRecord(): Promise<void> {
  if (!session.value || session.value.status !== "ended" || saving.value) return;
  saving.value = true;
  errorMessage.value = "";
  const id = sessionId.value;
  try {
    const result = await saveMockInterview(id, recordTitle.value);
    if (id !== sessionId.value) return;
    session.value.saved_record_id = result.record.id;
    await router.push({ name: "mock-interview-saved", params: { id: result.record.id } });
  } catch (error) {
    if (id === sessionId.value) errorMessage.value = describeError(error);
  } finally {
    if (id === sessionId.value) saving.value = false;
  }
}

function beforeUnload(event: BeforeUnloadEvent): void {
  if (session.value && session.value.saved_record_id === null) {
    event.preventDefault();
    event.returnValue = "";
  }
}

onBeforeRouteLeave(() => {
  if (!session.value || session.value.saved_record_id !== null) return true;
  return window.confirm("这场面试尚未保存为长期记录。离开后临时会话不会进入历史记录，仍要离开吗？");
});

watch(sessionId, () => void loadSession(), { immediate: true });
window.addEventListener("beforeunload", beforeUnload);
onBeforeUnmount(() => {
  loadRevision++;
  window.removeEventListener("beforeunload", beforeUnload);
});
</script>

<template>
  <section class="mock-room-page" aria-labelledby="mock-room-title">
    <header class="page-heading">
      <div><span class="eyebrow">文字模拟面试 · 与普通练习分开</span><h2 id="mock-room-title">面试房间</h2><p v-if="session">{{ session.topic_name }} · 第 {{ Math.min(session.current_index + 1, session.question_count) }} / {{ session.question_count }} 题</p></div>
      <RouterLink to="/mock-interview">模拟面试首页</RouterLink>
    </header>

    <p v-if="loading" role="status">正在恢复临时面试…</p>
    <p v-if="errorMessage" role="alert">{{ errorMessage }}</p>
    <div v-if="!loading && !session && errorMessage" class="empty-state"><p>临时会话可能已过期或 Flask 已重新启动。</p><RouterLink to="/mock-interview">返回模拟面试</RouterLink></div>

    <template v-if="session">
      <div class="mock-room-meta">
        <progress aria-label="模拟面试进度" :value="session.current_index + (session.status === 'ended' ? 1 : 0)" :max="session.question_count" />
        <details v-if="session.context_sources.length" class="mock-room-context">
          <summary>本次 AI 可使用的资料（{{ session.context_sources.length }} 份）</summary>
          <ul><li v-for="source in session.context_sources" :key="source.material_version_id">{{ source.title }} · 第 {{ source.version_no }} 版</li></ul>
          <p>每次调用只检索所选资料中与当前题目和回答相关的片段，不会发送未选资料。</p>
        </details>
        <p v-else class="helper">本场没有选择个人资料；AI 只会参考当前题目和本题对话。</p>
      </div>

      <div v-if="currentQuestion && session.status === 'active'" class="mock-room-grid">
        <article class="mock-current-question panel">
          <span class="badge">题库原题 · #{{ currentQuestion.id }}</span>
          <h3>{{ currentQuestion.text }}</h3>
          <p class="helper">先用自己的话回答。AI 追问是可选的，不会自动生成。</p>
          <label for="mock-answer">你的回答<textarea id="mock-answer" v-model="answerDraft" aria-label="模拟面试回答" maxlength="10000" placeholder="输入本轮回答……" :disabled="activeAction" /></label>
          <p class="mock-character-count">{{ answerDraft.length }} / 10,000</p>
          <div v-if="!session.llm_configured" class="mock-llm-notice" role="status"><span>尚未配置模型。你可以继续作答、跳过追问并保存记录。</span><RouterLink to="/settings">模型设置</RouterLink></div>
          <div class="action-row mock-room-actions">
            <button type="button" class="primary" :disabled="activeAction || !session.llm_configured || !answerDraft.trim()" @click="askFollowUp">{{ followingUp ? "面试官正在思考…" : "让 AI 继续追问" }}</button>
            <button v-if="!isLastQuestion" type="button" :disabled="activeAction" @click="goNext">{{ progressing ? "正在进入下一题…" : "跳过追问，进入下一题" }}</button>
            <button type="button" :disabled="activeAction" @click="endInterview">结束本场面试</button>
          </div>
          <p class="helper">点击 AI 追问会发送本题和你当前输入的回答，以及上方选中的资料片段。</p>
        </article>
        <aside class="mock-room-dialogue"><h3>本题对话</h3><MockInterviewConversation :turns="session.turns.filter((turn) => turn.question_id === currentQuestion?.id)" /></aside>
      </div>

      <section v-if="session.status === 'ended'" class="mock-finished-workspace">
        <div class="panel mock-finished-card">
          <span class="badge success">本场已结束</span>
          <h3>保存回答记录，或生成 AI 建议</h3>
          <p class="helper">临时会话暂存在当前 Flask 进程中。只有明确保存后才会进入历史记录；重启服务前请先保存。</p>
          <div v-if="!session.summary && !session.llm_configured" class="mock-llm-notice" role="status"><span>模型未配置，仍可保存完整对话记录。</span><RouterLink to="/settings">模型设置</RouterLink></div>
          <p v-if="!session.summary && session.llm_configured" class="helper">生成总结会发送本场题目、你的回答和所选资料中的相关片段；结果只作为 AI 建议，不会自动保存。</p>
          <button v-if="!session.summary" type="button" class="primary" :disabled="activeAction || !session.llm_configured" @click="createSummary">{{ summarizing ? "正在生成建议…" : "生成 AI 面试总结" }}</button>
          <label>记录标题<input v-model="recordTitle" aria-label="记录标题" maxlength="240" :disabled="saving" /></label>
          <button type="button" :disabled="activeAction" @click="saveRecord">{{ saving ? "正在保存…" : session.saved_record_id ? "打开已保存记录" : "保存本次模拟面试" }}</button>
        </div>
        <MockInterviewSummary v-if="session.summary" :summary="session.summary" />
        <section v-if="session.summary_sources.length" class="panel mock-summary-sources" aria-label="总结使用的资料来源">
          <h3>总结引用的资料版本</h3>
          <ul><li v-for="source in session.summary_sources" :key="source.material_version_id">{{ source.title }} · 第 {{ source.version_no }} 版 · 片段 {{ source.chunk_ids.join(", ") || "无片段" }}</li></ul>
        </section>
        <MockInterviewConversation :turns="session.turns" />
      </section>
    </template>
  </section>
</template>

<style scoped>
.mock-room-page { display: grid; gap: 20px; }
.mock-room-meta { display: grid; gap: 10px; }
.mock-room-meta progress { margin: 0; }
.mock-room-context { padding: 10px 14px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface); }
.mock-room-context ul { margin: 0 0 8px; }
.mock-room-context p { margin: 0; color: var(--muted); font-size: 13px; }
.mock-room-grid { display: grid; grid-template-columns: minmax(0, 1.1fr) minmax(300px, .9fr); gap: 24px; align-items: start; }
.mock-current-question { display: grid; gap: 14px; }
.mock-current-question h3 { margin: 0; font-size: 22px; line-height: 1.65; white-space: pre-wrap; overflow-wrap: anywhere; }
.mock-current-question label { margin-top: 4px; }
.mock-current-question textarea { min-height: 200px; }
.mock-character-count { margin: -10px 0 0; text-align: right; color: var(--muted); font-size: 12px; }
.mock-room-actions { margin-top: 2px; }
.mock-room-dialogue { display: grid; gap: 12px; min-width: 0; }
.mock-room-dialogue h3 { margin: 0; }
.mock-llm-notice { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px; padding: 12px 14px; color: var(--warning); background: var(--warning-soft); border-radius: 8px; font-size: 13px; }
.mock-finished-workspace { display: grid; gap: 20px; }
.mock-finished-card { display: grid; gap: 12px; }
.mock-finished-card h3,.mock-finished-card p { margin: 0; }
.mock-finished-card label { max-width: 600px; }
.mock-summary-sources h3 { margin-bottom: 8px; }
.mock-summary-sources ul { margin: 0; overflow-wrap: anywhere; }
@media (max-width: 900px) { .mock-room-grid { grid-template-columns: minmax(0, 1fr); } }
@media (max-width: 680px) { .mock-room-actions { display: grid; grid-template-columns: 1fr; } .mock-room-actions button { width: 100%; } .mock-current-question h3 { font-size: 19px; } }
</style>
