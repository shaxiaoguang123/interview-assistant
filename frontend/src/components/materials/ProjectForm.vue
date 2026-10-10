<script setup lang="ts">
import { reactive, watch } from 'vue';
import type { ProjectInput,Project } from '../../api/materials';
const props=defineProps<{initial?:Project;busy?:boolean}>();
const emit=defineEmits<{save:[value:ProjectInput];cancel:[]}>();
const empty=():ProjectInput=>({name:'',summary:'',tech_stack:'',personal_role:'',challenges:'',outcomes:'',highlights:'',notes:'',is_active:true});
const form=reactive<ProjectInput>(empty());
watch(()=>props.initial,row=>Object.assign(form,empty(),row??{}),{immediate:true});
const fields:Array<{key:Exclude<keyof ProjectInput,'name'|'is_active'>;label:string;hint:string}>=[{key:'summary',label:'项目简介',hint:'项目解决的问题、用户与核心能力'},{key:'tech_stack',label:'技术栈',hint:'例如 Flask、LangGraph、SQLite'},{key:'personal_role',label:'个人职责',hint:'你实际负责的设计与实现'},{key:'challenges',label:'技术难点',hint:'遇到的问题及解决过程'},{key:'outcomes',label:'项目成果',hint:'可验证的结果；没有指标时不要补造'},{key:'highlights',label:'项目亮点',hint:'面试中值得展开的设计决策'},{key:'notes',label:'管理备注',hint:'仅供自己管理，不会自动加入 AI 上下文'}];
function submit(){const value=Object.fromEntries(Object.keys(empty()).map(k=>[k,form[k as keyof ProjectInput]])) as unknown as ProjectInput;emit('save',value);}
</script>
<template><form class="project-form" aria-label="项目表单" @submit.prevent="submit"><label>项目名称<input v-model="form.name" aria-label="项目名称" maxlength="240" required :disabled="busy||!!initial?.archived_at"/></label><div class="project-form-grid"><label v-for="field in fields" :key="field.key" :class="{'full-width':field.key==='summary'||field.key==='notes'}">{{ field.label }}<textarea v-model="form[field.key]" :aria-label="field.label" :placeholder="field.hint" maxlength="20000" :rows="field.key==='summary'?4:3" :disabled="busy||!!initial?.archived_at"/><small class="helper">{{ field.hint }}</small></label></div><label><input v-model="form.is_active" type="checkbox" :disabled="busy||!!initial?.archived_at"/>项目有效，可参与资料选择</label><p class="helper">保存事实字段会自动追加 Profile 版本。备注和有效状态变化不会产生事实版本。</p><div v-if="!initial?.archived_at" class="action-row"><button type="submit" :disabled="busy||!form.name.trim()">{{ busy?'正在保存…':initial?'保存项目':'创建项目' }}</button><button v-if="!initial" type="button" :disabled="busy" @click="emit('cancel')">取消</button></div></form></template>
<style scoped>
.project-form{display:grid;gap:20px;}.project-form-grid{display:grid;grid-template-columns:1fr 1fr;gap:20px;}.project-form textarea{font-weight:400;min-height:100px;}.full-width{grid-column:1/-1;}.project-form .helper{margin:0;}.project-form small{font-weight:400;}
@media(max-width:767px){.project-form-grid{grid-template-columns:1fr;}}
</style>
