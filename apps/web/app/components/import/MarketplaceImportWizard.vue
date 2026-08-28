<script setup lang="ts">
import type {
  EnrichedRowResponse,
  GenericCsvMappingRequest,
  MarketplaceParsedRowResponse,
  ParsedRowResponse,
} from '~/types/api'

const wizard = useImportWizardBase({
  sourceType: 'marketplace_mapping',
  requiredColumns: ['reference'],
})
const {
  // Step
  currentStep,
  steps,
  // Sources
  sources,
  selectedSourceId,
  selectedSource,
  // File
  file,
  handleFileChange,
  handleDrop,
  // Analysis
  analyze,
  analyzeResult,
  isAnalyzing,
  analyzeError,
  applyAnalyzeResult,
  loadMappingOrSuggest,
  // Mapping
  delimiter,
  encoding,
  skipRows,
  dateFormat,
  amountFormat,
  columnDate,
  columnAmount,
  columnReference,
  isMappingComplete,
  baseMapping,
  columnOptions,
  dateFormatOptions,
  // Preview
  parse,
  previewRows,
  parseErrors,
  filteredCount,
  isParsing,
  parseError,
  selectedRows,
  saveMappingCheckbox,
  isSavingMapping,
  toggleRow,
  toggleAll,
  // Import
  isImporting,
  importResult,
  reset: resetBase,
} = wizard

const toast = useToast()
const fileInputRef = useTemplateRef<HTMLInputElement>('fileInput')

// --- Marketplace-specific: File Upload (file_id based) ---
const { uploadFile, isUploading, uploadError, fileId, reset: resetFileUpload } = useCsvFileUpload()

// --- Parser detection ---
const parserFallbackToMapping = ref(false)
const isParserSource = computed(() =>
  selectedSource.value?.source_config?.parser != null && !parserFallbackToMapping.value,
)

// --- Marketplace Parser flow ---
const {
  parseMarketplaceCsv,
  isParsing: isMarketplaceParsing,
  parseError: marketplaceParseError,
  parseResult: marketplaceParseResult,
  groupByType,
  reset: resetMarketplace,
} = useMarketplaceParsing()

const marketplaceRows = computed<MarketplaceParsedRowResponse[]>(
  () => marketplaceParseResult.value?.rows ?? [],
)

// Display metadata for marketplace transaction types (Etsy + Shopify)
const typeLabels: Record<string, { label: string, icon: string, category: 'revenue' | 'fee' | 'marketing' | 'other' }> = {
  // Etsy types
  sale: { label: 'Verkäufe', icon: 'i-lucide-shopping-bag', category: 'revenue' },
  refund: { label: 'Erstattungen', icon: 'i-lucide-undo-2', category: 'revenue' },
  sales_tax: { label: 'Umsatzsteuer', icon: 'i-lucide-landmark', category: 'other' },
  fee_transaction_item: { label: 'Transaktionsgebühr', icon: 'i-lucide-receipt', category: 'fee' },
  fee_transaction_shipping: { label: 'Versandgebühr', icon: 'i-lucide-truck', category: 'fee' },
  fee_processing: { label: 'Zahlungsgebühr', icon: 'i-lucide-credit-card', category: 'fee' },
  fee_listing: { label: 'Listinggebühr', icon: 'i-lucide-tag', category: 'fee' },
  credit_transaction: { label: 'Gutschrift Transaktion', icon: 'i-lucide-arrow-down-left', category: 'fee' },
  credit_processing: { label: 'Gutschrift Zahlung', icon: 'i-lucide-arrow-down-left', category: 'fee' },
  credit_listing: { label: 'Gutschrift Listing', icon: 'i-lucide-arrow-down-left', category: 'fee' },
  marketing_ads: { label: 'Marketplace Ads', icon: 'i-lucide-megaphone', category: 'marketing' },
  marketing_offsite: { label: 'Offsite Ads', icon: 'i-lucide-globe', category: 'marketing' },
  payout: { label: 'Auszahlung', icon: 'i-lucide-banknote', category: 'other' },
  // Shopify types
  charge: { label: 'Verkäufe', icon: 'i-lucide-shopping-bag', category: 'revenue' },
  fee: { label: 'Gebühren', icon: 'i-lucide-receipt', category: 'fee' },
  chargeback: { label: 'Rückbuchungen', icon: 'i-lucide-alert-triangle', category: 'revenue' },
  adjustment: { label: 'Anpassungen', icon: 'i-lucide-settings', category: 'other' },
  reserve: { label: 'Rücklage', icon: 'i-lucide-lock', category: 'other' },
  // Amazon types
  order: { label: 'Verkäufe', icon: 'i-lucide-shopping-bag', category: 'revenue' },
  transfer: { label: 'Auszahlung', icon: 'i-lucide-banknote', category: 'other' },
}

