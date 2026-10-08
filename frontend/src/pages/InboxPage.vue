<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { ApiError, request } from "../api/client";
import IngestionCandidateEditor from "../components/IngestionCandidateEditor.vue";
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
  candidate_count: number;
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
  candidate_state: string;
  candidate_revision: number;
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
const ocrBlocks = ref<OCRBlock[]>([]);
const busy = ref(false);
const loadError = ref("");
const historyError = ref("");
const candidateBusy = ref(false);
const selectedMergeIds = ref<number[]>([]);
const mergeFinalText = ref("");

const jobs = computed(() =>
  sources.value.flatMap((source) =>
    source.ingestion_jobs.map((job) => ({ ...job, source })),
  ),
);
const selectedJob = computed(() => jobs.value.find((item) => item.id === selectedJobId.value) ?? null);
const selectedCandidate = computed(
  () => candidates.value.find((candidate) => candidate.id === selectedCandidateId.value) ?? null,
);
const selectedSourceAsset = computed(() => {
  const sourceId = selectedCandidate.value?.sources.find(
    (source) => source.question_source_id === selectedSourceId.value,
  )?.source_asset_id;
  return sources.value.find((source) => source.id === sourceId) ?? selectedJob.value?.source ?? null;
});
const selectedCandidateSources = computed(() => selectedCandidate.value?.sources ?? []);

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
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "请求失败";
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
      historyError.value = "无法读取导入任务状态：" + errorMessage(error);
      return null;
    }
    await new Promise((resolve) => window.setTimeout(resolve, 500));
  }
  historyError.value = "任务仍在运行，可稍后重新打开查看状态。";
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

async function openJob(jobId: number) {
  selectedJobId.value = jobId;
  selectedCandidateId.value = null;
  selectedSourceId.value = null;
  candidates.value = [];
  ocrBlocks.value = [];
  historyError.value = "";
  try {
    const [candidateRows, blocks] = await Promise.all([
      request<Candidate[]>("/api/v1/ingestions/" + jobId + "/candidates"),
      request<OCRBlock[]>("/api/v1/ingestions/" + jobId + "/ocr-blocks"),
    ]);
    candidates.value = candidateRows;
    ocrBlocks.value = blocks;
    if (candidateRows.length) selectCandidate(candidateRows[0]);
  } catch (error) {
    historyError.value = errorMessage(error);
  }
}

function selectCandidate(candidate: Candidate) {
  selectedCandidateId.value = candidate.id;
  selectedSourceId.value = candidate.sources[0]?.question_source_id ?? null;
  selectedMergeIds.value = [];
  mergeFinalText.value = candidate.text;
}

async function refreshCurrentJob() {
  if (selectedJobId.value !== null) await openJob(selectedJobId.value);
}

async function patchCandidate(payload: Record<string, unknown>) {
  if (selectedCandidateId.value === null) return;
  candidateBusy.value = true;
  historyError.value = "";
  try {
    await request<Candidate>(
      "/api/v1/ingestion-candidates/" + selectedCandidateId.value,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      },
    );
    await refreshCurrentJob();
  } catch (error) {
    historyError.value =
      error instanceof ApiError && error.status === 409
        ? "候选内容已被其他操作更新，请刷新后重试。"
        : errorMessage(error);
    if (error instanceof ApiError && error.status === 409) await refreshCurrentJob();
  } finally {
    candidateBusy.value = false;
  }
}

async function splitCandidate(payload: Record<string, unknown>) {
  if (selectedJobId.value === null || selectedCandidateId.value === null) return;
  candidateBusy.value = true;
  historyError.value = "";
  try {
    await request(
      "/api/v1/ingestions/" +
        selectedJobId.value +
        "/candidates/" +
        selectedCandidateId.value +
        "/split",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      },
    );
    await refreshCurrentJob();
  } catch (error) {
    historyError.value =
      error instanceof ApiError && error.status === 409
        ? "候选内容已变化，请刷新后重试。"
        : errorMessage(error);
    if (error instanceof ApiError && error.status === 409) await refreshCurrentJob();
  } finally {
    candidateBusy.value = false;
  }
}

async function candidateDisposition(
  action: "archive" | "confirm",
  payload: { expected_revision: number },
) {
  if (selectedCandidateId.value === null) return;
  candidateBusy.value = true;
  historyError.value = "";
  try {
    await request(
      "/api/v1/ingestion-candidates/" + selectedCandidateId.value + "/" + action,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      },
    );
    await refreshCurrentJob();
  } catch (error) {
    historyError.value =
      error instanceof ApiError && error.status === 409
        ? "候选内容已变化，请刷新后重试。"
        : errorMessage(error);
    if (error instanceof ApiError && error.status === 409) await refreshCurrentJob();
  } finally {
    candidateBusy.value = false;
  }
}

