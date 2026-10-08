<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { ApiError, request } from "../api/client";

interface TopicItem {
  id: number;
  parent_id: number | null;
  slug: string;
  name: string;
  sort_order: number;
  is_active: boolean;
}

interface TagItem {
  id: number;
  name: string;
  is_active: boolean;
}

const topics = ref<TopicItem[]>([]);
const tags = ref<TagItem[]>([]);
const topicNameDrafts = reactive<Record<number, string>>({});
const topicParentDrafts = reactive<Record<number, string>>({});
const tagNameDrafts = reactive<Record<number, string>>({});
const newTopicSlug = ref("");
const newTopicName = ref("");
const newTopicParent = ref("");
const newTagName = ref("");
const errorMessage = ref("");

function errorText(error: unknown): string {
  if (error instanceof ApiError) {
    const fieldMessage = Object.values(error.fields)[0];
    return fieldMessage ? `${error.message}: ${fieldMessage}` : error.message;
  }
  return "请求失败，请稍后重试。";
}

async function loadTaxonomy(): Promise<void> {
  try {
    const [topicRows, tagRows] = await Promise.all([
      request<TopicItem[]>("/api/v1/topics"),
      request<TagItem[]>("/api/v1/tags"),
    ]);
    topics.value = topicRows;
    tags.value = tagRows;
    for (const topic of topicRows) {
      topicNameDrafts[topic.id] = topic.name;
      topicParentDrafts[topic.id] = topic.parent_id === null ? "" : String(topic.parent_id);
    }
    for (const tag of tagRows) tagNameDrafts[tag.id] = tag.name;
  } catch (error) {
    errorMessage.value = errorText(error);
  }
}

function topicDepth(topic: TopicItem): number {
  const byId = new Map(topics.value.map((item) => [item.id, item]));
  const seen = new Set<number>();
  let parentId = topic.parent_id;
  let depth = 0;
  while (parentId !== null && !seen.has(parentId)) {
    seen.add(parentId);
    const parent = byId.get(parentId);
    if (!parent) break;
    depth += 1;
    parentId = parent.parent_id;
  }
  return depth;
}

async function createTopic(): Promise<void> {
  errorMessage.value = "";
  try {
    const topic = await request<TopicItem>("/api/v1/topics", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        slug: newTopicSlug.value,
        name: newTopicName.value,
        parent_id: newTopicParent.value ? Number(newTopicParent.value) : null,
      }),
    });
    topics.value = [...topics.value, topic].sort(
      (left, right) => left.sort_order - right.sort_order || left.slug.localeCompare(right.slug),
    );
    topicNameDrafts[topic.id] = topic.name;
    topicParentDrafts[topic.id] = topic.parent_id === null ? "" : String(topic.parent_id);
    newTopicSlug.value = "";
    newTopicName.value = "";
    newTopicParent.value = "";
  } catch (error) {
    errorMessage.value = errorText(error);
  }
}

async function saveTopic(topic: TopicItem): Promise<void> {
  errorMessage.value = "";
  try {
    const updated = await request<TopicItem>(`/api/v1/topics/${topic.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: topicNameDrafts[topic.id],
        parent_id: topicParentDrafts[topic.id] ? Number(topicParentDrafts[topic.id]) : null,
      }),
    });
    topics.value = topics.value.map((item) => (item.id === updated.id ? updated : item));
    topicNameDrafts[updated.id] = updated.name;
    topicParentDrafts[updated.id] = updated.parent_id === null ? "" : String(updated.parent_id);
  } catch (error) {
    errorMessage.value = errorText(error);
  }
}

async function toggleTopic(topic: TopicItem): Promise<void> {
  errorMessage.value = "";
  try {
    const updated = await request<TopicItem>(`/api/v1/topics/${topic.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ is_active: !topic.is_active }),
    });
    topics.value = topics.value.map((item) => (item.id === updated.id ? updated : item));
  } catch (error) {
    errorMessage.value = errorText(error);
  }
}