function typeLabel(type: string): string {
  return typeLabels[type]?.label ?? type
}

function typeIcon(type: string): string {
  return typeLabels[type]?.icon ?? 'i-lucide-circle'
}

// Category order for sorting
const categoryOrder = { revenue: 0, fee: 1, marketing: 2, other: 3 }

// Type summary for parser preview (grouped by etsy_type)
const typeSummary = computed(() => {
  if (marketplaceRows.value.length === 0)
    return []
  const groups = groupByType(marketplaceRows.value)
  return Array.from(groups.entries())
    .map(([type, stats]) => ({ type, ...stats }))
    .sort((a, b) => {
      const catA = categoryOrder[typeLabels[a.type]?.category ?? 'other']
      const catB = categoryOrder[typeLabels[b.type]?.category ?? 'other']
      if (catA !== catB)
        return catA - catB
      return Math.abs(b.total) - Math.abs(a.total)
    })
})

// RC USt: computed server-side in MarketplaceCsvParseResponse.rc_ust_amount
const rcUstAmount = computed(() => {
  const value = marketplaceParseResult.value?.rc_ust_amount
  return value ? Number.parseFloat(value) : 0
})

// Map marketplace rows to ParsedRowResponse for the shared PreviewTable
const parserDisplayRows = computed<ParsedRowResponse[]>(() =>
  marketplaceRows.value.map(row => ({
    date: row.date,
    amount: row.amount,
    counterparty: row.counterparty,
    description: row.description,
    source_reference: row.source_reference,
    oms_order_id: row.oms_order_id,
  })),
)

// --- Marketplace-specific: OMS Stores ---
const { data: omsSettings } = useOmsSettings()
const { primaryProvider } = useOmsProviders()

const omsProviderName = computed(() => primaryProvider.value?.display_name ?? 'Warenwirtschaft')

const linkedOmsStore = computed(() => {
  if (!selectedSourceId.value || !omsSettings.value?.stores)
    return null
  return omsSettings.value.stores.find(
    store => store.source_config_id === selectedSourceId.value,
  ) ?? null
})

// --- Post-import: Fee transaction linking ---
const feeTransactionIds = ref<Set<string>>(new Set())
const feeTransactionTotal = ref(0)
const showBulkLinkModal = ref(false)
const isLoadingFeeTransactions = ref(false)

async function loadFeeTransactions() {
  if (!selectedSourceId.value)
    return
  isLoadingFeeTransactions.value = true

  // Fetch fee+marketing transactions via standardized marketplace_category filter.
  // Works for any marketplace parser that sets extra_data.marketplace_category.
  const response = await $fetch<{ items: Array<{ id: string, amount: string }>, total: number }>('/api/v1/transactions', {
    params: {
      source_config_id: selectedSourceId.value,
      marketplace_category: 'fee,marketing',
      limit: 500,
    },
  })

  feeTransactionIds.value = new Set(response.items.map(t => t.id))
  feeTransactionTotal.value = response.items.reduce((sum, t) => sum + Math.abs(Number(t.amount)), 0)
  isLoadingFeeTransactions.value = false
  showBulkLinkModal.value = true
}

// --- Marketplace-specific: Filter Column (mapping flow only) ---
const columnFilter = ref<string | undefined>(undefined)
const availableFilterValues = ref<string[]>([])
const selectedFilterValues = ref<string[]>([])

