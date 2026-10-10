<script setup lang="ts">
defineProps<{name: "bank" | "inbox" | "taxonomy" | "practice" | "brand" | "progress"}>();
const paths = {
  bank: "M4 4h6v7H4zM14 4h6v7h-6zM4 15h6v5H4zM14 15h6v5h-6z",
  inbox: "M4 4h16v16H4zM4 14h5l2 3h2l2-3h5M8 8h8M8 11h5",
  taxonomy: "M12 4v6M5 14v-4h14v4M3 15h4v5H3zM10 15h4v5h-4zM17 15h4v5h-4zM10 2h4v4h-4z",
  practice: "m9 5 11 7-11 7zM4 5v14",
  progress: "M4 20h16M6 16v-4M12 16V8M18 16V4",
  brand: "M4 4h16v16H4zM8 8h8M8 12h5M8 16h3",
};
</script>
<template><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" class="workspace-icon"><path :d="paths[name]" /></svg></template>
