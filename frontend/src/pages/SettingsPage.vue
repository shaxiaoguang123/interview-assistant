<script setup lang="ts">
import { onBeforeUnmount, onMounted, shallowRef } from "vue";
import { ApiError } from "../api/client";
import { getLLMConfig, saveLLMConfig, testLLMConnection, type LLMConfig } from "../api/assistant";
import BackupSettingsPanel from "../components/settings/BackupSettingsPanel.vue";
import SystemStatusPanel from "../components/system/SystemStatusPanel.vue";

const settings = shallowRef<LLMConfig | null>(null);
const baseUrl = shallowRef("");
const model = shallowRef("");
const apiKey = shallowRef("");
const busy = shallowRef(false);
const error = shallowRef("");
const success = shallowRef("");
const connected = shallowRef(false);
let alive = true;

function isEditable(field: "base_url" | "model" | "api_key") {
  return settings.value?.editable?.[field] ?? true;
}

async function load() {
  try {
    const result = await getLLMConfig();
    if (!alive) return;
    settings.value = result;
    baseUrl.value = result.base_url;
    model.value = result.model;
  } catch (caught) {
    if (alive) error.value = caught instanceof ApiError ? caught.message : "模型配置加载失败。";
  }
}

function payloadForSave() {
  const payload: { base_url?: string; model?: string; api_key?: string } = {};
  if (isEditable("base_url")) payload.base_url = baseUrl.value;
  if (isEditable("model")) payload.model = model.value;
  if (isEditable("api_key") && apiKey.value.trim()) payload.api_key = apiKey.value.trim();
  return payload;
}

async function save() {
  if (busy.value) return;
  busy.value = true;
  error.value = "";
  success.value = "";
  connected.value = false;
  try {
    const payload = payloadForSave();
    if (!Object.keys(payload).length) {
      success.value = "这些配置由环境变量控制；修改启动环境后重启服务即可生效。";
      return;
    }
    settings.value = await saveLLMConfig(payload);
    baseUrl.value = settings.value.base_url;
    model.value = settings.value.model;
    apiKey.value = "";
    success.value = "本机配置已保存到应用数据目录，服务重启后仍可使用。";
  } catch (caught) {
    error.value = caught instanceof ApiError ? caught.message : "配置保存失败。";
  } finally {
    busy.value = false;
  }
}

async function clearLocalKey() {
  if (busy.value || !isEditable("api_key") || !settings.value?.has_api_key) return;
  if (!window.confirm("清除本机保存的 API Key？之后需要重新配置才能调用模型。")) return;
  busy.value = true;
  error.value = "";
  success.value = "";
  try {
    settings.value = await saveLLMConfig({ clear_api_key: true });
    apiKey.value = "";
    connected.value = false;
    success.value = "本机 API Key 已清除。";
  } catch (caught) {
    error.value = caught instanceof ApiError ? caught.message : "清除 API Key 失败。";
  } finally {
    busy.value = false;
  }
}

async function testConnection() {
  if (busy.value) return;
  busy.value = true;
  error.value = "";
  success.value = "";
  try {
    const result = await testLLMConnection();
    if (alive) {
      connected.value = result.connected;
      success.value = `连接成功，模型 ${result.model} 已返回文本响应。`;
    }
  } catch (caught) {
    if (alive) {
      connected.value = false;
      error.value = caught instanceof ApiError ? caught.message : "连接失败，请检查配置。";
    }
  } finally {
    if (alive) busy.value = false;
  }
}

function sourceLabel(value?: string) {
  if (value === "environment") return "环境变量控制";
  if (value === "local") return "已保存到本机";
  return "尚未配置";
}

onMounted(load);
onBeforeUnmount(() => { alive = false; apiKey.value = ""; });
</script>

