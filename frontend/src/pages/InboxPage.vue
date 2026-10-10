<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { ApiError, request } from "../api/client";
import IngestionCandidateEditor from "../components/IngestionCandidateEditor.vue";
import QuestionRelationReview from "../components/QuestionRelationReview.vue";
import type { RelationReviewState } from "../api/question-relations";
import SourceImageViewer from "../components/SourceImageViewer.vue";
import SourceUpload from "../components/SourceUpload.vue";

interface IngestionJob {
  id: number;
  source_asset_id: number;
  status: string;
  stage: string;
  failure_stage: string | null;
  engine: string | null;
  engine_version: string | null;
  error_code: string | null;
  error_message: string | null;
  candidate_count: number; // Automatically grouped candidates created by the OCR run.
}

interface SourceAsset {
  id: number;
  source_type: string;
  title: string | null;
  original_filename: string | null;
  mime_type: string;
  byte_size: number;
  original_width: number;
  original_height: number;
  display_width: number;
  display_height: number;
  sha256: string;
  archived_at: string | null;
  ingestion_jobs: IngestionJob[];
}

interface UploadResult {
  status: "stored" | "rejected";
  source?: SourceAsset;
  job?: IngestionJob;
  error?: { code: string; message: string; fields: Record<string, string> };
  filename?: string;
}

interface Candidate {
  id: number;
  text: string;
  status: string;
  archived_at: string | null;
  candidate_state: string;
  candidate_revision: number;
  split_from_candidate_id: number | null;
  split_child_ids: number[];
  superseded_by_candidate_id: number | null;
  topics: Array<{ id: number; name: string; is_active: boolean }>;
  tags: Array<{ id: number; name: string; is_active: boolean }>;
  sources: Array<{
    question_source_id: number;
    source_asset_id: number;
    locator_json: { x: number; y: number; width: number; height: number };
    locator_correction_json: { x: number; y: number; width: number; height: number } | null;
    source_text_snapshot: string;
    raw_ocr_text_snapshot: string;
    confidence: number | null;
    ocr_blocks: Array<{
      id: string;
      text: string;
      bbox: { x: number; y: number; width: number; height: number };
      reading_order: number;
    }>;
  }>;
}

interface OCRBlock {
  id: string;
  text: string;
  bbox: { x: number; y: number; width: number; height: number };
  reading_order: number;
  confidence: number | null;
}

interface TaxonomyItem {
  id: number;
  name: string;
  is_active: boolean;
}

const sources = ref<SourceAsset[]>([]);
const topics = ref<TaxonomyItem[]>([]);
const tags = ref<TaxonomyItem[]>([]);
const uploadResults = ref<UploadResult[]>([]);
const selectedJobId = ref<number | null>(null);
const selectedCandidateId = ref<number | null>(null);
const selectedSourceId = ref<number | null>(null);
const candidates = ref<Candidate[]>([]);
const candidateHistoryLoaded = ref(false);
const ocrBlocks = ref<OCRBlock[]>([]);
const busy = ref(false);
const loadError = ref("");
const historyError = ref("");
const candidateBusy = ref(false);
const selectedMergeIds = ref<number[]>([]);
const mergeFinalText = ref("");
const manualCreateOpen = ref(false);
const manualBlockIds = ref<string[]>([]);
const manualCandidateText = ref("");
const relationReviewState = ref<RelationReviewState | null>(null);
const candidateSelectionRevision = ref(0);
let jobLoadRevision = 0;

const jobs = computed(() =>
  sources.value.flatMap((source) =>
    source.ingestion_jobs.map((job) => ({ ...job, source })),
  ),
);
const selectedJob = computed(() => jobs.value.find((item) => item.id === selectedJobId.value) ?? null);
const selectedCandidate = computed(
  () => candidates.value.find((candidate) => candidate.id === selectedCandidateId.value) ?? null,
);
const relationContextKey = computed(() => `${selectedJobId.value}:${candidateSelectionRevision.value}:${selectedCandidate.value?.candidate_revision}`);
const canConfirmSelectedCandidate = computed(() =>
  relationReviewState.value?.questionId === selectedCandidateId.value &&
  relationReviewState.value?.contextKey === relationContextKey.value &&
  relationReviewState.value?.canConfirm === true,
);

