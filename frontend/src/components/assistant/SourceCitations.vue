<script setup lang="ts">
import { RouterLink } from 'vue-router';
import type { AssistantSource } from '../../api/assistant';
defineProps<{sources:AssistantSource[];showChunks?:boolean}>();
const methodLabels:Record<string,string>={fts:'全文检索命中',keyword_fallback:'关键词回退命中',selected_excerpt:'未命中关键词 · 选中资料摘要'};
</script>
<template><section class="assistant-sources" aria-label="AI 实际来源"><h4>本次发送的资料来源</h4><p v-if="!sources.length" class="helper">不使用个人资料。仅发送题目和当前回答（如有）。</p><ol v-else><li v-for="(source,i) in sources" :key="source.material_version_id"><div class="source-line"><span class="badge">{{ source.label||`S${i+1}` }}</span><RouterLink :to="`/materials?material_id=${source.material_id}&version_id=${source.material_version_id}`">{{ source.title }} · v{{ source.version_no }}</RouterLink><span class="mono">{{ source.sha256.slice(0,10) }}…</span></div><details v-if="showChunks&&source.chunks?.length"><summary>查看将发送的 {{ source.chunks.length }} 个片段</summary><div v-for="chunk in source.chunks" :key="chunk.chunk_id"><p class="helper">片段 #{{ chunk.chunk_id }}{{ chunk.page_number?` · 第 ${chunk.page_number} 页`:'' }} · {{ methodLabels[chunk.retrieval_method] }}</p><pre>{{ chunk.text }}</pre></div></details><small v-else class="helper">实际片段 ID：{{ source.chunk_ids?.join('、')||'—' }}</small></li></ol></section></template>
<style scoped>
.assistant-sources{padding-top:16px;}.assistant-sources ol{padding:0;list-style:none;margin:0;}.assistant-sources li{padding:12px 0;border-top:1px solid var(--border);}.source-line{display:flex;align-items:center;gap:8px;flex-wrap:wrap;}.assistant-sources pre{max-height:260px;overflow:auto;font-family:inherit;font-size:13px;}.assistant-sources small{display:block;margin-top:6px;}
</style>
