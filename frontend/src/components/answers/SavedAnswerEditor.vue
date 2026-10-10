<script setup lang="ts">
import { ref } from 'vue';
const props = withDefaults(defineProps<{initial?:string;busy?:boolean;editing?:boolean}>(),{initial:'',busy:false,editing:false});
const emit = defineEmits<{save:[content:string];cancel:[]}>();
const content = ref(props.initial);
</script>
<template>
  <form class="answer-editor" @submit.prevent="emit('save',content)">
    <label>回答正文<textarea v-model="content" aria-label="回答正文" maxlength="100000" :disabled="busy" rows="8" /></label>
    <p class="helper">{{ editing ? '保存会追加新版本，旧正文与评分继续保留。新版本需要重新评分。' : '只有点击保存才进入回答库；质量评分可在保存后设置。' }}</p>
    <div class="action-row"><button type="submit" :disabled="busy || !content.trim()">{{ busy ? '正在保存…' : editing ? '保存新版本' : '保存回答' }}</button><button type="button" :disabled="busy" @click="emit('cancel')">取消</button></div>
  </form>
</template>
<style scoped>
.answer-editor {padding:20px;background:var(--brand-soft);border:1px solid var(--border);border-radius:12px;}
.answer-editor textarea {margin-top:8px;min-height:220px;background:var(--surface);font-weight:400;}
.answer-editor .helper {margin:16px 0;}
</style>