function setRelationReviewState(state: RelationReviewState) {
  if (state.questionId === selectedCandidateId.value && state.contextKey === relationContextKey.value) {
    relationReviewState.value = state;
  }
}
const pendingCandidateCount = computed(
  () => candidates.value.filter((candidate) => candidate.candidate_state === "pending_review" && !candidate.archived_at).length,
);
const selectedSourceAsset = computed(() => {
  const sourceId = selectedCandidate.value?.sources.find(
    (source) => source.question_source_id === selectedSourceId.value,
  )?.source_asset_id;
  return sources.value.find((source) => source.id === sourceId) ?? selectedJob.value?.source ?? null;
});
const selectedCandidateSources = computed(() => selectedCandidate.value?.sources ?? []);
const selectedManualBlocks = computed(() => {
  const selected = new Set(manualBlockIds.value);
  return ocrBlocks.value.filter((block) => selected.has(block.id));
});
const manualSourceText = computed(() =>
  selectedManualBlocks.value.map((block) => block.text).join("\n"),
);
const manualCandidatePreview = computed(() => {
  const asset = selectedJob.value?.source;
  if (!manualCreateOpen.value || !asset || selectedManualBlocks.value.length === 0) return null;
  return {
    source_asset_id: asset.id,
    text: manualSourceText.value,
    ocr_blocks: selectedManualBlocks.value,
  };
});

function setJob(job: IngestionJob) {
  const asset = sources.value.find((source) => source.id === job.source_asset_id);
  if (asset) {
    const index = asset.ingestion_jobs.findIndex((item) => item.id === job.id);
    if (index < 0) asset.ingestion_jobs.unshift(job);
    else asset.ingestion_jobs[index] = job;
    sources.value = [...sources.value];
  }
  uploadResults.value = uploadResults.value.map((result) =>
    result.job?.id === job.id ? { ...result, job } : result,
  );
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    const details = Object.values(error.fields);
    return details.length ? `${error.message}: ${details.join("；")}` : error.message;
  }
  if (error instanceof Error) return error.message;
  return "请求失败";
}

function setHistoryErrorForJob(jobId: number, message: string) {
  if (selectedJobId.value === jobId) historyError.value = message;
}

async function loadSources() {
  loadError.value = "";
  try {
    const [sourceRows, topicRows, tagRows] = await Promise.all([
      request<SourceAsset[]>("/api/v1/sources"),
      request<TaxonomyItem[]>("/api/v1/topics"),
      request<TaxonomyItem[]>("/api/v1/tags"),
    ]);
    sources.value = sourceRows;
    topics.value = topicRows;
    tags.value = tagRows;
  } catch (error) {
    loadError.value = errorMessage(error);
  }
}

async function waitForJob(jobId: number): Promise<IngestionJob | null> {
  for (let attempt = 0; attempt < 120; attempt += 1) {
    try {
      const response = await request<{ job: IngestionJob }>("/api/v1/ingestions/" + jobId);
      setJob(response.job);
      if (response.job.status !== "queued" && response.job.status !== "running") {
        return response.job;
      }
    } catch (error) {
      setHistoryErrorForJob(jobId, "无法读取导入任务状态：" + errorMessage(error));
      return null;
    }
    await new Promise((resolve) => window.setTimeout(resolve, 500));
  }
  setHistoryErrorForJob(jobId, "任务仍在运行，可稍后重新打开查看状态。");
  return null;
}

async function runJob(jobId: number) {
  const known = jobs.value.find((item) => item.id === jobId);
  if (known) setJob({ ...known, status: "running", stage: "running" });
  try {
    const response = await request<{ job: IngestionJob }>(
      "/api/v1/ingestions/" + jobId + "/run",
      { method: "POST" },
    );
    setJob(response.job);
    return response.job;
  } catch {
    // The request may have reached Flask before the browser timed out.
    // Read persisted state; never POST /run again for this job.
    return waitForJob(jobId);
  }
}

async function processQueuedJobs(jobIds: number[]) {
  busy.value = true;
  try {
    for (const id of jobIds) await runJob(id);
  } finally {
    busy.value = false;
  }
}

