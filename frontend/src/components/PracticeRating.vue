<script setup lang="ts">
const props = withDefaults(defineProps<{ disabled?: boolean }>(), { disabled: false });
const emit = defineEmits<{ rate: [rating: string] }>();

const ratings = [
  { value: "dont_know", label: "不会" },
  { value: "vague", label: "模糊" },
  { value: "basic", label: "基本会" },
  { value: "proficient", label: "熟练" },
];
</script>

<template>
  <fieldset aria-label="本次掌握程度">
    <legend>本次掌握程度</legend>
    <button
      v-for="rating in ratings"
      :key="rating.value"
      type="button"
      :aria-label="`自评${rating.label}`"
      :disabled="props.disabled"
      @click="emit('rate', rating.value)"
    >
      {{ rating.label }}
    </button>
  </fieldset>
</template>
