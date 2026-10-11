<script setup lang="ts">
import { onBeforeUnmount, onMounted, shallowRef } from "vue";
import { ApiError } from "../../api/client";
import { getSystemStatus, type SystemStatus } from "../../api/system";

withDefaults(defineProps<{ compact?: boolean }>(), { compact: false });

const status = shallowRef<SystemStatus | null>(null);
const loading = shallowRef(true);
const error = shallowRef("");
let revision = 0;

async function load() {
  const requestId = ++revision;
  loading.value = true;
  error.value = "";
  try {
    const result = await getSystemStatus();
    if (result?.application !== "agent-interview-assistant" || !result.database || !result.ocr || !result.llm) {
      throw new Error("unexpected status response");
    }
    if (requestId === revision) status.value = result;
  } catch (caught) {
    if (requestId === revision) {
      error.value = caught instanceof ApiError ? caught.message : "本机环境状态暂时无法读取。";
    }
  } finally {
    if (requestId === revision) loading.value = false;
  }
}

function revisionLabel(value: string | string[] | null) {
  const revisions = Array.isArray(value) ? value : value ? [value] : [];
  return revisions.length ? revisions.map((revision) => revision.split("_", 1)[0]).join(", ") : "未初始化";
}

onMounted(() => void load());
onBeforeUnmount(() => { revision += 1; });
</script>

<template>
  <section class="panel system-status" :class="{ 'system-status-compact': compact }" aria-labelledby="system-status-title">
    <header class="system-status-heading">
      <div><span class="eyebrow">本机环境</span><h3 id="system-status-title">运行状态</h3></div>
      <button type="button" class="system-status-refresh" :disabled="loading" @click="load">{{ loading ? '检查中…' : '重新检查' }}</button>
    </header>
    <p v-if="loading && !status" role="status" class="system-status-message">正在检查本机服务…</p>
    <div v-else-if="error" class="system-status-error"><p role="alert">{{ error }}</p><button type="button" @click="load">重试</button></div>
    <template v-else-if="status">
      <div class="system-status-grid">
        <div class="system-status-item">
          <span>后端服务</span><strong :data-ready="status.backend.ready">{{ status.backend.ready ? '运行正常' : '不可用' }}</strong>
        </div>
        <div class="system-status-item">
          <span>数据库</span><strong :data-ready="status.database.ready">{{ status.database.ready ? '已就绪' : status.database.state === 'not_initialized' ? '待初始化' : status.database.state === 'upgrade_required' ? '需要升级' : '暂不可用' }}</strong>
          <small v-if="status.database.state === 'not_initialized'">首次启动会初始化本机数据库</small>
          <small v-else-if="status.database.state === 'upgrade_required'">关闭应用后重新启动，会先备份再升级</small>
          <small v-else>版本 {{ revisionLabel(status.database.current_revision) }}</small>
        </div>
        <div class="system-status-item">
          <span>OCR 识别</span><strong :data-ready="status.ocr.ready">{{ status.ocr.ready ? '模型已校验' : status.ocr.state === 'missing' ? '尚未准备' : '需要检查' }}</strong>
          <small>{{ status.ocr.message }}</small>
        </div>
        <div class="system-status-item">
          <span>LLM 模型</span><strong :data-ready="status.llm.configured">{{ status.llm.configured ? '已配置' : '可稍后配置' }}</strong>
          <small>未配置不影响题库、练习和项目管理</small>
        </div>
      </div>
      <footer class="system-status-footer"><span>Python {{ status.python.version }}{{ status.python.supported ? '' : ' · 建议使用 3.12' }}</span><span>{{ status.storage.location === 'default' ? '默认本机数据目录' : '自定义本机数据目录' }}</span></footer>
    </template>
  </section>
</template>

<style scoped>
.system-status{min-width:0}.system-status-heading{display:flex;align-items:center;justify-content:space-between;gap:12px}.system-status-heading h3{font-size:17px;margin:4px 0 0}.system-status-refresh,.system-status-error button{min-height:44px;padding:7px 12px;border:1px solid var(--border);border-radius:var(--control-radius);background:var(--surface);color:var(--text);font-weight:600}.system-status-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-top:16px}.system-status-item{display:grid;gap:5px;min-width:0;padding:12px;border-radius:8px;background:var(--surface-muted,#f5f7fa)}.system-status-item>span,.system-status-item small,.system-status-footer{font-size:12px;color:var(--muted)}.system-status-item strong{color:var(--warning)}.system-status-item strong[data-ready="true"]{color:var(--success,#287b5b)}.system-status-item small{line-height:1.45;overflow-wrap:anywhere}.system-status-footer{display:flex;justify-content:space-between;gap:12px;margin-top:12px}.system-status-compact .system-status-item{padding:10px}.system-status-message{color:var(--muted)}.system-status-error{display:flex;align-items:center;justify-content:space-between;gap:12px}.system-status-error p{color:var(--danger)}@media(max-width:760px){.system-status-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:480px){.system-status-grid{gap:8px}.system-status-item{padding:10px}.system-status-footer{flex-direction:column;gap:4px}.system-status-error{align-items:flex-start;flex-direction:column}.system-status-error button{width:100%}}
</style>
