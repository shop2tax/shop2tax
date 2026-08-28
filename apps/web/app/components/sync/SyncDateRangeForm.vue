<script setup lang="ts">
interface SyncResult {
  importedCount: number
  skippedCount?: number
  feeCount?: number
  pdfCount?: number
  pdfErrorCount?: number
  linkedCount?: number
  errors?: string[]
}

interface SyncProgress {
  processed: number
  total: number
  imported: number
  errors: number
}

const props = defineProps<{
  title: string
  description: string
  lastSyncDate?: string | null
  startDateRequired?: boolean
  endDateRequired?: boolean
  loading?: boolean
  progress?: SyncProgress | null
  result?: SyncResult | null
  resultLink?: string
  resultLinkLabel?: string
}>()

const emit = defineEmits<{
  sync: [startDate: string | undefined, endDate: string | undefined]
}>()

const startDate = defineModel<string>('startDate')
const endDate = defineModel<string>('endDate')

const { formatDate } = useFormatters()

// Defer validation to client to avoid SSR hydration mismatch
// (server doesn't have async data yet → disabled="true", client does → not disabled)
const mounted = ref(false)
onMounted(() => {
  mounted.value = true
})

const canSync = computed(() => {
  if (!mounted.value)
    return true
  if (props.startDateRequired && !startDate.value)
    return false
  if (props.endDateRequired && !endDate.value)
    return false
  return true
})

const progressPercent = computed(() => {
  if (!props.progress || props.progress.total === 0)
    return 0
  return Math.round((props.progress.processed / props.progress.total) * 100)
})

function handleSync() {
  emit('sync', startDate.value || undefined, endDate.value || undefined)
}
</script>

<template>
  <SectionCard :title="title" :description="description">
    <template #header>
      <UBadge v-if="lastSyncDate" color="neutral" variant="soft" size="sm">
        <UIcon name="i-lucide-clock" class="mr-1 size-3" />
        Letzter Sync: {{ formatDate(lastSyncDate) }}
      </UBadge>
    </template>

    <div class="flex flex-wrap items-end gap-4">
      <UFormField :label="startDateRequired ? 'Startdatum' : 'Startdatum (optional)'">
        <UInput
          v-model="startDate"
          type="date"
          size="md"
          class="min-w-40"
          :title="startDateRequired ? undefined : 'Ab Datum synchronisieren (leer = ab letztem Sync)'"
        />
      </UFormField>

      <UFormField :label="endDateRequired ? 'Enddatum' : 'Enddatum (optional)'">
        <UInput
          v-model="endDate"
          type="date"
          size="md"
          class="min-w-40"
        />
      </UFormField>

      <div>
        <UButton
          color="primary"
          icon="i-lucide-refresh-cw"
          :loading="loading"
          :disabled="!canSync"
          @click="handleSync"
        >
          Synchronisieren
        </UButton>
      </div>
    </div>

    <!-- Progress Bar (shown during sync with streaming progress) -->
    <div v-if="loading && progress" class="mt-4">
      <div class="flex items-center justify-between mb-1.5">
        <span class="text-sm text-stone-600">
          Verarbeite {{ progress.processed }} / {{ progress.total }} Bestellungen
        </span>
        <span class="text-sm font-medium text-stone-700">{{ progressPercent }}%</span>
      </div>
      <div class="h-2 bg-stone-200 rounded-full overflow-hidden">
        <div
          class="h-full bg-blue-500 rounded-full transition-all duration-300 ease-out"
          :style="{ width: `${progressPercent}%` }"
        />
      </div>
      <p class="mt-1.5 text-xs text-stone-500">
        {{ progress.imported }} importiert<template v-if="progress.errors > 0">
          , {{ progress.errors }} Fehler
        </template>
      </p>
    </div>

    <!-- Sync Result -->
    <div v-if="result" class="mt-6">
      <UAlert
        :color="result.errors && result.errors.length > 0 ? 'warning' : 'success'"
        variant="soft"
        :title="`${result.importedCount} importiert`"
      >
        <template #description>
          <div class="space-y-1">
            <p>
              <template v-if="result.skippedCount !== undefined">
                {{ result.skippedCount }} übersprungen
              </template>
              <template v-if="result.feeCount !== undefined">
                • {{ result.feeCount }} Gebühren
              </template>
              <template v-if="result.pdfCount !== undefined">
                • {{ result.pdfCount }} PDFs
                <template v-if="result.pdfErrorCount && result.pdfErrorCount > 0">
                  ({{ result.pdfErrorCount }} fehlgeschlagen)
                </template>
              </template>
              <template v-if="result.linkedCount && result.linkedCount > 0">
                • {{ result.linkedCount }} Belege automatisch zugeordnet
              </template>
            </p>
            <p v-for="(error, index) in result.errors?.slice(0, 5)" :key="index" class="text-sm text-red-600">
              {{ error }}
            </p>
            <p v-if="result.errors && result.errors.length > 5" class="text-sm text-stone-500">
              ... und {{ result.errors.length - 5 }} weitere Fehler
            </p>
          </div>
        </template>
        <template v-if="resultLink" #actions>
          <UButton color="primary" variant="solid" :to="resultLink">
            {{ resultLinkLabel || 'Anzeigen' }}
          </UButton>
        </template>
      </UAlert>
    </div>
  </SectionCard>
</template>
