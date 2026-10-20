<script setup lang="ts">
import { ref } from "vue";

defineProps<{ disabled?: boolean }>();
const emit = defineEmits<{
  upload: [files: File[]];
}>();

const selectedFiles = ref<File[]>([]);

function onFilesChanged(event: Event) {
  const input = event.target as HTMLInputElement;
  selectedFiles.value = Array.from(input.files ?? []);
}

function submit() {
  if (selectedFiles.value.length === 0) return;
  emit("upload", [...selectedFiles.value]);
}
</script>

<template>
  <form class="source-upload" aria-label="截图上传" @submit.prevent="submit">
    <div class="source-upload-copy">
      <span class="eyebrow">01 · 导入来源</span>
      <h3>上传截图</h3>
      <p class="helper">PNG、JPEG、WebP · 每张截图独立处理</p>
    </div>
    <div class="source-upload-controls">
      <label>
        选择截图
        <input
          aria-label="选择截图文件"
          type="file"
          accept="image/jpeg,image/png,image/webp"
          multiple
          :disabled="disabled"
          @change="onFilesChanged"
        />
      </label>
      <ul v-if="selectedFiles.length" class="source-upload-files">
        <li v-for="(file, index) in selectedFiles" :key="index + ':' + file.name + file.size">
          {{ file.name }}
        </li>
      </ul>
      <button type="submit" :disabled="disabled || selectedFiles.length === 0">上传截图</button>
    </div>
  </form>
</template>
