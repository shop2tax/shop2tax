<script setup lang="ts">
defineProps<{
  parseError?: string | null
  parseErrors: string[]
}>()
</script>

<template>
  <div>
    <UAlert v-if="parseError" color="error" variant="soft" :title="parseError" class="mb-4" />

    <UAlert v-if="parseErrors.length > 0" color="warning" variant="soft" icon="i-lucide-alert-triangle" class="mb-4">
      <template #title>
        {{ parseErrors.length }} Zeilen mit Fehlern
      </template>
      <template #description>
        <ul class="mt-2 list-inside list-disc text-sm">
          <li v-for="(error, i) in parseErrors.slice(0, 3)" :key="i">
            {{ error }}
          </li>
          <li v-if="parseErrors.length > 3">
            ... und {{ parseErrors.length - 3 }} weitere
          </li>
        </ul>
      </template>
    </UAlert>
  </div>
</template>
