<script setup lang="ts">
defineProps<{name: "bank" | "inbox" | "taxonomy" | "practice" | "brand" | "progress" | "projects" | "materials" | "settings"}>();
const paths = {
  bank: "M4 4h6v7H4zM14 4h6v7h-6zM4 15h6v5H4zM14 15h6v5h-6z",
  inbox: "M4 4h16v16H4zM4 14h5l2 3h2l2-3h5M8 8h8M8 11h5",
  taxonomy: "M12 4v6M5 14v-4h14v4M3 15h4v5H3zM10 15h4v5h-4zM17 15h4v5h-4zM10 2h4v4h-4z",
  practice: "m9 5 11 7-11 7zM4 5v14",
  progress: "M4 20h16M6 16v-4M12 16V8M18 16V4",
  projects: "M4 7h16v13H4zM8 7V4h8v3M4 12h16M10 12v3h4v-3",
  materials: "M5 3h10l4 4v14H5zM15 3v5h4M9 12h6M9 16h6",
  settings: "M4 7h16M4 17h16M8 4v6M16 14v6",
  brand: "M4 4h16v16H4zM8 8h8M8 12h5M8 16h3",
};
</script>
<template><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" class="workspace-icon"><path :d="paths[name]" /></svg></template>
