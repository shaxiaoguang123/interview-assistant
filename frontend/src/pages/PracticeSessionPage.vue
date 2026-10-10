<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { RouterLink, useRoute } from "vue-router";
import { ApiError, request } from "../api/client";
import { formatReviewTime, type ReviewSchedule } from "../api/progress";
import PracticeRating from "../components/PracticeRating.vue";
import { createSavedAnswer } from "../api/saved-answers";

interface SessionItem {
  id: number;
  question_id: number;
  ordinal: number;
  status: "shown" | "completed" | "skipped";
  question: { id: number; text: string; status: string; archived_at: string | null };
}

interface PracticeSession {
  id: number;
  mode: string;
  selector_version: string;
  selection_seed: number | null;
  started_at: string;
  completed_at: string | null;
  items: SessionItem[];
}

const route = useRoute();
const practiceSession = ref<PracticeSession | null>(null);
const answerDraft = ref("");
const errorMessage = ref("");
const loading = ref(true);
const skipping = ref(false);
const reviewing = ref(false);
const saving = ref(false);
const saveChoice = ref<{item:SessionItem;reviewId:number;rating:string;schedule?:ReviewSchedule}|null>(null);
const savedAnswerId = ref<number|null>(null);
const qualityRating = ref<number|null>(null);
const masteryLabel:Record<string,string>={dont_know:'不会',vague:'模糊',basic:'基本会',proficient:'熟练'};
const sessionId = computed(() => Number(route.params.id));
let loadRevision = 0;
const completedCount = computed(() => practiceSession.value?.items.filter(i => i.status !== 'shown').length ?? 0);
function currentRequest(id: number, revision: number) { return sessionId.value === id && loadRevision === revision; }
const currentItem = computed(
  () => saveChoice.value?.item ?? practiceSession.value?.items.find((item) => item.status === "shown") ?? null,
);

function displayError(error: unknown): string {
  if (error instanceof ApiError) {
    const details = Object.values(error.fields);
    return details.length ? `${error.message}: ${details.join("；")}` : error.message;
  }
  return "请求失败，请稍后重试。";
}

async function loadSession(): Promise<void> {
  const id = sessionId.value;
  const revision = ++loadRevision;
  practiceSession.value = null;
  answerDraft.value = "";
  skipping.value = false;
  reviewing.value = false;
  saving.value = false;
  saveChoice.value = null;
  savedAnswerId.value = null;
  qualityRating.value = null;
  loading.value = true;
  errorMessage.value = "";
  try {
    const result = await request<PracticeSession>(`/api/v1/practice-sessions/${id}`);
    if (currentRequest(id, revision)) practiceSession.value = result;
  } catch (error) {
    if (currentRequest(id, revision)) errorMessage.value = displayError(error);
  } finally {
    if (currentRequest(id, revision)) loading.value = false;
  }
}

async function skipCurrentItem(): Promise<void> {
  if (!currentItem.value || skipping.value || reviewing.value || saveChoice.value) return;
  const id = sessionId.value;
  const revision = loadRevision;
  const itemId = currentItem.value.id;
  errorMessage.value = "";
  skipping.value = true;
  try {
    await request(`/api/v1/session-items/${itemId}/skip`, { method: "POST" });
    if (!currentRequest(id, revision)) return;
    answerDraft.value = "";
    await loadSession();
  } catch (error) {
    if (currentRequest(id, revision)) errorMessage.value = displayError(error);
  } finally {
    if (currentRequest(id, revision)) skipping.value = false;
  }
}

async function recordRating(reviewRating: string): Promise<void> {
  if (!currentItem.value || skipping.value || reviewing.value || saveChoice.value) return;
  const id = sessionId.value;
  const revision = loadRevision;
  const itemId = currentItem.value.id;
  const item = {...currentItem.value};
  errorMessage.value = "";
  reviewing.value = true;
  try {
    const review = await request<{id:number;review_schedule?:ReviewSchedule}>(`/api/v1/session-items/${itemId}/review`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ review_rating: reviewRating }),
    });
    if (!currentRequest(id, revision)) return;
    saveChoice.value = {item,reviewId:review.id,rating:reviewRating,schedule:review.review_schedule};
    const session = practiceSession.value;
    if (session) {
      const original = session.items.find(i=>i.id===itemId);
      if(original)original.status='completed';
      if(session.items.every(i=>i.status!=='shown'))session.completed_at=new Date().toISOString();
    }
  } catch (error) {
    if (currentRequest(id, revision)) errorMessage.value = displayError(error);
  } finally {
    if (currentRequest(id, revision)) reviewing.value = false;
  }
}

function rewriteDraft(): void {
  answerDraft.value = "";
}

async function saveAnswer():Promise<void>{
  const choice=saveChoice.value;
  if(!choice || saving.value || savedAnswerId.value || !answerDraft.value.trim())return;
  const id=sessionId.value,revision=loadRevision;
  saving.value=true;errorMessage.value='';
  try {
    const answer=await createSavedAnswer(choice.item.question_id,{content:answerDraft.value,self_rating:qualityRating.value,
      source_session_item_id:choice.item.id,source_practice_review_id:choice.reviewId});
    if(currentRequest(id,revision))savedAnswerId.value=answer.id;
  }catch(e){if(currentRequest(id,revision))errorMessage.value=displayError(e);}
  finally{if(currentRequest(id,revision))saving.value=false;}
}

