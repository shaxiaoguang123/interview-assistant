<script setup lang="ts">
import { onMounted, ref } from "vue";
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
  </main>
</template>