watch(columnFilter, (filterColumn) => {
  if (!filterColumn || !analyzeResult.value) {
    availableFilterValues.value = []
    selectedFilterValues.value = []
    return
  }

  // Use unique_values (all rows) if available, fall back to sample_values (first 5)
  const uniqueMap = analyzeResult.value.unique_values || {}
  const sampleMap = analyzeResult.value.sample_values || {}
  const values = uniqueMap[filterColumn] || sampleMap[filterColumn] || []
  const unique = [...new Set(values.filter(v => v.trim()))]
  availableFilterValues.value = unique
  selectedFilterValues.value = [] // Don't pre-select — user picks what to include
})

// --- Marketplace-specific: Enrichment (mapping flow only) ---
const { enrichRows, isEnriching, enrichError, enrichedRows, matchedCount, unmatchedCount, reset: resetEnrichment } = useMarketplaceEnrichment()

// Extended mapping (base + filter fields)
const currentMapping = computed<GenericCsvMappingRequest | null>(() => {
  if (!baseMapping.value)
    return null

  return {
    ...baseMapping.value,
    column_filter: columnFilter.value,
    filter_include_values: columnFilter.value && selectedFilterValues.value.length > 0
      ? selectedFilterValues.value
      : undefined,
  }
})

// Display rows for mapping flow: merge enriched OMS data into standard fields
const mappingDisplayRows = computed<ParsedRowResponse[]>(() => {
  if (enrichedRows.value.length > 0) {
    return enrichedRows.value.map((row) => {
      const enriched = row as EnrichedRowResponse
      return {
        date: enriched.enriched_date || row.date,
        amount: enriched.enriched_amount ?? row.amount,
        counterparty: enriched.enriched_counterparty || row.counterparty || '',
        description: enriched.enriched_description || (enriched.match_status === 'matched' ? '-' : row.description || ''),
        source_reference: row.source_reference || undefined,
      } as ParsedRowResponse
    })
  }
  return previewRows.value
})

const hasEnrichment = computed(() => enrichedRows.value.length > 0)

// --- Live Preview: auto-parse when mapping or filter changes (mapping flow only) ---
let parseDebounceTimer: ReturnType<typeof setTimeout> | null = null

function triggerPreview() {
  if (parseDebounceTimer)
    clearTimeout(parseDebounceTimer)

  const mapping = currentMapping.value
  if (!mapping || !fileId.value) {
    previewRows.value = []
    selectedRows.value = new Set()
    parseErrors.value = []
    filteredCount.value = 0
    resetEnrichment()
    return
  }

  // Reset enrichment when mapping changes — user must re-trigger
  resetEnrichment()

  parseDebounceTimer = setTimeout(async () => {
    const result = await parse(fileId.value!, mapping)
    if (!result)
      return

    previewRows.value = result.rows
    parseErrors.value = result.errors
    filteredCount.value = result.filtered_count ?? 0
    selectedRows.value = new Set(result.rows.map((_, i) => i))
  }, 300)
}

// Watch all reactive sources that affect the preview — explicit deps instead of deep-watching a computed
watch([baseMapping, columnFilter, selectedFilterValues], triggerPreview, { deep: true })

// --- Manual Enrichment trigger (mapping flow only) ---
async function startEnrichment() {
  if (!fileId.value || !currentMapping.value || !linkedOmsStore.value)
    return

  await enrichRows(fileId.value, currentMapping.value, linkedOmsStore.value.id)
  // Update selection to enriched rows
  if (enrichedRows.value.length > 0) {
    selectedRows.value = new Set(mappingDisplayRows.value.map((_, i) => i))
  }
}

// --- Step Navigation ---
async function goToStep2() {
  if (!file.value || !selectedSourceId.value)
    return

  // Upload file → get file_id
  const uploadResult = await uploadFile(file.value)
  if (!uploadResult)
    return

  if (isParserSource.value) {
    // Parser flow: upload → parse-marketplace → preview (skip analyze + mapping)
    const result = await parseMarketplaceCsv(
      uploadResult.file_id!,
      selectedSourceId.value,
      linkedOmsStore.value?.id,
    )
    if (result) {
      selectedRows.value = new Set(result.rows.map((_, i) => i))
      currentStep.value = 2
      return
    }

    // Parser not available for this source → fall back to generic mapping flow
    parserFallbackToMapping.value = true
    resetMarketplace()
  }

  // Mapping flow: analyze → column mapping → live preview
  const analyzeData = await analyze(uploadResult.file_id!)
  if (!analyzeData)
    return

  applyAnalyzeResult(analyzeData)

  const savedMapping = await loadMappingOrSuggest(selectedSourceId.value, analyzeData)
  if (savedMapping) {
    columnFilter.value = savedMapping.column_filter ?? undefined
    if (savedMapping.filter_include_values)
      selectedFilterValues.value = savedMapping.filter_include_values
  }

  currentStep.value = 2
}

