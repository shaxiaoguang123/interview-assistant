<script setup lang="ts">
import { shallowRef,ref } from 'vue';
import { ApiError } from '../../api/client';
import { uploadMaterial,materialLabels,type Project,type Material } from '../../api/materials';
const props=defineProps<{projects:Project[];projectId?:number;materialId?:number}>();
const emit=defineEmits<{uploaded:[material:Material];cancel:[]}>();
const file=shallowRef<File|null>(null),busy=shallowRef(false),error=shallowRef(''),title=shallowRef(''),kind=shallowRef('resume'),project=shallowRef<number|null>(props.projectId??null);
let alive=true;
import { onBeforeUnmount } from 'vue';onBeforeUnmount(()=>alive=false);
function selected(event:Event){file.value=(event.target as HTMLInputElement).files?.[0]??null;if(file.value&&!title.value)title.value=file.value.name;}
async function upload(){if(!file.value||busy.value)return;busy.value=true;error.value='';try{const result=await uploadMaterial(file.value,{title:title.value,kind:kind.value,project_id:project.value},props.materialId);if(alive)emit('uploaded',result);}catch(e){if(alive)error.value=e instanceof ApiError?e.message:'资料上传失败，请重试。';}finally{if(alive)busy.value=false;}}
</script>
<template><form class="material-upload" aria-label="上传资料" @submit.prevent="upload"><h3>{{ materialId?'替换文件，追加新版本':'上传资料' }}</h3><p class="helper">TXT / Markdown / PDF / DOCX · 最大 10 MB。扫描型 PDF 需要先转换为可提取文字的文件。</p><label>资料文件<input type="file" accept=".txt,.md,.markdown,.pdf,.docx" aria-label="资料文件" :disabled="busy" required @change="selected"/></label><template v-if="!materialId"><label>资料标题<input v-model="title" aria-label="资料标题" maxlength="240" :disabled="busy" required/></label><div class="upload-grid"><label>资料类型<select v-model="kind" aria-label="资料类型" :disabled="busy"><option v-for="(label,key) in materialLabels" v-show="key!=='project_profile'" :key="key" :value="key" :disabled="key==='project_profile'">{{ label }}</option></select></label><label>关联项目<select v-model="project" aria-label="上传关联项目" :disabled="busy"><option :value="null">独立资料 / 通用简历</option><option v-for="p in projects.filter(p=>!p.archived_at)" :key="p.id" :value="p.id">{{ p.name }}</option></select></label></div></template><p v-if="error" role="alert">{{ error }}</p><div class="action-row"><button type="submit" :disabled="busy||!file">{{ busy?'正在提取文字…':materialId?'上传新版本':'上传并提取文字' }}</button><button type="button" :disabled="busy" @click="emit('cancel')">取消</button></div></form></template>
<style scoped>
.material-upload{display:grid;gap:16px;padding:20px;background:var(--brand-soft);border:1px solid var(--border);border-radius:12px;}.material-upload h3,.material-upload p{margin:0;}.upload-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px;}@media(max-width:767px){.upload-grid{grid-template-columns:1fr;}}
</style>
