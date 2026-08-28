<script setup lang="ts">
defineProps<{
  saveMappingCheckbox: boolean
  isImporting: boolean
  isSavingMapping: boolean
  selectedCount: number
}>()

const emit = defineEmits<{
  'update:saveMappingCheckbox': [value: boolean]
  'back': []
  'import': []
}>()
</script>

<template>
  <div class="flex items-center justify-between">
    <UButton variant="ghost" @click="emit('back')">
      Zurück
    </UButton>
    <div class="flex items-center gap-4">
      <UCheckbox
        :model-value="saveMappingCheckbox"
        label="Zuordnung speichern"
        @update:model-value="emit('update:saveMappingCheckbox', $event as boolean)"
      />
      <UButton
        color="primary"
        :loading="isImporting || isSavingMapping"
        :disabled="selectedCount === 0"
        @click="emit('import')"
      >
        {{ selectedCount }} Zeilen importieren
      </UButton>
    </div>
  </div>
</template>