async function resumeJob(jobId: number) {
  if (busy.value) return;
  busy.value = true;
  if (selectedJobId.value === jobId) historyError.value = "";
  try {
    const response = await request<{ job: IngestionJob }>("/api/v1/ingestions/" + jobId);
    setJob(response.job);
    if (response.job.status === "queued") await runJob(jobId);
    else if (response.job.status === "running") await waitForJob(jobId);
  } catch (error) {
    setHistoryErrorForJob(jobId, "无法继续导入任务：" + errorMessage(error));
  } finally {
    busy.value = false;
  }
}

async function uploadFiles(files: File[]) {
  busy.value = true;
  uploadResults.value = [];
  loadError.value = "";
  const formData = new FormData();
  for (const file of files) formData.append("files", file, file.name);
  try {
    const response = await request<{ results: UploadResult[] }>("/api/v1/sources", {
      method: "POST",
      body: formData,
    });
    uploadResults.value = response.results.map((result, index) => ({
      ...result,
      filename: result.filename ?? files[index]?.name,
    }));
    const queued: number[] = [];
    for (const result of response.results) {
      if (result.status !== "stored" || !result.source || !result.job) continue;
      const existing = sources.value.find((source) => source.id === result.source!.id);
      if (existing) existing.ingestion_jobs.unshift(result.job);
      else sources.value.unshift({ ...result.source, ingestion_jobs: [result.job] });
      queued.push(result.job.id);
    }
    sources.value = [...sources.value];
    await processQueuedJobs(queued);
  } catch (error) {
    loadError.value = errorMessage(error);
  } finally {
    busy.value = false;
  }
}

async function openJob(
  jobId: number,
  preferredCandidateId: number | null = null,
  preferredSourceId: number | null = null,
) {
  const requestRevision = ++jobLoadRevision;
  selectedJobId.value = jobId;
  selectedCandidateId.value = null;
  selectedSourceId.value = null;
  candidates.value = [];
  candidateHistoryLoaded.value = false;
  ocrBlocks.value = [];
  manualCreateOpen.value = false;
  manualBlockIds.value = [];
  manualCandidateText.value = "";
  historyError.value = "";
  try {
    const [candidateRows, blocks] = await Promise.all([
      request<Candidate[]>("/api/v1/ingestions/" + jobId + "/candidates"),
      request<OCRBlock[]>("/api/v1/ingestions/" + jobId + "/ocr-blocks"),
    ]);
    if (requestRevision !== jobLoadRevision) return;
    candidates.value = candidateRows;
    candidateHistoryLoaded.value = true;
    ocrBlocks.value = blocks;
    const preferred = candidateRows.find((candidate) => candidate.id === preferredCandidateId);
    const nextPending = candidateRows.find(
      (candidate) => candidate.candidate_state === "pending_review" && !candidate.archived_at,
    );
    const candidate = preferred ?? nextPending ?? candidateRows[0];
    if (candidate) selectCandidate(candidate, preferredSourceId);
  } catch (error) {
    if (requestRevision === jobLoadRevision) historyError.value = errorMessage(error);
  }
}

function selectCandidate(candidate: Candidate, preferredSourceId: number | null = null) {
  candidateSelectionRevision.value += 1;
  selectedCandidateId.value = candidate.id;
  selectedSourceId.value =
    candidate.sources.find((source) => source.question_source_id === preferredSourceId)
      ?.question_source_id ?? candidate.sources[0]?.question_source_id ?? null;
  selectedMergeIds.value = [];
  mergeFinalText.value = candidate.text;
}

async function openHistoricalJob(jobId: number) {
  const preserveSelection = selectedJobId.value === jobId;
  await openJob(
    jobId,
    preserveSelection ? selectedCandidateId.value : null,
    preserveSelection ? selectedSourceId.value : null,
  );
}

async function refreshCurrentJob(
  preferredCandidateId: number | null = selectedCandidateId.value,
  preferredSourceId: number | null = selectedSourceId.value,
  expectedJobId: number | null = selectedJobId.value,
) {
  if (expectedJobId !== null && selectedJobId.value === expectedJobId) {
    await openJob(expectedJobId, preferredCandidateId, preferredSourceId);
  }
}

function conflictMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError && error.status === 409
    ? fallback
    : errorMessage(error);
}

