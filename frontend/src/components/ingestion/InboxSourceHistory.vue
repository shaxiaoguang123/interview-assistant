<script setup lang="ts">
import type { SourceAsset } from "../../api/ingestion";

defineProps<{
  sources: SourceAsset[];
  selectedJobId: number | null;
  busy: boolean;
  stateLabel: (value: string) => string;
}>();

const emit = defineEmits<{
  "open-job": [jobId: number];
  "resume-job": [jobId: number];
  "retry-source": [sourceId: number];
}>();
</script>

<template>
  <details class="inbox-queue-section inbox-source-history" aria-label="截图与导入历史" :open="!selectedJobId">
    <summary class="inbox-section-heading">
      <div><span class="eyebrow">来源</span><h3>截图历史</h3></div>
      <span class="badge">{{ sources.length }} 张</span>
    </summary>
    <p v-if="sources.length === 0" class="empty-state">还没有截图</p>
    <article v-for="asset in sources" :key="asset.id" class="source-entry">
      <h4>{{ asset.title || asset.original_filename || "截图 " + asset.id }}</h4>
      <p class="muted">{{ asset.display_width }} × {{ asset.display_height }} · {{ asset.ingestion_jobs.length }} 次导入</p>
      <details><summary>来源校验信息</summary><p class="mono">{{ asset.sha256 }}</p></details>
      <a :href="'/api/v1/sources/' + asset.id + '/original'">打开原图</a>
      <ul aria-label="OCR 任务历史">
        <li v-for="job in asset.ingestion_jobs" :key="job.id">
          <button
            type="button"
            :aria-label="'打开导入任务 ' + job.id"
            :aria-pressed="job.id === selectedJobId"
            @click="emit('open-job', job.id)"
          >
            任务 {{ job.id }} · {{ stateLabel(job.status) }} · 自动候选 {{ job.candidate_count }}
          </button>
          <button
            v-if="job.status === 'queued' || job.status === 'running'"
            type="button"
            :disabled="busy"
            :aria-label="job.status === 'queued' ? '继续识别任务 ' + job.id : '查看任务状态 ' + job.id"
            @click="emit('resume-job', job.id)"
          >
            {{ job.status === "queued" ? "继续识别" : "查看状态" }}
          </button>
          <span v-if="job.error_code">{{ job.error_code }} · {{ job.error_message }}</span>
          <button
            v-if="job.status === 'failed'"
            type="button"
            :disabled="busy"
            :aria-label="'重试截图 ' + asset.id"
            @click="emit('retry-source', asset.id)"
          >
            重新识别
          </button>
        </li>
      </ul>
    </article>
  </details>
</template>
