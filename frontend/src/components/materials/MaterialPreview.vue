<script setup lang="ts">
import { onBeforeUnmount,ref,shallowRef,watch } from 'vue';
import { ApiError } from '../../api/client';
import { getMaterialVersions,getMaterialVersion,type MaterialVersion,type Material } from '../../api/materials';
const props=defineProps<{material:Material;versionId?:number}>();
const versions=ref<MaterialVersion[]>([]),selected=shallowRef<number|null>(null),preview=shallowRef<MaterialVersion|null>(null),loading=shallowRef(false),error=shallowRef('');
let revision=0,loadRevision=0;
async function load(){const r=++revision;loadRevision++;versions.value=[];preview.value=null;error.value='';try{const result=await getMaterialVersions(props.material.id);if(r!==revision)return;versions.value=result;selected.value=result.some(v=>v.id===props.versionId)?props.versionId!:result[0]?.id??null;if(selected.value)await show(selected.value);}catch(e){if(r===revision)error.value=e instanceof ApiError?e.message:'版本加载失败。';}}
async function show(id:number){const r=++loadRevision;loading.value=true;error.value='';try{const result=await getMaterialVersion(id);if(r===loadRevision)preview.value=result;}catch(e){if(r===loadRevision)error.value=e instanceof ApiError?e.message:'正文加载失败。';}finally{if(r===loadRevision)loading.value=false;}}
watch(()=>[props.material.id,props.material.version_count,props.versionId],()=>void load(),{immediate:true});
onBeforeUnmount(()=>{revision++;loadRevision++;});
</script>
<template><section class="material-preview" aria-label="资料版本预览"><div class="preview-heading"><label>历史版本<select v-model="selected" aria-label="资料版本" @change="selected&&show(selected)"><option v-for="version in versions" :key="version.id" :value="version.id">v{{ version.version_no }} · {{ new Date(version.created_at).toLocaleDateString('zh-CN') }} · {{ version.original_filename }}</option></select></label><a v-if="preview" :href="preview.download_url">下载此版本</a></div><p v-if="error" role="alert">{{ error }} <button @click="load">重试</button></p><p v-if="loading" role="status">正在读取提取文字…</p><template v-if="preview"><div class="record-meta"><span class="badge">文字已提取 · {{ preview.text?.length??0 }} 字</span><span class="mono">SHA-256 {{ preview.sha256.slice(0,12) }}…</span></div><pre class="material-text" aria-label="提取文字">{{ preview.text }}</pre><p class="helper">历史版本保留原始文件与解析片段，后续修改不会改变旧 AI 引用。</p></template></section></template>
<style scoped>
.preview-heading{display:flex;align-items:center;justify-content:space-between;gap:16px;margin:20px 0;}.preview-heading label{flex:1;min-width:0;}.preview-heading a{flex-shrink:0;}.material-text{max-height:520px;overflow:auto;white-space:pre-wrap;font-family:inherit;font-size:14px;line-height:1.85;background:var(--canvas);}.material-preview .record-meta{flex-wrap:wrap;}.material-preview .helper{margin:0;}@media(max-width:767px){.preview-heading{flex-wrap:wrap;}.preview-heading label{flex-basis:100%;}.material-text{max-height:420px;}}
</style>