async function createManualCandidate() {
  const jobId = selectedJobId.value;
  if (jobId === null || manualBlockIds.value.length === 0) return;
  candidateBusy.value = true;
  historyError.value = "";
  const payload: { ocr_block_ids: string[]; text?: string } = {
    ocr_block_ids: [...manualBlockIds.value],
  };
  if (manualCandidateText.value.trim()) payload.text = manualCandidateText.value;
  try {
    const candidate = await request<Candidate>(
      "/api/v1/ingestions/" + jobId + "/candidates",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      },
    );
    await refreshCurrentJob(candidate.id, candidate.sources[0]?.question_source_id ?? null, jobId);
  } catch (error) {
    setHistoryErrorForJob(jobId, conflictMessage(error, "导入任务状态已变化，请刷新后重试。"));
  } finally {
    candidateBusy.value = false;
  }
}

async function patchCandidate(payload: Record<string, unknown>) {
  if (selectedCandidateId.value === null || selectedJobId.value === null) return;
  const jobId = selectedJobId.value;
  const candidateId = selectedCandidateId.value;
  const sourceId = selectedSourceId.value;
  candidateBusy.value = true;
  historyError.value = "";
  try {
    await request<Candidate>(
      "/api/v1/ingestion-candidates/" + candidateId,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      },
    );
    await refreshCurrentJob(candidateId, sourceId, jobId);
  } catch (error) {
    if (selectedJobId.value !== jobId) return;
    if (error instanceof ApiError && error.status === 409) {
      await refreshCurrentJob(candidateId, sourceId, jobId);
      setHistoryErrorForJob(jobId, "候选内容已被其他操作更新，请刷新后重试。");
    } else {
      setHistoryErrorForJob(jobId, errorMessage(error));
    }
  } finally {
    candidateBusy.value = false;
  }
}

async function splitCandidate(payload: Record<string, unknown>) {
  if (selectedJobId.value === null || selectedCandidateId.value === null) return;
  const jobId = selectedJobId.value;
  const candidateId = selectedCandidateId.value;
  const sourceId = selectedSourceId.value;
  candidateBusy.value = true;
  historyError.value = "";
  try {
    const result = await request<{ children: Candidate[] }>(
      "/api/v1/ingestions/" +
        jobId +
        "/candidates/" +
        candidateId +
        "/split",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      },
    );
    const firstChild = result.children.find(
      (candidate) => candidate.candidate_state === "pending_review" && !candidate.archived_at,
    );
    await refreshCurrentJob(
      firstChild?.id ?? candidateId,
      firstChild?.sources[0]?.question_source_id ?? null,
      jobId,
    );
  } catch (error) {
    if (selectedJobId.value !== jobId) return;
    if (error instanceof ApiError && error.status === 409) {
      await refreshCurrentJob(candidateId, sourceId, jobId);
      setHistoryErrorForJob(jobId, "候选内容已变化，请刷新后重试。");
    } else {
      setHistoryErrorForJob(jobId, errorMessage(error));
    }
  } finally {
    candidateBusy.value = false;
  }
}

async function candidateDisposition(
  action: "archive" | "confirm",
  payload: { expected_revision: number },
) {
  if (action === "confirm" && !canConfirmSelectedCandidate.value) return;
  if (selectedCandidateId.value === null || selectedJobId.value === null) return;
  const jobId = selectedJobId.value;
  const candidateId = selectedCandidateId.value;
  const sourceId = selectedSourceId.value;
  candidateBusy.value = true;
  historyError.value = "";
  try {
    await request(
      "/api/v1/ingestion-candidates/" + candidateId + "/" + action,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      },
    );
    await refreshCurrentJob(candidateId, sourceId, jobId);
  } catch (error) {
    if (selectedJobId.value !== jobId) return;
    if (error instanceof ApiError && error.status === 409) {
      await refreshCurrentJob(candidateId, sourceId, jobId);
      setHistoryErrorForJob(jobId, error.fields.similar_questions
        ? "请先处理相似题建议；同题需等待规范题归并功能，或明确排除/标记相关或不同后再确认。"
        : "候选内容已变化，请刷新后重试。");
    } else if (
      action === "confirm" &&
      error instanceof ApiError &&
      error.status === 400 &&
      (error.fields.topic_ids || error.fields.tag_ids)
    ) {
      setHistoryErrorForJob(jobId, "候选题关联的分类已停用或无效，请重新选择有效 Topic/Tag 后再确认。");
    } else {
      setHistoryErrorForJob(jobId, errorMessage(error));
    }
  } finally {
    candidateBusy.value = false;
  }
}

