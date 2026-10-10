<script setup lang="ts">
import { computed } from 'vue';
import type { Material,Project } from '../../api/materials';
import type { ContextSelection } from '../../api/assistant';
const props=defineProps<{projects:Project[];materials:Material[];busy:boolean}>();
const selection=defineModel<ContextSelection>({required:true});
const activeProjects=computed(()=>props.projects.filter(p=>p.is_active&&!p.archived_at));
const projectDocuments=computed(()=>props.materials.filter(m=>m.project_id!==null&&selection.value.project_ids.includes(m.project_id)));
const standalone=computed(()=>props.materials.filter(m=>!m.is_system_managed&&m.is_active&&m.include_in_context&&!m.archived_at&&(!m.project_id||activeProjects.value.some(p=>p.id===m.project_id))));
function toggle(field:keyof ContextSelection,id:number,checked:boolean){selection.value={...selection.value,[field]:checked?[...new Set([...selection.value[field],id])]:selection.value[field].filter(v=>v!==id)};}
function checked(event:Event){return (event.target as HTMLInputElement).checked;}
function clear(){selection.value={project_ids:[],material_ids:[],exclude_material_ids:[]};}
</script>
<template><section class="context-selector" aria-label="AI 上下文选择"><div class="context-heading"><h4>选择事实资料</h4><button type="button" :disabled="busy" @click="clear">不使用个人资料</button></div><p class="helper">默认不发送任何个人资料。选择项目会展开其有效且允许上下文的当前版本，可再排除具体文件。</p><div class="context-grid"><fieldset><legend>项目经历</legend><p v-if="!activeProjects.length" class="helper">暂无有效项目</p><label v-for="p in activeProjects" :key="p.id"><input type="checkbox" :checked="selection.project_ids.includes(p.id)" :disabled="busy" @change="toggle('project_ids',p.id,checked($event))"/>{{ p.name }}</label></fieldset><fieldset><legend>单独选择简历 / 文档</legend><p v-if="!standalone.length" class="helper">暂无可用资料</p><label v-for="m in standalone" :key="m.id"><input type="checkbox" :checked="selection.material_ids.includes(m.id)" :disabled="busy" @change="toggle('material_ids',m.id,checked($event))"/>{{ m.title }}</label></fieldset></div><details v-if="projectDocuments.length" class="context-exclusions" open><summary>展开的项目资料 · {{ projectDocuments.length }} 份</summary><label v-for="m in projectDocuments" :key="m.id"><input type="checkbox" :checked="m.is_active&&m.include_in_context&&!m.archived_at&&!selection.exclude_material_ids.includes(m.id)" :disabled="busy||!m.is_active||!m.include_in_context||!!m.archived_at" @change="toggle('exclude_material_ids',m.id,!checked($event))"/><span>{{ m.title }} <small class="muted">{{ !m.is_active||!m.include_in_context||m.archived_at?'不允许发送':`当前 v${m.current_version?.version_no??0}` }}</small></span></label></details></section></template>
<style scoped>
.context-heading{display:flex;align-items:center;justify-content:space-between;gap:16px;}.context-heading h4{margin:0;}.context-heading button{font-size:13px;}.context-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px;}.context-grid label,.context-exclusions label{font-size:14px;overflow-wrap:anywhere;}.context-exclusions{margin-top:16px;}.context-selector>.helper{margin:12px 0 16px;}@media(max-width:767px){.context-grid{grid-template-columns:1fr;}}
</style>