<template>
  <section aria-labelledby="settings-title" class="settings-page">
    <header class="page-heading"><div><span class="eyebrow">本机偏好</span><h2 id="settings-title">设置</h2><p>管理模型连接，并将题库、练习历史、截图和个人资料备份到 ZIP 文件。</p></div><span class="badge" :class="{ accent: connected }">{{ connected ? '连接已验证' : settings?.configured ? '模型已配置' : '模型尚未配置' }}</span></header>

    <SystemStatusPanel />
    <div class="settings-grid">
      <form class="panel llm-form" aria-label="模型配置" @submit.prevent="save">
        <header><div><span class="eyebrow">可选功能</span><h3>连接模型 Provider</h3></div><span v-if="settings" class="badge">{{ settings.configuration_scope === 'environment' ? '使用环境配置' : settings.configuration_scope === 'local' ? '使用本机配置' : '未配置' }}</span></header>
        <label>Base URL<input v-model="baseUrl" type="url" aria-label="LLM Base URL" placeholder="https://your-provider.example/v1" required :disabled="busy || !isEditable('base_url')" autocomplete="off"/><small>{{ sourceLabel(settings?.base_url_source) }}</small></label>
        <label>模型名称<input v-model="model" aria-label="LLM 模型名称" placeholder="gpt-6-luna" maxlength="120" required :disabled="busy || !isEditable('model')"/><small>{{ sourceLabel(settings?.model_source) }}</small></label>
        <label>API Key<input v-model="apiKey" type="password" aria-label="LLM API Key" :placeholder="settings?.api_key_source === 'environment' ? '由环境变量提供' : settings?.has_api_key ? '本机凭据已配置；留空保留当前值' : '输入本机 Provider 凭据'" maxlength="2000" :disabled="busy || !isEditable('api_key')" autocomplete="new-password"/><small>{{ settings?.has_api_key ? `凭据已设置 · ${sourceLabel(settings.api_key_source)}` : sourceLabel(settings?.api_key_source) }}</small></label>
        <p class="helper">Base URL 和模型名保存在本机应用目录；API Key 单独保存在权限受限的文件中。密钥不会回传到页面、写入 SQLite 或包含在备份里。环境变量优先级最高。</p>
        <p v-if="settings?.data_dir" class="helper settings-data-dir">数据目录：<code>{{ settings.data_dir }}</code></p>
        <p v-if="error" role="alert" class="settings-error">{{ error }}</p><p v-if="success" role="status" class="success-banner">{{ success }}</p>
        <div class="action-row"><button type="submit" class="primary" :disabled="busy">{{ busy ? '正在处理…' : '保存本机配置' }}</button><button type="button" :disabled="busy || !settings?.configured" @click="testConnection">测试连接</button><button v-if="settings?.has_api_key && isEditable('api_key')" type="button" class="danger" :disabled="busy" @click="clearLocalKey">清除本机 Key</button></div>
      </form>
      <aside class="panel settings-help"><h3>环境变量（高级配置）</h3><p>开发者可以在启动 Flask 前设置以下变量。环境变量会覆盖本机设置；模型未配置时，题库、练习与资料管理仍可正常使用。</p><pre>LLM_BASE_URL=https://your-provider.example/v1
LLM_API_KEY=your-local-secret
LLM_MODEL=gpt-6-luna</pre><h4>数据与隐私</h4><p class="helper">应用数据位于本机数据目录。备份包保留历史 ID 和资料文件，不包含 Provider Key、OCR 模型或临时数据。</p><p class="helper">生成式 AI 只在用户主动操作并确认上下文后调用，保存结果也需要明确操作。</p></aside>
    </div>

    <BackupSettingsPanel />
  </section>
</template>

<style scoped>
.settings-page>.system-status{margin-bottom:20px}.settings-grid{display:grid;grid-template-columns:minmax(0,1.05fr) minmax(300px,.8fr);gap:24px;align-items:start}.llm-form{display:grid;gap:17px}.llm-form>header{display:flex;align-items:center;justify-content:space-between;gap:12px}.llm-form h3,.settings-help h3{font-size:18px;margin:4px 0}.llm-form label{display:grid;gap:5px}.llm-form label small{font-size:12px;color:var(--muted)}.llm-form>p{margin:0}.settings-data-dir code{overflow-wrap:anywhere}.settings-help p{overflow-wrap:anywhere}.settings-help pre{margin:18px 0;padding:14px;background:#f0f3f7;border-radius:8px;overflow:auto;white-space:pre;line-height:1.6;font-size:12px}.settings-help h4{margin:20px 0 6px}.settings-error{color:var(--danger)}@media(max-width:1000px){.settings-grid{grid-template-columns:1fr}}@media(max-width:767px){.llm-form .action-row{align-items:stretch;flex-direction:column}.llm-form .action-row button{width:100%}}
</style>