async function mergeCandidates() {
  if (selectedJobId.value === null || selectedCandidate.value === null) return;
  const jobId = selectedJobId.value;
  const survivorId = selectedCandidate.value.id;
  const sourceId = selectedSourceId.value;
  const participantIds = [...new Set([...selectedMergeIds.value, survivorId])];
  if (participantIds.length < 2) {
    historyError.value = "请选择至少另一道同一任务中的待确认候选题。";
    return;
  }
  candidateBusy.value = true;
  historyError.value = "";
  try {
    const selectedCandidates = candidates.value.filter((candidate) =>
      participantIds.includes(candidate.id),
    );
    const result = await request<{ survivor: Candidate }>(
      "/api/v1/ingestions/" + jobId + "/candidates/merge",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          survivor_id: survivorId,
          candidates: selectedCandidates.map((candidate) => ({
            id: candidate.id,
            expected_revision: candidate.candidate_revision,
          })),
          final_text: mergeFinalText.value,
        }),
      },
    );
    await refreshCurrentJob(
      result.survivor.id,
      result.survivor.sources.some((source) => source.question_source_id === sourceId)
        ? sourceId
        : result.survivor.sources[0]?.question_source_id ?? null,
      jobId,
    );
  } catch (error) {
    if (selectedJobId.value !== jobId) return;
    if (error instanceof ApiError && error.status === 409) {
      await refreshCurrentJob(survivorId, sourceId, jobId);
      setHistoryErrorForJob(jobId, "候选内容已变化，请刷新后重试。");
    } else {
      setHistoryErrorForJob(jobId, errorMessage(error));
    }
  } finally {
    candidateBusy.value = false;
  }
}

async function retrySource(sourceId: number) {
  busy.value = true;
  try {
    const response = await request<{ job: IngestionJob }>(
      "/api/v1/sources/" + sourceId + "/ingestions",
      { method: "POST" },
    );
    const asset = sources.value.find((source) => source.id === sourceId);
    if (asset) asset.ingestion_jobs.unshift(response.job);
    sources.value = [...sources.value];
    await runJob(response.job.id);
  } catch (error) {
    loadError.value = errorMessage(error);
  } finally {
    busy.value = false;
  }
}

function stateLabel(value: string) {
  return ({pending_review:"待审核",confirmed:"已确认",rejected:"已拒绝",superseded:"已替换",succeeded:"识别成功",failed:"识别失败",queued:"等待识别",running:"识别中"} as Record<string,string>)[value] ?? value;
}
onMounted(loadSources);
</script>