// --- Import ---
const { bulkImport } = useTransactionMutations()

async function handleImport() {
  if (!selectedSourceId.value || selectedRows.value.size === 0)
    return

  if (isParserSource.value) {
    // Parser import: pass marketplace fields through (import_hash, is_internal_transfer, extra_data)
    isImporting.value = true
    try {
      const items = marketplaceRows.value
        .filter((_, i) => selectedRows.value.has(i))
        .filter(row => row.date && row.amount != null)
        .map(row => ({
          date: row.date,
          amount: row.amount,
          counterparty: row.counterparty || '',
          description: row.description || '',
          source_reference: row.source_reference ?? undefined,
          import_hash: row.import_hash ?? undefined,
          is_internal_transfer: row.is_internal_transfer,
          extra_data: row.extra_data ?? undefined,
          oms_order_id: row.oms_order_id ?? undefined,
        }))

      const result = await bulkImport({
        source_config_id: selectedSourceId.value,
        items,
        skip_duplicates: true,
      })

      importResult.value = {
        imported: result.imported_count,
        skipped: result.skipped_count,
        errors: result.error_count,
        linked: result.linked_count,
        noReceipt: result.no_receipt_count,
        skippedLocked: result.skipped_locked_count,
      }

      const skippedText = result.skipped_count > 0 ? ` · ${result.skipped_count} Duplikate übersprungen` : ''
      const linkedText = result.linked_count > 0 ? ` · ${result.linked_count} Belege automatisch zugeordnet` : ''
      toast.add({ title: `${result.imported_count} Buchungen importiert${skippedText}${linkedText}`, color: 'success', icon: 'i-lucide-check' })
    }
    catch {
      toast.add({ title: 'Fehler beim Import', color: 'error', icon: 'i-lucide-circle-x' })
    }
    finally {
      isImporting.value = false
    }
  }
  else {
    // Mapping import: existing behavior with enrichment
    await wizard.executeImport(mappingDisplayRows.value, {
      column_filter: columnFilter.value,
      filter_include_values: columnFilter.value && selectedFilterValues.value.length > 0
        ? selectedFilterValues.value
        : undefined,
    })
  }
}

function resetWizard() {
  resetBase()
  columnFilter.value = undefined
  availableFilterValues.value = []
  selectedFilterValues.value = []
  parserFallbackToMapping.value = false
  feeTransactionIds.value = new Set()
  feeTransactionTotal.value = 0
  showBulkLinkModal.value = false
  resetFileUpload()
  resetEnrichment()
  resetMarketplace()
}

const { formatCurrency } = useFormatters()
</script>

