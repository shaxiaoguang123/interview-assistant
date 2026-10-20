<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { RouterLink } from "vue-router";
import type { MergeOutcome } from "../api/question-merge";
import { ApiError, request } from "../api/client";
import type {
  IngestionCandidate,
  IngestionJob,
  IngestionOCRBlock,
  IngestionTaxonomyItem,
  SourceAsset,
  UploadResult,
} from "../api/ingestion";
import IngestionCandidateEditor from "../components/IngestionCandidateEditor.vue";
import QuestionRelationReview from "../components/QuestionRelationReview.vue";
import type { RelationReviewState } from "../api/question-relations";
import InboxCandidateQueue from "../components/ingestion/InboxCandidateQueue.vue";
import InboxSourceHistory from "../components/ingestion/InboxSourceHistory.vue";
import JobAiTriage from "../components/ingestion/JobAiTriage.vue";
import SourceImageViewer from "../components/SourceImageViewer.vue";
import SourceUpload from "../components/SourceUpload.vue";

const sources = ref<SourceAsset[]>([]);
const topics = ref<IngestionTaxonomyItem[]>([]);
const tags = ref<IngestionTaxonomyItem[]>([]);
const uploadResults = ref<UploadResult[]>([]);
const selectedJobId = ref<number | null>(null);
const selectedCandidateId = ref<number | null>(null);
const selectedSourceId = ref<number | null>(null);
const candidates = ref<IngestionCandidate[]>([]);
const candidateHistoryLoaded = ref(false);
const ocrBlocks = ref<IngestionOCRBlock[]>([]);
const busy = ref(false);
const mergeSuccess = ref<MergeOutcome | null>(null);
const loadError = ref("");
const historyError = ref("");
const candidateBusy = ref(false);
const candidateDraftDirty = ref(false);
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
      request<IngestionTaxonomyItem[]>("/api/v1/topics"),
      request<IngestionTaxonomyItem[]>("/api/v1/tags"),
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
  mergeSuccess.value = null;
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
      request<IngestionCandidate[]>("/api/v1/ingestions/" + jobId + "/candidates"),
      request<IngestionOCRBlock[]>("/api/v1/ingestions/" + jobId + "/ocr-blocks"),
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

function selectCandidate(candidate: IngestionCandidate, preferredSourceId: number | null = null) {
  // Re-clicking the selected row must preserve its editor draft and review gate.
  if (selectedCandidateId.value === candidate.id && preferredSourceId === null) return;
  candidateSelectionRevision.value += 1;
  candidateDraftDirty.value = false;
  mergeSuccess.value = null;
  selectedCandidateId.value = candidate.id;
  selectedSourceId.value =
    candidate.sources.find((source) => source.question_source_id === preferredSourceId)
      ?.question_source_id ?? candidate.sources[0]?.question_source_id ?? null;
  selectedMergeIds.value = [];
  mergeFinalText.value = candidate.text;
}