async function mergeCandidates() {
  if (selectedJobId.value === null || selectedCandidate.value === null) return;
  const participantIds = [...new Set([...selectedMergeIds.value, selectedCandidate.value.id])];
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
    await request(
      "/api/v1/ingestions/" + selectedJobId.value + "/candidates/merge",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          survivor_id: selectedCandidate.value.id,
          candidates: selectedCandidates.map((candidate) => ({
            id: candidate.id,
            expected_revision: candidate.candidate_revision,
          })),
          final_text: mergeFinalText.value,
        }),
      },
    );
    await refreshCurrentJob();
  } catch (error) {
    historyError.value =
      error instanceof ApiError && error.status === 409
        ? "候选内容已变化，请刷新后重试。"
        : errorMessage(error);
    if (error instanceof ApiError && error.status === 409) await refreshCurrentJob();
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

onMounted(loadSources);
</script>

<template>
  <section aria-label="截图采集收件箱">
    <h2>截图采集</h2>
    <SourceUpload :disabled="busy" @upload="uploadFiles" />
    <p v-if="busy" role="status">正在处理截图…</p>
    <p v-if="loadError" role="alert">{{ loadError }}</p>

    <section v-if="uploadResults.length" aria-label="本次上传结果">
      <h3>本次上传</h3>
      <ul>
        <li v-for="(result, index) in uploadResults" :key="index">
          <span v-if="result.status === 'stored'">
            {{ result.source?.original_filename }} · {{ result.job?.status }}
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
      <p v-if="sources.length === 0">还没有截图</p>
      <article v-for="asset in sources" :key="asset.id" class="source-entry">
        <h4>{{ asset.title || asset.original_filename || "截图 " + asset.id }}</h4>
        <p>{{ asset.display_width }} × {{ asset.display_height }} · {{ asset.sha256 }}</p>
        <a :href="'/api/v1/sources/' + asset.id + '/original'">打开原图</a>
        <ul aria-label="OCR 任务历史">
          <li v-for="job in asset.ingestion_jobs" :key="job.id">
            <button
              type="button"
              :aria-label="'打开导入任务 ' + job.id"
              @click="openJob(job.id)"
            >
              任务 {{ job.id }} · {{ job.status }} · {{ job.stage }} · 候选 {{ job.candidate_count }}
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

    <p v-if="historyError" role="alert">{{ historyError }}</p>
    <section v-if="selectedJob" aria-label="导入任务详情">
      <h3>任务 {{ selectedJob.id }} · {{ selectedJob.status }}</h3>
      <p v-if="selectedJob.failure_stage">失败阶段：{{ selectedJob.failure_stage }}</p>
      <pre v-if="ocrBlocks.length" aria-label="OCR 原文">{{
        ocrBlocks.map((block) => block.text).join("\n")
      }}</pre>
      <p v-else>没有识别到文字</p>
      <ul aria-label="候选题历史">
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
            {{ candidate.text }} · {{ candidate.candidate_state }}
          </button>
          <span> 来源区域 {{ candidate.sources.map((item) => item.question_source_id).join(", ") }} </span>
        </li>
      </ul>
      <p v-if="selectedCandidate && selectedCandidate.candidate_state !== 'pending_review'">
        此候选已完成审核，只能查看历史来源证据。
      </p>
      <form
        v-if="selectedCandidate && selectedCandidate.candidate_state === 'pending_review' && !selectedCandidate.archived_at"
        aria-label="候选题同任务合并"
        @submit.prevent="mergeCandidates"
      >
        <label>
          合并后正文
          <textarea v-model="mergeFinalText" aria-label="合并后题目正文" />
        </label>
        <button type="submit" :disabled="candidateBusy">合并所选候选题</button>
      </form>
      <IngestionCandidateEditor
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
        @select-source="selectedSourceId = $event"
        @save="patchCandidate"
        @split="splitCandidate"
        @archive="candidateDisposition('archive', $event)"
        @confirm="candidateDisposition('confirm', $event)"
      />
      <SourceImageViewer
        v-if="selectedCandidate"
        :sources="selectedCandidateSources"
        :selected-source-id="selectedSourceId"
        :image-width="selectedSourceAsset?.display_width ?? 0"
        :image-height="selectedSourceAsset?.display_height ?? 0"
        @select-source="selectedSourceId = $event"
      />
    </section>
  </section>
</template>

<style scoped>
.source-entry {
  margin: 1rem 0;
  padding: 0.75rem;
  border: 1px solid #d4d8df;
  border-radius: 0.5rem;
}

pre {
  max-height: 16rem;
  overflow: auto;
  white-space: pre-wrap;
}
</style>