watch(sessionId, () => void loadSession(), {immediate:true});
onBeforeUnmount(()=>loadRevision++);
</script>

<template>
  <section aria-labelledby="practice-session-title" class="practice-session">
    <p v-if="loading">正在加载练习…</p>
    <template v-if="errorMessage">
      <p role="alert">{{ errorMessage }}</p>
      <button
        v-if="!practiceSession"
        type="button"
        aria-label="重试加载练习"
        @click="loadSession"
      >
        重试加载
      </button>
    </template>
    <template v-if="!loading && practiceSession">
      <header class="page-heading"><div><span class="eyebrow">Practice room</span><h2 id="practice-session-title">练习会话 #{{ practiceSession.id }}</h2><p>完成 {{ completedCount }} / {{ practiceSession.items.length }} · 掌握程度由你自己判断</p></div></header>
      <progress aria-label="练习完成进度" :value="completedCount" :max="Math.max(1, practiceSession.items.length)" />
      <div class="practice-workspace"><div class="practice-question">
      <p v-if="practiceSession.completed_at && !saveChoice">本次练习已完成</p>
      <template v-else-if="currentItem">
        <p>第 {{ currentItem.ordinal }} 题</p>
        <h3>{{ currentItem.question.text }}</h3>
        <p v-if="currentItem.question.status === 'merged'" class="helper">这是归并前的历史题目，仍可完成本次练习；记录保留原题 #{{ currentItem.question_id }}。</p>
        <p v-if="currentItem.question.archived_at">此题已归档；仍可完成当前练习。</p>
        <label>
          临时回答
          <textarea v-model="answerDraft" aria-label="临时回答" :disabled="reviewing || skipping || saving || !!savedAnswerId" />
        </label>
        <template v-if="!saveChoice"><p class="helper">临时回答不会自动保存。先评价掌握程度，再决定是否保存这份回答。</p>
        <button type="button" :disabled="reviewing || skipping" @click="rewriteDraft">重新回答</button>
        <PracticeRating :disabled="reviewing || skipping" @rate="recordRating" />
        <button type="button" :disabled="skipping || reviewing" @click="skipCurrentItem">
          {{ skipping ? "正在跳过…" : "跳过此题" }}
        </button>
        </template>
        <section v-else class="practice-save-choice" aria-label="保存本次回答">
          <p role="status">掌握度已记录：{{ masteryLabel[saveChoice.rating] }}。{{ practiceSession.completed_at?'本次练习已完成，仍可保存这份回答。':'正文已保留，请决定是否保存。' }}</p>
          <p v-if="saveChoice.schedule?.next_review_at" class="review-next" role="status">下次复习：{{ formatReviewTime(saveChoice.schedule.next_review_at) }} <span class="helper">（按本次掌握度固定间隔安排）</span></p>
          <template v-if="!savedAnswerId"><label class="practice-quality">答案质量评分（可选）<select v-model="qualityRating" aria-label="本次答案质量评分" :disabled="saving"><option :value="null">暂不评分</option><option v-for="n in 5" :key="n" :value="n">{{ n }} 分</option></select></label><p class="helper">质量评分评价这份答案，与上面的四级掌握度独立。</p><div class="action-row"><button class="primary" :disabled="saving || !answerDraft.trim()" @click="saveAnswer">{{ saving?'正在保存…':'保存本次回答' }}</button><button :disabled="saving" @click="loadSession">不保存，{{ practiceSession.completed_at?'结束练习':'继续下一题' }}</button></div></template>
          <template v-else><p class="success-banner">回答 #{{ savedAnswerId }} 已保存，并保留本次练习来源。</p><div class="action-row"><RouterLink :to="`/questions/${saveChoice.item.question_id}`">查看保存回答</RouterLink><button class="primary" @click="loadSession">{{ practiceSession.completed_at?'完成练习':'继续下一题' }}</button></div></template>
        </section>
      </template>
      <p v-else>当前会话没有待练习题目。</p>

      </div><aside aria-label="本次练习队列"><h3>本次题目</h3><ol aria-label="练习题目顺序" class="practice-queue">
        <li v-for="item in practiceSession.items" :key="item.id">
          <span>{{ item.ordinal }}. {{ item.question.text }}</span>
          <span class="muted">{{ {shown:"待练习",completed:"已完成",skipped:"已跳过"}[item.status] }} · 原题 #{{ item.question_id }}</span>
        </li>
      </ol></aside></div>
    </template>
  </section>
</template>
<style scoped>
.practice-save-choice{margin-top:24px;padding:20px;border:1px solid var(--brand);border-radius:12px;background:var(--brand-soft);}
.practice-question .practice-quality{display:flex;flex-direction:row;gap:12px;align-items:center;flex-wrap:wrap;margin:16px 0;}
.practice-question textarea{min-height:240px;font-weight:400;}
</style>
