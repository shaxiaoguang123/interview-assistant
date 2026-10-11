<script setup lang="ts">
import { shallowRef } from "vue";
import { ApiError } from "../../api/client";
import { downloadBackup, formatBackupBytes, inspectBackup, type BackupInspection } from "../../api/backups";

const selectedFile = shallowRef<File | null>(null);
const inspection = shallowRef<BackupInspection | null>(null);
const busy = shallowRef(false);
const error = shallowRef("");
const notice = shallowRef("");

function selected(event: Event) {
  selectedFile.value = (event.target as HTMLInputElement).files?.[0] ?? null;
  inspection.value = null;
  error.value = "";
  notice.value = "";
}

async function exportArchive() {
  if (busy.value) return;
  busy.value = true;
  error.value = "";
  notice.value = "";
  try {
    const result = await downloadBackup();
    const url = URL.createObjectURL(result.blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = result.filename;
    anchor.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    notice.value = "备份已生成并下载。请将 ZIP 保存到安全位置。";
  } catch (caught) {
    error.value = caught instanceof ApiError ? caught.message : "备份导出失败，请检查磁盘空间后重试。";
  } finally {
    busy.value = false;
  }
}

async function validateArchive() {
  if (!selectedFile.value || busy.value) return;
  busy.value = true;
  error.value = "";
  notice.value = "";
  inspection.value = null;
  try {
    inspection.value = await inspectBackup(selectedFile.value);
    notice.value = "校验通过。恢复前请先关闭应用，并在终端使用离线恢复命令。";
  } catch (caught) {
    error.value = caught instanceof ApiError ? caught.message : "备份校验失败；现有数据未受影响。";
  } finally {
    busy.value = false;
  }
}

function formatCreatedAt(value: string | null) {
  if (!value) return "时间未知";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "时间未知" : new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short" }).format(date);
}
</script>

<template>
  <section class="panel backup-panel" aria-labelledby="backup-title">
    <header class="backup-heading"><div><span class="eyebrow">本机数据管理</span><h3 id="backup-title">备份与恢复</h3><p>完整保存数据库、截图、OCR 来源、项目资料和历史版本，便于迁移到新的数据目录。</p></div><span class="badge">不包含 API Key</span></header>
    <div class="backup-actions">
      <article class="backup-action-card"><div><h4>导出完整备份</h4><p>使用 SQLite 在线备份快照，包含运行中的 WAL 数据。导出前会校验引用文件及哈希。</p></div><button class="primary" :disabled="busy" @click="exportArchive">{{ busy ? '正在处理…' : '下载备份 ZIP' }}</button></article>
      <article class="backup-action-card backup-inspect-card"><div><h4>检查已有备份</h4><p>校验 ZIP 清单、文件哈希、数据库完整性、外键和资料引用。</p></div><label class="backup-file-label">选择备份 ZIP<input type="file" accept=".zip,application/zip" :disabled="busy" @change="selected" /></label><button :disabled="busy || !selectedFile" @click="validateArchive">{{ busy ? '正在校验…' : '校验备份' }}</button></article>
    </div>
    <p v-if="error" class="backup-message error-message" role="alert">{{ error }}</p>
    <p v-if="notice" class="backup-message success-message" role="status">{{ notice }}</p>
    <section v-if="inspection" class="backup-inspection" aria-label="备份检查结果">
      <div class="backup-inspection-title"><span class="badge accent">校验通过</span><strong>{{ selectedFile?.name }}</strong></div>
      <dl><div><dt>备份时间</dt><dd>{{ formatCreatedAt(inspection.created_at) }}</dd></div><div><dt>数据库版本</dt><dd>{{ inspection.schema_revision }}</dd></div><div><dt>备份大小</dt><dd>{{ formatBackupBytes(inspection.total_bytes) }}</dd></div><div><dt>关联文件</dt><dd>{{ inspection.file_count }} 个</dd></div></dl>
      <ul class="backup-counts"><li>题目 {{ inspection.data_counts.questions ?? 0 }}</li><li>练习评价 {{ inspection.data_counts.practice_reviews ?? 0 }}</li><li>保存回答 {{ inspection.data_counts.saved_answers ?? 0 }}</li><li>项目 {{ inspection.data_counts.projects ?? 0 }}</li><li>资料 {{ inspection.data_counts.materials ?? 0 }}</li><li>截图 {{ inspection.data_counts.source_assets ?? 0 }}</li><li>AI 输出 {{ inspection.data_counts.assistant_outputs ?? 0 }}</li></ul>
    </section>
    <details class="restore-guide"><summary>如何安全恢复</summary><ol><li>先检查备份并妥善保留原 ZIP。</li><li>关闭 Agent Interview Assistant 和 Flask 服务。</li><li>在项目的 <code>backend</code> 目录运行下面命令，目标目录建议使用新的空目录。</li><li>将应用的 <code>APP_DATA_DIR</code> 指向恢复后的目录，再启动应用。若设置了自定义 <code>DATABASE_URL</code> 或 <code>SOURCE_STORAGE_DIR</code>，也要指向新目录中的恢复数据。</li></ol><pre>python -m app.maintenance inspect --backup "&lt;备份 ZIP 路径&gt;"
python -m app.maintenance restore --backup "&lt;备份 ZIP 路径&gt;" --target "&lt;新的 APP_DATA_DIR&gt;"</pre><p class="helper">已有目标目录不会静默覆盖。若确需替换，命令要求额外输入确认语，并将旧目录保留为可恢复副本。恢复过程在暂存目录校验数据库和文件后才切换。</p><p class="helper">API Key 和 Provider 凭据不在备份中；新目录启动后可在此页重新配置。</p></details>
  </section>
</template>

<style scoped>
.backup-panel{margin-top:24px}.backup-heading{display:flex;align-items:flex-start;justify-content:space-between;gap:16px}.backup-heading h3{font-size:18px;margin:4px 0}.backup-heading p,.backup-action-card p{margin:0;color:var(--muted);font-size:13px;line-height:1.55;max-width:76ch}.backup-actions{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px;margin-top:20px}.backup-action-card{display:grid;align-content:space-between;gap:18px;padding:18px;border:1px solid var(--border);border-radius:10px;background:#fbfcfe}.backup-action-card h4{margin:0 0 6px;font-size:15px}.backup-action-card button{justify-self:start}.backup-inspect-card{grid-template-columns:minmax(0,1fr) auto;align-items:end}.backup-inspect-card>div{grid-column:1/-1}.backup-file-label{display:grid;gap:6px;min-width:0;font-size:13px;font-weight:600}.backup-file-label input{max-width:100%;min-height:44px;font-weight:400}.backup-message{margin:16px 0 0;padding:12px 14px;border-radius:8px;font-size:13px}.error-message{background:var(--danger-soft);color:var(--danger)}.success-message{background:var(--success-soft);color:var(--success)}.backup-inspection{margin-top:18px;padding:16px;border:1px solid #b7d9ca;border-radius:10px;background:var(--success-soft)}.backup-inspection-title{display:flex;align-items:center;gap:10px;flex-wrap:wrap}.backup-inspection dl{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:16px 0}.backup-inspection dl div{min-width:0}.backup-inspection dt{font-size:12px;color:var(--muted)}.backup-inspection dd{margin:2px 0 0;font-weight:650;overflow-wrap:anywhere}.backup-counts{display:flex;flex-wrap:wrap;gap:8px 18px;margin:0;padding:0;list-style:none;font-size:13px}.restore-guide{margin-top:20px;padding-top:16px;border-top:1px solid var(--border)}.restore-guide summary{cursor:pointer;font-weight:650}.restore-guide ol{padding-left:22px;color:var(--ink)}.restore-guide li{padding:3px 0}.restore-guide pre{max-width:100%;overflow-x:auto;padding:14px;background:#f0f3f7;border-radius:8px;white-space:pre;line-height:1.6;font-size:12px}.restore-guide .helper{margin-bottom:8px}@media(max-width:767px){.backup-actions{grid-template-columns:1fr}.backup-inspect-card{grid-template-columns:1fr}.backup-inspect-card>div{grid-column:auto}.backup-inspection dl{grid-template-columns:repeat(2,minmax(0,1fr))}.backup-heading{flex-direction:column}.backup-action-card button{width:100%}}
</style>
