<script setup lang="ts">
definePageMeta({
  middleware: ['auth'],
})

// Tab navigation
const tabs = [
  { label: 'DATEV', value: 'datev', icon: 'i-lucide-file-spreadsheet' },
  { label: 'EÜR', value: 'euer', icon: 'i-lucide-receipt-text' },
]
const activeTab = useQueryTab(tabs.map(t => t.value), 'datev')
</script>

<template>
  <div class="flex-1 min-w-0">
    <PageHeader title="Export" />

    <div class="p-6 space-y-6">
      <TabNav v-model="activeTab" :tabs="tabs" />

      <ExportDatevExport v-if="activeTab === 'datev'" />

      <!-- EÜR Tab -->
      <div v-if="activeTab === 'euer'" class="flex flex-col items-center justify-center py-20 text-center">
        <UIcon name="i-lucide-receipt-text" class="size-12 text-stone-300 dark:text-stone-600" />
        <h3 class="mt-4 font-display text-lg font-semibold text-stone-700 dark:text-stone-300">
          EÜR-Export
        </h3>
        <p class="mt-2 max-w-md text-sm text-stone-500 dark:text-stone-400">
          Der Export der Einnahmen-Überschuss-Rechnung (EÜR) wird in einer zukünftigen Version verfügbar sein.
        </p>
      </div>
    </div>
  </div>
</template>