function openBatchCandidate(candidateId: number) {
  const candidate = candidates.value.find((item) => item.id === candidateId);
  if (candidate) selectCandidate(candidate);
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

async function refreshAfterAiConflict() {
  const jobId = selectedJobId.value;
  const candidateId = selectedCandidateId.value;
  const sourceId = selectedSourceId.value;
  if (jobId === null || candidateId === null) return;
  await refreshCurrentJob(candidateId, sourceId, jobId);
  setHistoryErrorForJob(jobId, "候选已更新并重新读取；若有未保存草稿，编辑器会保留以供你对照后决定是否保存。");
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
    const candidate = await request<IngestionCandidate>(
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

function openManualCreationForBlocks(blockIds: string[]) {
  manualBlockIds.value = [...blockIds];
  manualCandidateText.value = "";
  manualCreateOpen.value = true;
}

async function applyBatchCandidate(payload: {
  candidate_id: number;
  expected_revision: number;
  text: string;
  topic_ids?: number[];
  tag_ids?: number[];
  difficulty?: string | null;
}) {
  const jobId = selectedJobId.value;
  if (jobId === null || candidateDraftDirty.value) return;
  const keepCandidateId = selectedCandidateId.value;
  const sourceId = selectedSourceId.value;
  candidateBusy.value = true;
  historyError.value = "";
  try {
    await request<IngestionCandidate>(`/api/v1/ingestion-candidates/${payload.candidate_id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        expected_revision: payload.expected_revision,
        text: payload.text,
        ...(payload.topic_ids?.length ? { topic_ids: payload.topic_ids } : {}),
        ...(payload.tag_ids?.length ? { tag_ids: payload.tag_ids } : {}),
        ...(payload.difficulty ? { difficulty: payload.difficulty } : {}),
      }),
    });
    await refreshCurrentJob(keepCandidateId, sourceId, jobId);
  } catch (error) {
    if (selectedJobId.value === jobId) {
      await refreshCurrentJob(keepCandidateId, sourceId, jobId);
      setHistoryErrorForJob(jobId, conflictMessage(error, "候选已变化或建议未能保存，请重新读取后重试。"));
    }
  } finally {
    candidateBusy.value = false;
  }
}

async function archiveBatchCandidate(payload: { candidate_id: number; expected_revision: number }) {
  const jobId = selectedJobId.value;
  if (jobId === null || candidateDraftDirty.value) return;
  const keepCandidateId = selectedCandidateId.value === payload.candidate_id ? null : selectedCandidateId.value;
  const sourceId = selectedSourceId.value;
  candidateBusy.value = true;
  historyError.value = "";
  try {
    await request(`/api/v1/ingestion-candidates/${payload.candidate_id}/archive`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ expected_revision: payload.expected_revision }),
    });
    await refreshCurrentJob(keepCandidateId, sourceId, jobId);
  } catch (error) {
    if (selectedJobId.value === jobId) {
      await refreshCurrentJob(keepCandidateId, sourceId, jobId);
      setHistoryErrorForJob(jobId, conflictMessage(error, "候选未能归档，请重新读取后重试。"));
    }
  } finally {
    candidateBusy.value = false;
  }
}

async function splitBatchCandidate(payload: {
  candidate_id: number;
  expected_revision: number;
  parts: Array<{ text: string; ocr_block_ids: string[]; source_text_snapshot: string }>;
}) {
  const jobId = selectedJobId.value;
  if (jobId === null || candidateDraftDirty.value) return;
  const sourceId = selectedSourceId.value;
  candidateBusy.value = true;
  historyError.value = "";
  try {
    const response = await request<{ children: IngestionCandidate[] }>(
      `/api/v1/ingestions/${jobId}/candidates/${payload.candidate_id}/split`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ expected_revision: payload.expected_revision, parts: payload.parts }),
      },
    );
    const firstChild = response.children.find((candidate) => candidate.candidate_state === "pending_review");
    await refreshCurrentJob(firstChild?.id ?? null, firstChild?.sources[0]?.question_source_id ?? sourceId, jobId);
  } catch (error) {
    if (selectedJobId.value === jobId) {
      await refreshCurrentJob(selectedCandidateId.value, sourceId, jobId);
      setHistoryErrorForJob(jobId, conflictMessage(error, "候选未能拆分，请检查 OCR 来源后重试。"));
    }
  } finally {
    candidateBusy.value = false;
  }
}

async function createBatchCandidate(payload: { ocr_block_ids: string[]; text: string }) {
  const jobId = selectedJobId.value;
  if (jobId === null || candidateDraftDirty.value) return;
  candidateBusy.value = true;
  historyError.value = "";
  try {
    const candidate = await request<IngestionCandidate>(`/api/v1/ingestions/${jobId}/candidates`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...payload, expected_unassigned: true }),
    });
    await refreshCurrentJob(candidate.id, candidate.sources[0]?.question_source_id ?? null, jobId);
  } catch (error) {
    if (selectedJobId.value === jobId) {
      await refreshCurrentJob(selectedCandidateId.value, selectedSourceId.value, jobId);
      setHistoryErrorForJob(jobId, conflictMessage(error, "来源已关联或候选未能创建，请重新分析后重试。"));
    }
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
    await request<IngestionCandidate>(
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
    const result = await request<{ children: IngestionCandidate[] }>(
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
        ? "请先处理相似题建议；同题请归并为规范题，或明确排除/标记相关或不同后再确认。"
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
    const result = await request<{ survivor: IngestionCandidate }>(
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

async function onCanonicalMerged(outcome: MergeOutcome) {
  const jobId = selectedJobId.value;
  const selection = candidateSelectionRevision.value;
  const sourceId = selectedSourceId.value;
  if (selectedCandidateId.value !== outcome.sourceId || jobId === null) return;
  await refreshCurrentJob(outcome.sourceId, sourceId, jobId);
  if (selectedJobId.value === jobId && selectedCandidateId.value === outcome.sourceId && candidateSelectionRevision.value === selection + 1) mergeSuccess.value = outcome;
}
function stateLabel(value: string) {
  return ({pending_review:"待审核",confirmed:"已确认",rejected:"已拒绝",superseded:"已替换",succeeded:"识别成功",failed:"识别失败",queued:"等待识别",running:"识别中"} as Record<string,string>)[value] ?? value;
}
onMounted(loadSources);
</script>

<template>
  <section aria-label="截图采集收件箱" class="inbox-page">
    <header class="page-heading inbox-page-heading">
      <div>
        <span class="eyebrow">截图导入工作流</span>
        <h2>截图采集</h2>
        <p>上传截图后校对识别结果；确认入库前，原图和 OCR 来源始终保留。</p>
      </div>
      <ol class="inbox-workflow" aria-label="截图入库流程">
        <li><span class="workflow-number">01</span><span>上传</span></li>
        <li><span class="workflow-number">02</span><span>校对</span></li>
        <li><span class="workflow-number">03</span><span>确认入库</span></li>
      </ol>
    </header>

    <section class="inbox-intake" aria-label="上传与处理状态">
      <SourceUpload :disabled="busy" @upload="uploadFiles" />
      <p v-if="busy" role="status">正在处理截图…</p>
      <p v-if="loadError" role="alert">{{ loadError }}</p>
      <section v-if="uploadResults.length" class="upload-results" aria-label="本次上传结果">
        <h3>本次上传结果</h3>
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
    </section>

    <div class="inbox-workspace">
      <aside class="inbox-library" aria-label="截图与候选导航">
        <InboxCandidateQueue
          v-if="selectedJob"
          :job-id="selectedJob.id"
          :candidates="candidates"
          :loaded="candidateHistoryLoaded"
          :pending-count="pendingCandidateCount"
          :selected-candidate-id="selectedCandidateId"
          :busy="candidateBusy"
          v-model:selected-merge-ids="selectedMergeIds"
          v-model:merge-final-text="mergeFinalText"
          @select="selectCandidate"
          @merge="mergeCandidates"
        />
        <InboxSourceHistory
          :sources="sources"
          :selected-job-id="selectedJobId"
          :busy="busy"
          :state-label="stateLabel"
          @open-job="openHistoricalJob"
          @resume-job="resumeJob"
          @retry-source="retrySource"
        />

      </aside>

      <div class="inbox-review-pane">
        <p v-if="historyError" role="alert">{{ historyError }}</p>
        <section v-if="selectedJob" aria-label="导入任务详情" class="job-workspace">
          <header class="job-heading">
            <div><span class="eyebrow">当前来源 · 任务 {{ selectedJob.id }}</span><h3>候选审核</h3></div>
            <span class="badge" :class="selectedJob.status === 'succeeded' ? 'success' : selectedJob.status === 'failed' ? 'danger' : 'warning'">{{ stateLabel(selectedJob.status) }}</span>
          </header>

          <div class="job-source-context">
            <p v-if="selectedJob.failure_stage" class="job-failure">失败阶段：{{ selectedJob.failure_stage }}</p>
            <details v-if="ocrBlocks.length" class="ocr-original">
              <summary>查看完整 OCR 原文 <span class="badge">{{ ocrBlocks.length }} 个区域</span></summary>
              <pre aria-label="OCR 原文">{{ ocrBlocks.map((block) => block.text).join("\n") }}</pre>
            </details>
            <p v-else>没有识别到文字</p>
          </div>

          <section
            v-if="selectedJob.status === 'succeeded' && selectedJob.stage === 'completed' && ocrBlocks.length"
            aria-label="OCR 人工补建候选"
            class="manual-candidate-tools"
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
              <div class="action-row">
                <button type="submit" :disabled="candidateBusy || manualBlockIds.length === 0">创建待审核候选题</button>
                <button type="button" :disabled="candidateBusy" @click="manualCreateOpen = false">取消</button>
              </div>
            </form>
          </section>

          <JobAiTriage
            v-if="selectedJob.status === 'succeeded' && selectedJob.stage === 'completed' && (!candidateHistoryLoaded || ocrBlocks.length)"
            :job-id="selectedJob.id"
            :candidates="candidates"
            :ocr-blocks="ocrBlocks"
            :topics="topics"
            :tags="tags"
            :ready="candidateHistoryLoaded && ocrBlocks.length > 0"
            :busy="candidateBusy || !candidateHistoryLoaded"
            :draft-dirty="candidateDraftDirty"
            @apply-candidate="applyBatchCandidate"
            @archive-candidate="archiveBatchCandidate"
            @split-candidate="splitBatchCandidate"
            @create-candidate="createBatchCandidate"
            @open-candidate="openBatchCandidate"
            @manual-create="openManualCreationForBlocks"
            @conflict="refreshAfterAiConflict"
          />

          <p v-if="selectedCandidate && selectedCandidate.candidate_state !== 'pending_review'" class="history-notice">
            此候选已完成审核，只能查看历史来源证据。
          </p>
          <div v-if="mergeSuccess" class="success-banner" role="status">归并成功 · 候选 #{{ mergeSuccess.sourceId }} 已确认并归并。<RouterLink :to="'/questions/' + mergeSuccess.canonicalId">打开规范题 #{{ mergeSuccess.canonicalId }}</RouterLink></div>
          <div v-if="selectedCandidate?.status === 'merged' && !mergeSuccess" class="canonical-banner">此候选已归并，保留原始 OCR 与来源证据。<RouterLink :to="'/questions/' + selectedCandidate.canonical_question_id">打开规范题 #{{ selectedCandidate.canonical_question_id }}</RouterLink></div>

          <div v-if="selectedCandidate" class="candidate-focus">
            <span class="eyebrow">当前候选 #{{ selectedCandidate.id }}</span>
            <h3>{{ selectedCandidate.text }}</h3>
            <p v-if="selectedCandidate.candidate_state === 'pending_review'" class="helper">校对正文 → 检查相似题 → 保存候选修改 → 确认入库</p>
          </div>
          <div v-else class="empty-state review-empty-state">从左侧候选列表选择一道题，开始校对与确认。</div>

          <div v-if="selectedCandidate" class="candidate-review-workspace" :class="{historical:selectedCandidate.candidate_state !== 'pending_review'}">
            <div class="candidate-main">
              <IngestionCandidateEditor
                v-if="selectedCandidate.candidate_state === 'pending_review' && !selectedCandidate.archived_at && selectedCandidate.status === 'pending_review'"
                :candidate="selectedCandidate"
                :topics="topics"
                :tags="tags"
                :selected-source-id="selectedSourceId"
                :busy="candidateBusy"
                :confirmation-blocked="!canConfirmSelectedCandidate"
                @select-source="selectedSourceId = $event"
                @dirty-change="candidateDraftDirty = $event"
                @ai-conflict="refreshAfterAiConflict"
                @save="patchCandidate"
                @split="splitCandidate"
                @archive="candidateDisposition('archive', $event)"
                @confirm="candidateDisposition('confirm', $event)"
              />
              <QuestionRelationReview
                v-if="selectedCandidate.candidate_state === 'pending_review' && !selectedCandidate.archived_at && selectedCandidate.status === 'pending_review'"
                :key="selectedCandidate.id + ':' + relationContextKey"
                :question-id="selectedCandidate.id"
                :text="selectedCandidate.text"
                :context-key="relationContextKey"
                :disabled="candidateBusy || candidateDraftDirty"
                @state="setRelationReviewState"
                @merged="onCanonicalMerged"
              />
            </div>
            <aside class="candidate-evidence"><h3>来源证据</h3>
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
              />
            </aside>
          </div>
        </section>
        <div v-else class="empty-state job-empty-state">选择左侧导入任务，开始校对题目与来源。</div>
      </div>
    </div>
  </section>
</template>
