<script setup lang="ts">
import type { DatevZipValidationResult } from '~/composables/useDatev'
import type { DatevExportResponse, DatevValidationResult } from '~/types/api'

const toast = useToast()
const { preview, downloadCsv, validate } = useDatevMutations()
const { downloadZip, validateZip } = useDatevZipMutations()
const { data: history, refresh: refreshHistory } = useDatevHistory()
const { data: datevSettings } = useDatevSettings()

const dateFrom = ref('')
const dateTo = ref('')
const includeUnreconciled = ref(false)

// ZIP export options (sevdesk-like)
const includeReceipts = ref(true) // Belegbilder exportieren
const finalizedOnly = ref(false) // Nur festgeschriebene Belege
const includeRevenue = ref(true) // Einnahmebelege
const includeExpense = ref(true) // Ausgabebelege

// Preview/validation state
const previewData = ref<DatevExportResponse | null>(null)
const validationResult = ref<DatevValidationResult | null>(null)
const zipValidationResult = ref<DatevZipValidationResult | null>(null)
const isLoading = ref(false)
const isExporting = ref(false)

// Build export request from saved settings + local form state (CSV)
function buildRequest() {
  const settings = datevSettings.value
  return {
    config: {
      beraternummer: settings?.beraternummer || '',
      mandantennummer: settings?.mandantennummer || '',
      wirtschaftsjahr_beginn: settings?.wirtschaftsjahr_beginn || `${new Date().getFullYear()}-01-01`,
      sachkontenlaenge: 4,
    },
    date_from: dateFrom.value || undefined,
    date_to: dateTo.value || undefined,
    include_unreconciled: includeUnreconciled.value,
  }
}

// Build ZIP export request
function buildZipRequest() {
  const settings = datevSettings.value

  // Build document_types filter
  const documentTypes: string[] = []
  if (includeRevenue.value)
    documentTypes.push('revenue')
  if (includeExpense.value)
    documentTypes.push('expense')

  return {
    config: {
      beraternummer: settings?.beraternummer || '',
      mandantennummer: settings?.mandantennummer || '',
      wirtschaftsjahr_beginn: settings?.wirtschaftsjahr_beginn || `${new Date().getFullYear()}-01-01`,
      sachkontenlaenge: 4,
    },
    date_from: dateFrom.value || undefined,
    date_to: dateTo.value || undefined,
    include_receipts: includeReceipts.value,
    finalized_only: finalizedOnly.value,
    document_types: documentTypes.length === 2 ? null : documentTypes, // null = all
  }
}

const canExport = computed(() => {
  return datevSettings.value?.beraternummer && datevSettings.value?.mandantennummer
})

async function handlePreview() {
  isLoading.value = true
  validationResult.value = null

  try {
    previewData.value = await preview(buildRequest())
  }
  catch {
    toast.add({ title: 'Fehler beim Laden der Vorschau', color: 'error', icon: 'i-lucide-circle-x' })
  }
  finally {
    isLoading.value = false
  }
}

async function handleValidate() {
  isLoading.value = true
  zipValidationResult.value = null

  try {
    if (includeReceipts.value) {
      // Validate ZIP export
      zipValidationResult.value = await validateZip(buildZipRequest())
      validationResult.value = {
        valid: zipValidationResult.value.valid,
        errors: zipValidationResult.value.errors,
        warnings: zipValidationResult.value.warnings,
      }
    }
    else {
      // Validate CSV export
      validationResult.value = await validate(buildRequest())
    }
  }
  catch {
    toast.add({ title: 'Fehler bei der Validierung', color: 'error', icon: 'i-lucide-circle-x' })
  }
  finally {
    isLoading.value = false
  }
}