async function createTag(): Promise<void> {
  errorMessage.value = "";
  try {
    const tag = await request<TagItem>("/api/v1/tags", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: newTagName.value }),
    });
    tags.value = [...tags.value, tag].sort((left, right) => left.name.localeCompare(right.name));
    tagNameDrafts[tag.id] = tag.name;
    newTagName.value = "";
  } catch (error) {
    errorMessage.value = errorText(error);
  }
}

async function saveTag(tag: TagItem): Promise<void> {
  errorMessage.value = "";
  try {
    const updated = await request<TagItem>(`/api/v1/tags/${tag.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: tagNameDrafts[tag.id] }),
    });
    tags.value = tags.value.map((item) => (item.id === updated.id ? updated : item));
    tagNameDrafts[updated.id] = updated.name;
  } catch (error) {
    errorMessage.value = errorText(error);
  }
}

async function toggleTag(tag: TagItem): Promise<void> {
  errorMessage.value = "";
  try {
    const updated = await request<TagItem>(`/api/v1/tags/${tag.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ is_active: !tag.is_active }),
    });
    tags.value = tags.value.map((item) => (item.id === updated.id ? updated : item));
  } catch (error) {
    errorMessage.value = errorText(error);
  }
}

onMounted(loadTaxonomy);
</script>

<template>
  <section aria-labelledby="taxonomy-title">
    <h2 id="taxonomy-title">Agent Topic 与标签</h2>
    <p v-if="errorMessage" role="alert">{{ errorMessage }}</p>

    <section aria-labelledby="topics-title">
      <h3 id="topics-title">Topic</h3>
      <form aria-label="新建 Topic 表单" @submit.prevent="createTopic">
        <label>
          Slug
          <input v-model="newTopicSlug" aria-label="新建 Topic slug" required />
        </label>
        <label>
          名称
          <input v-model="newTopicName" aria-label="新建 Topic 名称" required />
        </label>
        <label>
          父级 Topic
          <select v-model="newTopicParent" aria-label="新建 Topic 父级">
            <option value="">无</option>
            <option v-for="topic in topics" :key="topic.id" :value="String(topic.id)">
              {{ topic.name }}<template v-if="!topic.is_active">（停用）</template>
            </option>
          </select>
        </label>
        <button type="submit">添加 Topic</button>
      </form>
      <ul>
        <li
          v-for="topic in topics"
          :key="topic.id"
          :style="{ marginInlineStart: `${topicDepth(topic) * 16}px` }"
        >
          <input v-model="topicNameDrafts[topic.id]" :aria-label="`Topic 名称 ${topic.slug}`" />
          <span>{{ topic.slug }}</span>
          <span v-if="!topic.is_active">停用</span>
          <select v-model="topicParentDrafts[topic.id]" :aria-label="`Topic 父级 ${topic.slug}`">
            <option value="">无父级</option>
            <option v-for="parent in topics" :key="parent.id" :value="String(parent.id)" :disabled="parent.id === topic.id">
              {{ parent.name }}<template v-if="!parent.is_active">（停用）</template>
            </option>
          </select>
          <button type="button" :aria-label="`保存 Topic ${topic.slug}`" @click="saveTopic(topic)">保存 Topic</button>
          <button type="button" @click="toggleTopic(topic)">
            {{ topic.is_active ? "停用 Topic" : "启用 Topic" }}
          </button>
        </li>
      </ul>
    </section>

    <section aria-labelledby="tags-title">
      <h3 id="tags-title">Tag</h3>
      <form aria-label="新建标签表单" @submit.prevent="createTag">
        <label>
          标签名称
          <input v-model="newTagName" aria-label="新建标签" required />
        </label>
        <button type="submit">添加标签</button>
      </form>
      <ul>
        <li v-for="tag in tags" :key="tag.id">
          <input v-model="tagNameDrafts[tag.id]" :aria-label="`标签名称 ${tag.id}`" />
          <span>{{ tag.name }}</span>
          <span v-if="!tag.is_active">停用</span>
          <button type="button" @click="saveTag(tag)">保存标签</button>
          <button type="button" @click="toggleTag(tag)">
            {{ tag.is_active ? "停用标签" : "启用标签" }}
          </button>
        </li>
      </ul>
    </section>
  </section>
</template>
