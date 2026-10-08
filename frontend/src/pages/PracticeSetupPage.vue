<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { ApiError, request } from "../api/client";

interface TaxonomyItem {
  id: number;
  name: string;
  is_active: boolean;
}

type PracticeMode = "random" | "topic" | "tag";

const router = useRouter();
const mode = ref<PracticeMode>("random");
const topics = ref<TaxonomyItem[]>([]);
const tags = ref<TaxonomyItem[]>([]);
const selectedTopicIds = ref<number[]>([]);
const selectedTagIds = ref<number[]>([]);
const limit = ref(10);
const errorMessage = ref("");
const starting = ref(false);

function displayError(error: unknown): string {
  if (error instanceof ApiError) {
    const details = Object.values(error.fields);
    return details.length ? `${error.message}: ${details.join("；")}` : error.message;
  }
  return "请求失败，请稍后重试。";
}

async function loadTaxonomy(): Promise<void> {
  try {
    const [topicRows, tagRows] = await Promise.all([
      request<TaxonomyItem[]>("/api/v1/topics"),
      request<TaxonomyItem[]>("/api/v1/tags"),
    ]);
    topics.value = topicRows.filter((item) => item.is_active);
    tags.value = tagRows.filter((item) => item.is_active);
  } catch (error) {
    errorMessage.value = displayError(error);
  }
}

async function startPractice(): Promise<void> {
  errorMessage.value = "";
  starting.value = true;
  const filters =
    mode.value === "topic"
      ? { topic_ids: selectedTopicIds.value }
      : mode.value === "tag"
        ? { tag_ids: selectedTagIds.value }
        : {};
  try {
    const practiceSession = await request<{ id: number }>("/api/v1/practice-sessions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode: mode.value, filters, limit: Number(limit.value) }),
    });
    await router.push({ name: "practice-session", params: { id: practiceSession.id } });
  } catch (error) {
    errorMessage.value = displayError(error);
  } finally {
    starting.value = false;
  }
}

onMounted(loadTaxonomy);
</script>

<template>
  <section aria-labelledby="practice-setup-title">
    <h2 id="practice-setup-title">开始练习</h2>
    <p v-if="errorMessage" role="alert">{{ errorMessage }}</p>
    <form aria-label="练习设置" @submit.prevent="startPractice">
      <label>
        练习模式
        <select v-model="mode" aria-label="练习模式">
          <option value="random">随机练习</option>
          <option value="topic">分类练习</option>
          <option value="tag">知识点练习</option>
        </select>
      </label>
      <label v-if="mode === 'topic'">
        Topic
        <select v-model="selectedTopicIds" multiple aria-label="选择 Topic">
          <option v-for="topic in topics" :key="topic.id" :value="topic.id">{{ topic.name }}</option>
        </select>
      </label>
      <label v-if="mode === 'tag'">
        Tag
        <select v-model="selectedTagIds" multiple aria-label="选择 Tag">
          <option v-for="tag in tags" :key="tag.id" :value="tag.id">{{ tag.name }}</option>
        </select>
      </label>
      <label>
        题目数量
        <input v-model.number="limit" type="number" min="1" max="100" aria-label="题目数量" />
      </label>
      <button type="submit" :disabled="starting">{{ starting ? "正在创建…" : "开始练习" }}</button>
    </form>
  </section>
</template>