async function handleDownload() {
  isExporting.value = true

  try {
    if (includeReceipts.value) {
      // Download ZIP with Belegbilder
      const blob = await downloadZip(buildZipRequest())
      downloadBlob(blob, `DATEV_Export_${dateFrom.value || 'all'}_bis_${dateTo.value || 'all'}.zip`)

      toast.add({ title: 'DATEV-Export mit Belegbildern heruntergeladen', color: 'success', icon: 'i-lucide-download' })
    }
    else {
      // Download CSV only
      const blob = await downloadCsv(buildRequest())
      downloadBlob(blob, `DATEV_${dateFrom.value || 'all'}_${dateTo.value || 'all'}.csv`)

      toast.add({ title: 'DATEV-Export heruntergeladen', color: 'success', icon: 'i-lucide-download' })
    }
    refreshHistory()
  }
  catch {
    toast.add({ title: 'Fehler beim Export', color: 'error', icon: 'i-lucide-circle-x' })
  }
  finally {
    isExporting.value = false
  }
}

const { formatDate } = useFormatters()
</script>

<template>
  <!-- Filter toolbar -->
  <FilterToolbar>
    <UInput
      v-model="dateFrom"
      type="date"
      placeholder="Von"
      size="md"
      class="min-w-40"
    />
    <span class="text-xs text-stone-400">–</span>
    <UInput
      v-model="dateTo"
      type="date"
      placeholder="Bis"
      size="md"
      class="min-w-40"
    />

    <div class="h-5 w-px bg-stone-200 dark:bg-stone-700" />

    <UCheckbox
      v-model="includeUnreconciled"
      label="Unkontierte einbeziehen"
    />
  </FilterToolbar>

  <!-- Export Options Card (sevdesk-like) -->
  <SectionCard title="Export-Optionen">
    <div class="space-y-4">
      <!-- Belegbilder toggle -->
      <div class="flex items-center justify-between">
        <div>
          <p class="font-medium text-stone-700 dark:text-stone-300">
            Belegbilder exportieren
          </p>
          <p class="text-sm text-stone-500 dark:text-stone-400">
            Erstellt ein ZIP mit Buchungsstapel CSV und Belegen für DATEV Belegtransfer
          </p>
        </div>
        <USwitch v-model="includeReceipts" />
      </div>

      <!-- Conditional options when Belegbilder enabled -->
      <template v-if="includeReceipts">
        <div class="h-px bg-stone-200 dark:bg-stone-700" />

        <!-- Finalized only -->
        <UCheckbox
          v-model="finalizedOnly"
          label="Nur festgeschriebene Belege"
        />

        <!-- Document type filter -->
        <div class="space-y-2">
          <p class="text-sm font-medium text-stone-600 dark:text-stone-400">
            Belegtypen
          </p>
          <div class="flex gap-4">
            <UCheckbox
              v-model="includeRevenue"
              label="Einnahmebelege"
            />
            <UCheckbox
              v-model="includeExpense"
              label="Ausgabebelege"
            />
          </div>
        </div>
      </template>
    </div>
  </SectionCard>

  <!-- Missing config warning -->
  <UAlert
    v-if="!canExport"
    color="warning"
    variant="soft"
    title="DATEV-Konfiguration fehlt"
    description="Beraternummer und Mandantennummer müssen unter Einstellungen → DATEV konfiguriert werden."
  >
    <template #actions>
      <UButton color="warning" variant="soft" to="/settings?tab=datev">
        Zu den Einstellungen
      </UButton>
    </template>
  </UAlert>

  <!-- Validation Result -->
  <UAlert
    v-if="validationResult?.valid"
    color="success"
    variant="soft"
    title="Validierung erfolgreich"
    description="Die Export-Konfiguration ist gültig."
  />

  <UAlert
    v-else-if="validationResult && !validationResult.valid"
    color="error"
    variant="soft"
    title="Validierung fehlgeschlagen"
  >
    <ul class="list-disc pl-4 mt-2 space-y-1">
      <li v-for="error in validationResult.errors" :key="error">
        {{ error }}
      </li>
    </ul>
  </UAlert>

  <UAlert
    v-if="validationResult?.warnings?.length"
    color="warning"
    variant="soft"
    title="Warnungen"
  >
    <ul class="list-disc pl-4 mt-2 space-y-1">
      <li v-for="warning in validationResult.warnings" :key="warning">
        {{ warning }}
      </li>
    </ul>
  </UAlert>

  <!-- Receipts without file warning (ZIP validation only) -->
  <UAlert
    v-if="zipValidationResult?.receipts_without_file?.length"
    color="info"
    variant="soft"
    title="Belege ohne Datei"
    :description="`${zipValidationResult.receipts_without_file.length} Beleg(e) haben kein Belegbild und werden ohne Dokument exportiert.`"
  >
    <details class="mt-2">
      <summary class="text-sm cursor-pointer text-stone-600 dark:text-stone-400 hover:underline">
        Details anzeigen
      </summary>
      <ul class="list-disc pl-4 mt-2 space-y-1 text-sm">
        <li v-for="receiptNumber in zipValidationResult.receipts_without_file.slice(0, 10)" :key="receiptNumber">
          {{ receiptNumber }}
        </li>
        <li v-if="zipValidationResult.receipts_without_file.length > 10" class="text-stone-500">
          ... und {{ zipValidationResult.receipts_without_file.length - 10 }} weitere
        </li>
      </ul>
    </details>
  </UAlert>

  <!-- Preview -->
  <SectionCard v-if="previewData" title="Vorschau">
    <template #header>
      <span class="text-sm text-stone-500">
        {{ previewData.transaction_count }} Buchungen •
        {{ previewData.line_item_count }} Positionen
      </span>
    </template>

    <div class="overflow-x-auto">
      <table class="w-full text-sm">
        <thead>
          <tr class="border-b border-default">
            <th v-for="header in previewData.column_headers.slice(0, 8)" :key="header" class="px-2 py-1 text-left font-medium">
              {{ header }}
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(row, i) in previewData.rows.slice(0, 10)" :key="i" class="border-b border-default">
            <td v-for="(cell, j) in row.slice(0, 8)" :key="j" class="px-2 py-1">
              {{ cell }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <p v-if="previewData.rows.length > 10" class="text-sm text-stone-500 mt-2">
      ... und {{ previewData.rows.length - 10 }} weitere Zeilen
    </p>
  </SectionCard>

  <!-- Export History -->
  <SectionCard title="Export-Verlauf">
    <UTable
      :data="history?.items || []"
      :columns="[
        { accessorKey: 'created_at', header: 'Datum' },
        { accessorKey: 'export_format', header: 'Format' },
        { accessorKey: 'transaction_count', header: 'Buchungen' },
        { accessorKey: 'line_item_count', header: 'Positionen' },
        { accessorKey: 'date_from', header: 'Zeitraum' },
        { accessorKey: 'beraternummer', header: 'Berater' },
      ]"
      :empty-state="{ icon: 'i-lucide-file-x', label: 'Noch keine Exporte' }"
    >
      <template #created_at-cell="{ row }">
        {{ formatDate(row.original.created_at) }}
      </template>

      <template #export_format-cell="{ row }">
        <UBadge
          :color="row.original.export_format === 'zip' ? 'primary' : 'neutral'"
          variant="soft"
          size="sm"
        >
          {{ row.original.export_format === 'zip' ? 'ZIP' : 'CSV' }}
        </UBadge>
      </template>

      <template #date_from-cell="{ row }">
        <template v-if="row.original.date_from && row.original.date_to">
          {{ formatDate(row.original.date_from) }} - {{ formatDate(row.original.date_to) }}
        </template>
        <span v-else class="text-stone-400">Alle</span>
      </template>
    </UTable>

    <template #footer>
      <div class="flex items-center justify-end gap-2">
        <UButton
          variant="outline"
          color="neutral"
          :loading="isLoading"
          @click="handlePreview"
        >
          Vorschau
        </UButton>
        <UButton
          variant="outline"
          color="neutral"
          :loading="isLoading"
          @click="handleValidate"
        >
          Validieren
        </UButton>
        <UButton
          color="primary"
          :icon="includeReceipts ? 'i-lucide-archive' : 'i-lucide-download'"
          :loading="isExporting"
          :disabled="!canExport"
          :title="!canExport ? 'Beraternummer und Mandantennummer in Einstellungen → DATEV konfigurieren' : undefined"
          @click="handleDownload"
        >
          {{ includeReceipts ? 'ZIP herunterladen' : 'CSV herunterladen' }}
        </UButton>
      </div>
    </template>
  </SectionCard>
</template>
