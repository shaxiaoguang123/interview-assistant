<script setup lang="ts">
defineProps<{
  topics: Array<{ id: number; name: string; is_active: boolean }>;
  tags: Array<{ id: number; name: string; is_active: boolean }>;
}>();
</script>

<template>
  <dl class="taxonomy-badges" aria-label="题目分类与标签">
    <dt>Topic</dt>
    <dd>
      <span class="badge accent" v-for="topic in topics" :key="topic.id">
        {{ topic.name }}<template v-if="!topic.is_active">（停用）</template>
      </span>
    </dd>
    <dt>Tag</dt>
    <dd>
      <span class="badge" v-for="tag in tags" :key="tag.id">
        {{ tag.name }}<template v-if="!tag.is_active">（停用）</template>
      </span>
    </dd>
  </dl>
</template>
