<script setup lang="ts">
defineProps<{
  file: File | null
  analyzeError?: string | null
  /** Extra error to show (e.g. uploadError for marketplace) */
  extraError?: string | null
}>()

const emit = defineEmits<{
  drop: [event: DragEvent]
  click: []
}>()
</script>

<template>
  <div class="space-y-6">
    <!-- Slot for source selection (different per wizard) -->
    <slot name="source" />

    <!-- File Upload -->
    <div
      class="border-2 border-dashed border-stone-300 dark:border-stone-700 rounded-xl p-8 text-center cursor-pointer hover:border-primary-400 dark:hover:border-primary-600 transition-colors"
      :class="file ? 'bg-primary-50/50 dark:bg-primary-900/20 border-primary-400 dark:border-primary-600' : 'bg-stone-50/50 dark:bg-stone-900/50'"
      @dragover.prevent
      @drop="emit('drop', $event)"
      @click="emit('click')"
    >
      <template v-if="file">
        <UIcon name="i-lucide-file-check" class="mx-auto mb-2 size-10 text-primary-500" />
        <p class="font-medium text-stone-900 dark:text-stone-100">
          {{ file.name }}
        </p>
        <p class="mt-1 text-sm text-stone-500">
          {{ (file.size / 1024).toFixed(1) }} KB
        </p>
      </template>
      <template v-else>
        <UIcon name="i-lucide-upload-cloud" class="mx-auto mb-2 size-10 text-stone-400" />
        <p class="font-medium text-stone-900 dark:text-stone-100">
          CSV-Datei hierher ziehen
        </p>
        <p class="mt-1 text-sm text-stone-500">
          oder klicken zum Auswählen
        </p>
        <!-- Extra content below upload text (e.g. marketplace badges) -->
        <slot name="upload-hint" />
      </template>
    </div>

    <!-- Errors -->
    <UAlert v-if="extraError" color="error" variant="soft" :title="extraError" />
    <UAlert v-if="analyzeError" color="error" variant="soft" :title="analyzeError" />

    <!-- Extra alerts (e.g. marketplace "no sources" warning) -->
    <slot name="alerts" />
  </div>
</template>
