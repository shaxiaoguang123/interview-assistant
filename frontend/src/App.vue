<script setup lang="ts">
import { onMounted, ref } from "vue";
import { RouterLink, RouterView } from "vue-router";
import { ApiError, request } from "./api/client";

const healthStatus = ref("checking");

onMounted(async () => {
  try {
    const response = await request<{ status: string }>("/api/v1/health");
    healthStatus.value = response.status;
  } catch (error) {
    healthStatus.value = error instanceof ApiError ? "unavailable" : "error";
  }
});
</script>

<template>
  <main>
    <h1>Agent Interview Assistant</h1>
    <p role="status">{{ healthStatus }}</p>
    <nav aria-label="主导航">
      <RouterLink to="/">题库</RouterLink>
      <RouterLink to="/inbox">截图收件箱</RouterLink>
      <RouterLink to="/taxonomy">分类管理</RouterLink>
      <RouterLink to="/practice">练习</RouterLink>
    </nav>
    <RouterView />
  </main>
</template>