<template>
  <div class="space-y-6">
    <input
      ref="fileInput"
      type="file"
      accept=".csv,.txt,.tsv"
      class="hidden"
      @change="handleFileChange"
    >

    <ImportStepIndicator :steps="steps" :current-step="currentStep" />

    <!-- Import Result (parser flow: detailed summary) -->
    <div v-if="importResult && isParserSource" class="space-y-4">
      <UAlert
        color="success"
        variant="soft"
        icon="i-lucide-check"
        :title="`${importResult.imported} Buchungen importiert`"
        :description="[
          importResult.skipped > 0 ? `${importResult.skipped} Duplikate übersprungen` : '',
          (importResult.linked ?? 0) > 0 ? `${importResult.linked} Belege automatisch zugeordnet` : '',
          (importResult.noReceipt ?? 0) > 0 ? `${importResult.noReceipt} ohne passenden Beleg` : '',
          (importResult.skippedLocked ?? 0) > 0 ? `${importResult.skippedLocked} gesperrte Belege übersprungen` : '',
          importResult.errors > 0 ? `${importResult.errors} Fehler` : '',
        ].filter(Boolean).join(' · ') || undefined"
      />

      <!-- Type breakdown -->
      <div v-if="typeSummary.length > 0" class="rounded-lg border border-stone-200 p-4 dark:border-stone-800">
        <h4 class="mb-3 text-sm font-medium text-stone-600 dark:text-stone-400">
          Zusammenfassung nach Typ
        </h4>
        <div class="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
          <div
            v-for="group in typeSummary"
            :key="group.type"
            class="rounded-md bg-stone-50 px-3 py-2 dark:bg-stone-900"
          >
            <p class="flex items-center gap-1.5 text-xs text-stone-500">
              <UIcon :name="typeIcon(group.type)" class="size-3.5" />
              {{ typeLabel(group.type) }}
            </p>
            <p class="font-tabular text-sm font-medium" :class="group.total >= 0 ? 'text-emerald-600' : 'text-red-500'">
              {{ formatCurrency(group.total) }}
            </p>
            <p class="text-xs text-stone-400">
              {{ group.count }} Buchungen
            </p>
          </div>
        </div>

        <!-- RC USt hint for fees -->
        <p v-if="rcUstAmount > 0" class="mt-3 text-sm text-amber-600 dark:text-amber-400">
          Reverse-Charge-USt auf Gebühren: {{ formatCurrency(rcUstAmount) }}
          (fällig in der UStVA)
        </p>
      </div>

      <div class="flex items-center gap-2">
        <UButton variant="outline" color="neutral" @click="resetWizard">
          Weitere importieren
        </UButton>
        <UButton color="primary" :to="`/transactions?source_config_id=${selectedSourceId}`">
          Zu Buchungen
        </UButton>
        <UButton variant="outline" color="primary" to="/receipts/new" icon="i-lucide-file-plus">
          Neuen Beleg hochladen
        </UButton>
        <UButton
          variant="outline"
          color="neutral"
          icon="i-lucide-link"
          :loading="isLoadingFeeTransactions"
          @click="loadFeeTransactions"
        >
          Gebühren mit Beleg verknüpfen
        </UButton>
      </div>

      <!-- Bulk Link Modal for fee transactions -->
      <TransactionsBulkLinkModal
        v-if="feeTransactionIds.size > 0"
        :open="showBulkLinkModal"
        :selected-ids="feeTransactionIds"
        :selected-total="feeTransactionTotal"
        @update:open="showBulkLinkModal = $event"
        @linked="(receiptId: string) => navigateTo(`/receipts/${receiptId}`)"
      />
    </div>

    <!-- Import Result (mapping flow: simple) -->
    <UAlert
      v-if="importResult && !isParserSource"
      color="success"
      variant="soft"
      icon="i-lucide-check"
      :title="`${importResult.imported} Buchungen importiert`"
      :description="[
        importResult.skipped > 0 ? `${importResult.skipped} Duplikate übersprungen` : '',
        importResult.errors > 0 ? `${importResult.errors} Fehler` : '',
      ].filter(Boolean).join(' · ') || undefined"
    >
      <template #actions>
        <UButton variant="outline" color="neutral" @click="resetWizard">
          Weitere importieren
        </UButton>
        <UButton color="primary" to="/transactions">
          Zu Buchungen
        </UButton>
      </template>
    </UAlert>

    <!-- Step 1: Upload + Source Selection -->
    <SectionCard v-if="currentStep === 1 && !importResult" title="Schritt 1: Datei hochladen">
      <ImportFileUpload
        :file="file"
        :analyze-error="analyzeError || marketplaceParseError"
        :extra-error="uploadError"

        @drop="handleDrop"
        @click="fileInputRef?.click()"
      >
        <template #source>
          <UFormField label="Marktplatz-Quelle" required>
            <USelect
              v-model="selectedSourceId"
              :items="sources.map(s => ({ value: s.id, label: s.name }))"
              placeholder="Quelle auswählen..."
            />
          </UFormField>
          <UBadge v-if="selectedSource" color="neutral" variant="soft" size="sm" class="mt-1">
            {{ selectedSource.import_method }}
          </UBadge>
        </template>

        <template #alerts>
          <UAlert
            v-if="sources.length === 0"
            color="warning"
            variant="soft"
            icon="i-lucide-alert-triangle"
            title="Keine Marktplatz-Quellen vorhanden"
          >
            <template #description>
              Erstelle zuerst eine Marktplatz-Quelle unter
              <NuxtLink to="/settings?tab=sources" class="font-medium underline">
                Bank-Quellen
              </NuxtLink>.
            </template>
          </UAlert>
        </template>

        <template #upload-hint>
          <div class="mt-5 flex flex-wrap justify-center gap-2">
            <UBadge v-for="source in ['Etsy', 'Amazon', 'Shopify', 'Stripe']" :key="source" color="neutral" variant="soft" size="sm">
              {{ source }}
            </UBadge>
          </div>
        </template>
      </ImportFileUpload>

      <template #footer>
        <div class="flex justify-end">
          <UButton
            color="primary"
            :disabled="!file || !selectedSourceId"
            :loading="isUploading || isAnalyzing || isMarketplaceParsing"
            @click="goToStep2"
          >
            Weiter
          </UButton>
        </div>
      </template>
    </SectionCard>

    <!-- Step 2: Parser Preview (no mapping needed) -->
    <SectionCard
      v-if="currentStep === 2 && isParserSource && marketplaceRows.length > 0 && !importResult"
      title="Transaktionen prüfen"
    >
      <template #header>
        <div class="flex items-center gap-3">
          <UBadge v-if="selectedSource" color="primary" variant="soft" size="sm">
            {{ selectedSource.source_config?.parser?.toUpperCase() }}-Parser
          </UBadge>
          <UBadge color="neutral" variant="soft" size="sm">
            {{ marketplaceRows.length }} Zeilen
          </UBadge>
          <UBadge v-if="marketplaceParseResult?.enrichment?.matched" color="success" variant="soft" size="sm">
            {{ marketplaceParseResult.enrichment.matched }} {{ omsProviderName }}-Matches
          </UBadge>
        </div>
      </template>

      <!-- Type Summary -->
      <div v-if="typeSummary.length > 0" class="mb-4 flex flex-wrap gap-2">
        <div
          v-for="group in typeSummary"
          :key="group.type"
          class="flex items-center gap-1.5 rounded-md border border-stone-200 px-2.5 py-1.5 text-sm dark:border-stone-800"
        >
          <UIcon :name="typeIcon(group.type)" class="size-3.5 text-stone-400" />
          <span class="text-stone-500">{{ typeLabel(group.type) }}</span>
          <UBadge color="neutral" variant="soft" size="sm">
            {{ group.count }}×
          </UBadge>
          <span
            class="font-tabular"
            :class="group.total >= 0 ? 'text-emerald-600' : 'text-red-500'"
          >
            {{ formatCurrency(group.total) }}
          </span>
        </div>
      </div>

      <!-- Parse Errors -->
      <ImportParseErrors :parse-error="marketplaceParseError" :parse-errors="marketplaceParseResult?.errors ?? []" />

      <!-- Preview Table (reuses shared component) -->
      <ImportPreviewTable
        :rows="parserDisplayRows"
        :selected-rows="selectedRows"
        :is-mapping-complete="true"
        @toggle-row="toggleRow"
        @toggle-all="toggleAll"
      />

      <!-- RC USt hint for fees (shown before import) -->
      <UAlert
        v-if="rcUstAmount > 0"
        color="warning"
        variant="soft"
        icon="i-lucide-receipt-euro"
        class="mt-4"
        :title="`Reverse-Charge-USt: ${formatCurrency(rcUstAmount)}`"
        description="Diese USt auf Marktplatz-Gebühren wird nach Import in der UStVA fällig."
      />

      <template #footer>
        <div class="flex items-center justify-between">
          <UButton variant="ghost" @click="currentStep = 1; resetMarketplace()">
            Zurück
          </UButton>
          <UButton
            color="primary"
            :loading="isImporting"
            :disabled="selectedRows.size === 0"
            @click="handleImport"
          >
            {{ selectedRows.size }} Zeilen importieren
          </UButton>
        </div>
      </template>
    </SectionCard>

    <!-- Step 2: Column Mapping + Filter + Live Preview (mapping flow only) -->
    <SectionCard v-show="currentStep === 2 && !isParserSource && analyzeResult && !importResult" title="Transaktionen prüfen">
      <template #header>
        <div class="flex items-center gap-3">
          <UBadge v-if="selectedSource" color="neutral" variant="soft" size="sm">
            {{ selectedSource.name }}
          </UBadge>
          <UIcon v-if="isParsing || isEnriching" name="i-lucide-loader-2" class="size-4 animate-spin text-stone-400" />
          <UBadge v-if="mappingDisplayRows.length > 0" color="neutral" variant="soft" size="sm">
            {{ mappingDisplayRows.length }} Zeilen
          </UBadge>
          <UBadge v-if="filteredCount > 0" color="warning" variant="soft" size="sm">
            {{ filteredCount }} gefiltert
          </UBadge>
        </div>
      </template>

      <!-- Import Options -->
      <div class="mb-4 grid grid-cols-5 gap-2">
        <UFormField label="Trennzeichen">
          <USelect
            v-model="delimiter"
            :items="CSV_DELIMITER_OPTIONS"
          />
        </UFormField>
        <UFormField label="Encoding">
          <USelect
            v-model="encoding"
            :items="CSV_ENCODING_OPTIONS"
          />
        </UFormField>
        <UFormField label="Zeilen überspringen">
          <UInput v-model.number="skipRows" type="number" :min="0" />
        </UFormField>
        <UFormField v-if="columnAmount" label="Zahlenformat">
          <USelect
            v-model="amountFormat"
            :items="[
              { value: 'german', label: 'Deutsch (1.234,56)' },
              { value: 'english', label: 'Englisch (1,234.56)' },
            ]"
          />
        </UFormField>
        <UFormField v-if="columnDate" label="Datumsformat">
          <USelect v-model="dateFormat" :items="dateFormatOptions" placeholder="Format..." />
        </UFormField>
      </div>

      <!-- Date Ambiguity Warning -->
      <UAlert
        v-if="analyzeResult?.date_ambiguous"
        color="warning"
        variant="soft"
        icon="i-lucide-alert-triangle"
        title="Datumsformat mehrdeutig"
        description="Die Daten könnten sowohl als DD/MM als auch als MM/DD interpretiert werden. Bitte wähle das korrekte Format."
        class="mb-4"
      />

      <!-- Column Mapping Row: Referenz (Pflicht) + Filter (Spalte + Wert) + optional Datum/Betrag -->
      <div class="mb-4 grid grid-cols-5 gap-2">
        <UFormField label="Referenz (Order-ID)" required>
          <USelect v-model="columnReference" :items="columnOptions" placeholder="Spalte..." />
        </UFormField>
        <UFormField label="Filter (Spalte)">
          <USelect v-model="columnFilter" :items="columnOptions" placeholder="Keine" />
        </UFormField>
        <UFormField v-if="columnFilter && availableFilterValues.length > 0" label="Filter (Wert)">
          <USelect
            v-model="selectedFilterValues"
            multiple
            :items="availableFilterValues.map(v => ({ value: v, label: v }))"
            placeholder="Wert wählen..."
          />
        </UFormField>
        <UFormField label="Datum (Abgleich)">
          <USelect v-model="columnDate" :items="columnOptions" placeholder="Keine" />
        </UFormField>
        <UFormField label="Betrag (Abgleich)">
          <USelect v-model="columnAmount" :items="columnOptions" placeholder="Keine" />
        </UFormField>
      </div>

      <!-- Enrichment: Button + Status (mapping flow only) -->
      <div v-if="linkedOmsStore && previewRows.length > 0 && !hasEnrichment" class="mb-4 flex items-center gap-3 rounded-lg border border-stone-200 bg-stone-50 p-4 dark:border-stone-800 dark:bg-stone-900">
        <UButton
          color="primary"
          icon="i-lucide-sparkles"
          :loading="isEnriching"
          :disabled="isEnriching"
          @click="startEnrichment"
        >
          {{ isEnriching ? `${omsProviderName}-Daten werden geladen...` : `${omsProviderName}-Daten abrufen` }}
        </UButton>
        <span class="text-sm text-stone-500">
          {{ previewRows.length }} Zeilen mit {{ omsProviderName }}-Bestelldaten anreichern
        </span>
      </div>

      <!-- Enrichment Loading -->
      <UAlert
        v-if="isEnriching"
        color="info"
        variant="soft"
        icon="i-lucide-loader-2"
        :title="`${omsProviderName}-Daten werden abgerufen...`"
        :description="`Bestellungen werden von der ${omsProviderName}-API geladen und zugeordnet. Das kann beim ersten Mal etwas dauern.`"
        class="mb-4"
      />

      <!-- Enrichment Stats (after completion) -->
      <UAlert
        v-if="hasEnrichment"
        :color="unmatchedCount > 0 ? 'warning' : 'success'"
        variant="soft"
        :icon="unmatchedCount > 0 ? 'i-lucide-alert-triangle' : 'i-lucide-sparkles'"
        class="mb-4"
      >
        <template #title>
          {{ omsProviderName }}-Enrichment: {{ matchedCount }} zugeordnet, {{ unmatchedCount }} ohne Match
        </template>
      </UAlert>

      <!-- Enrichment / Parse Errors -->
      <UAlert v-if="enrichError" color="error" variant="soft" :title="enrichError" class="mb-4" />

      <ImportParseErrors :parse-error="parseError" :parse-errors="parseErrors" />

      <ImportPreviewTable
        :rows="mappingDisplayRows"
        :selected-rows="selectedRows"
        :is-mapping-complete="isMappingComplete"
        @toggle-row="toggleRow"
        @toggle-all="toggleAll"
      />

      <template #footer>
        <ImportWizardFooter
          :save-mapping-checkbox="saveMappingCheckbox"
          :is-importing="isImporting"
          :is-saving-mapping="isSavingMapping"
          :selected-count="selectedRows.size"
          @update:save-mapping-checkbox="saveMappingCheckbox = $event"
          @back="currentStep = 1"
          @import="handleImport"
        />
      </template>
    </SectionCard>

    <!-- 📥 CSV Export Help Links -->
    <SectionCard v-if="!importResult" title="CSV-Dateien herunterladen" description="Anleitungen zum Export der CSV-Dateien aus deinem Marktplatz-Konto.">
      <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <UButton
          variant="outline"
          color="neutral"
          icon="i-lucide-shopping-bag"
          to="https://sellercentral.amazon.de/reportcentral/VAT_TRANSACTION/1"
          target="_blank"
          trailing-icon="i-lucide-external-link"
          block
          size="lg"
          class="justify-start px-4 py-3"
        >
          Amazon – USt-Transaktionsbericht
        </UButton>
        <UButton
          variant="outline"
          color="neutral"
          icon="i-lucide-store"
          to="https://help.etsy.com/hc/en-us/articles/360000343328-Downloading-a-Spreadsheet-of-Your-Sold-Transactions?segment=selling"
          target="_blank"
          trailing-icon="i-lucide-external-link"
          block
          size="lg"
          class="justify-start px-4 py-3"
        >
          Etsy – CSV-Export Anleitung
        </UButton>
        <UButton
          variant="outline"
          color="neutral"
          icon="i-lucide-shopping-cart"
          to="https://wisemerchant.com/ecommerce/shopify/export-orders-transactions"
          target="_blank"
          trailing-icon="i-lucide-external-link"
          block
          size="lg"
          class="justify-start px-4 py-3"
        >
          Shopify – Transaktionen exportieren
        </UButton>
        <UButton
          variant="outline"
          color="neutral"
          icon="i-lucide-credit-card"
          to="https://support.stripe.com/questions/exporting-payment-reports"
          target="_blank"
          trailing-icon="i-lucide-external-link"
          block
          size="lg"
          class="justify-start px-4 py-3"
        >
          Stripe – Zahlungsberichte exportieren
        </UButton>
      </div>
    </SectionCard>
  </div>
</template>