<template>
  <section aria-label="截图采集收件箱" class="inbox-page">
    <header class="page-heading"><div><span class="eyebrow">Capture & review</span><h2>截图采集</h2><p>从截图到题库，每一道题都经过你的审核。</p></div></header>
    <div class="inbox-workspace"><aside class="inbox-library">
    <SourceUpload :disabled="busy" @upload="uploadFiles" />
    <p v-if="busy" role="status">正在处理截图…</p>
    <p v-if="loadError" role="alert">{{ loadError }}</p>

    <section v-if="uploadResults.length" aria-label="本次上传结果">
      <h3>本次上传</h3>
      <ul>
        <li v-for="(result, index) in uploadResults" :key="index">
          <span v-if="result.status === 'stored'">
            {{ result.source?.original_filename }} · {{ result.job ? stateLabel(result.job.status) : "" }}
          </span>
          <span v-else>
            {{ result.filename ?? "截图 " + (index + 1) }} ·
            {{ result.error?.code }} · {{ result.error?.message }}
          </span>
        </li>
      </ul>
    </section>

    <section aria-label="截图与导入历史">
      <h3>截图历史</h3>
      <p v-if="sources.length === 0" class="empty-state">还没有截图</p>
      <article v-for="asset in sources" :key="asset.id" class="source-entry">
        <h4>{{ asset.title || asset.original_filename || "截图 " + asset.id }}</h4>
        <p class="muted">{{ asset.display_width }} × {{ asset.display_height }} · {{ asset.ingestion_jobs.length }} 次导入</p><details><summary>来源校验信息</summary><p class="mono">{{ asset.sha256 }}</p></details>
        <a :href="'/api/v1/sources/' + asset.id + '/original'">打开原图</a>
        <ul aria-label="OCR 任务历史">
          <li v-for="job in asset.ingestion_jobs" :key="job.id">
            <button
              type="button"
              :aria-label="'打开导入任务 ' + job.id"
              :aria-pressed="job.id === selectedJobId"
              @click="openHistoricalJob(job.id)"
            >
              任务 {{ job.id }} · {{ stateLabel(job.status) }} · 自动候选 {{ job.candidate_count }}
            </button>
            <button
              v-if="job.status === 'queued' || job.status === 'running'"
              type="button"
              :disabled="busy"
              :aria-label="job.status === 'queued' ? '继续识别任务 ' + job.id : '查看任务状态 ' + job.id"
              @click="resumeJob(job.id)"
            >
              {{ job.status === "queued" ? "继续识别" : "查看状态" }}
            </button>
            <span v-if="job.error_code">{{ job.error_code }} · {{ job.error_message }}</span>
            <button
              v-if="job.status === 'failed'"
              type="button"
              :disabled="busy"
              :aria-label="'重试截图 ' + asset.id"
              @click="retrySource(asset.id)"
            >
              重新识别
            </button>
          </li>
        </ul>
      </article>
    </section>

    </aside><div>
    <p v-if="historyError" role="alert">{{ historyError }}</p>
    <section v-if="selectedJob" aria-label="导入任务详情" class="job-workspace">
      <h3>任务 {{ selectedJob.id }} · {{ stateLabel(selectedJob.status) }}</h3>
      <p v-if="selectedJob.failure_stage">失败阶段：{{ selectedJob.failure_stage }}</p>
      <details v-if="ocrBlocks.length"><summary>查看完整 OCR 原文（{{ ocrBlocks.length }} 个区域）</summary><pre aria-label="OCR 原文">{{
        ocrBlocks.map((block) => block.text).join("\n")
      }}</pre></details>
      <p v-else>没有识别到文字</p>
      <section
        v-if="selectedJob.status === 'succeeded' && selectedJob.stage === 'completed' && ocrBlocks.length"
        aria-label="OCR 人工补建候选"
      >
        <button
          v-if="!manualCreateOpen"
          type="button"
          aria-label="补建候选题"
          @click="manualCreateOpen = true"
        >
          从 OCR 块补建候选题
        </button>
        <form
          v-if="manualCreateOpen"
          aria-label="从 OCR 块补建候选题"
          @submit.prevent="createManualCandidate"
        >
          <p>选择一道未自动生成候选题的来源文字。OCR 块可被多个候选引用，补建不会修改已有候选或 OCR 证据。</p>
          <ul aria-label="可选 OCR 块">
            <li v-for="block in ocrBlocks" :key="block.id">
              <label>
                <input
                  v-model="manualBlockIds"
                  type="checkbox"
                  :value="block.id"
                  :disabled="!block.text.trim() || candidateBusy"
                  :aria-label="'选择用于补建的 OCR 块 ' + block.id"
                />
                {{ block.reading_order + 1 }}. {{ block.text }}
              </label>
            </li>
          </ul>
          <pre v-if="selectedManualBlocks.length" aria-label="补建候选题 OCR 快照">{{ manualSourceText }}</pre>
          <label>
            最终题目正文（可修正；留空则使用所选 OCR 文本）
            <textarea
              v-model="manualCandidateText"
              aria-label="补建候选题正文"
              :placeholder="manualSourceText"
            />
          </label>
          <button type="submit" :disabled="candidateBusy || manualBlockIds.length === 0">
            创建待审核候选题
          </button>
          <button type="button" :disabled="candidateBusy" @click="manualCreateOpen = false">
            取消
          </button>
        </form>
      </section>
      <ul aria-label="候选题历史" class="candidate-list">
        <li v-for="candidate in candidates" :key="candidate.id">
          <input
            v-if="candidate.candidate_state === 'pending_review' && !candidate.archived_at"
            v-model="selectedMergeIds"
            type="checkbox"
            :value="candidate.id"
            :aria-label="'选择合并候选 ' + candidate.id"
          />
          <button
            type="button"
            :aria-label="'查看候选题 ' + candidate.id"
            :aria-pressed="candidate.id === selectedCandidateId"
            @click="selectCandidate(candidate)"
          >
            {{ candidate.text }} · {{ stateLabel(candidate.candidate_state) }}
          </button>
          <span> 来源区域 {{ candidate.sources.map((item) => item.question_source_id).join(", ") }} </span>
          <span v-if="candidate.split_from_candidate_id">拆分自候选 #{{ candidate.split_from_candidate_id }}</span>
          <span v-if="candidate.split_child_ids.length">
            已拆分为候选 {{ candidate.split_child_ids.map((id) => "#" + id).join("、") }}
          </span>
          <span v-if="candidate.superseded_by_candidate_id">
            已合并至候选 #{{ candidate.superseded_by_candidate_id }}
          </span>
        </li>
      </ul>
      <p v-if="candidateHistoryLoaded" aria-label="候选数量统计">
        历史候选 {{ candidates.length }} · 待确认 {{ pendingCandidateCount }}
      </p>
      <p v-if="selectedCandidate && selectedCandidate.candidate_state !== 'pending_review'">
        此候选已完成审核，只能查看历史来源证据。
      </p>
      <details class="candidate-extras" v-if="selectedCandidate && selectedCandidate.candidate_state === 'pending_review' && !selectedCandidate.archived_at"><summary>整理同一截图的候选边界</summary>
      <form
        aria-label="候选题同任务合并"
        @submit.prevent="mergeCandidates"
      >
        <label>
          合并后正文
          <textarea v-model="mergeFinalText" aria-label="合并后题目正文" />
        </label>
        <button type="submit" :disabled="candidateBusy">合并所选候选题</button>
      </form></details>
      <QuestionRelationReview
        v-if="selectedCandidate && selectedCandidate.candidate_state === 'pending_review' && !selectedCandidate.archived_at && selectedCandidate.status === 'pending_review'"
        :key="`${selectedCandidate.id}:${relationContextKey}`"
        :question-id="selectedCandidate.id"
        :text="selectedCandidate.text"
        :context-key="relationContextKey"
        :disabled="candidateBusy"
        @state="setRelationReviewState"
      />
      <div class="candidate-review-workspace"><IngestionCandidateEditor
        v-if="
          selectedCandidate &&
          selectedCandidate.candidate_state === 'pending_review' &&
          !selectedCandidate.archived_at &&
          selectedCandidate.status === 'pending_review'
        "
        :candidate="selectedCandidate"
        :topics="topics"
        :tags="tags"
        :selected-source-id="selectedSourceId"
        :busy="candidateBusy"
        :confirmation-blocked="!canConfirmSelectedCandidate"
        @select-source="selectedSourceId = $event"
        @save="patchCandidate"
        @split="splitCandidate"
        @archive="candidateDisposition('archive', $event)"
        @confirm="candidateDisposition('confirm', $event)"
      />
      <SourceImageViewer
        v-if="manualCandidatePreview && selectedJob"
        :sources="[]"
        :selected-source-id="null"
        :image-width="selectedJob.source.display_width"
        :image-height="selectedJob.source.display_height"
        :preview="manualCandidatePreview"
      />
      <SourceImageViewer
        v-else-if="selectedCandidate"
        :sources="selectedCandidateSources"
        :selected-source-id="selectedSourceId"
        :image-width="selectedSourceAsset?.display_width ?? 0"
        :image-height="selectedSourceAsset?.display_height ?? 0"
        @select-source="selectedSourceId = $event"
      /></div>
    </section>
    <div v-else class="empty-state">选择左侧导入任务，开始校对题目与来源。</div>
    </div></div>
  </section>
</template>

<style scoped>
.source-entry {
  margin: 1rem 0;
  padding: 0.75rem;
  border: 1px solid #d4d8df;
  border-radius: 0.5rem;
  overflow-wrap: anywhere;
}

pre {
  max-height: 16rem;
  overflow: auto;
  white-space: pre-wrap;
}
</style>
