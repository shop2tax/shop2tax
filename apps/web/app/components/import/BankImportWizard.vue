<script setup lang="ts">
const wizard = useImportWizardBase({ sourceType: 'csv_mapping' })
const {
  // Step
  currentStep,
  steps,
  // Sources
  sources,
  selectedSourceId,
  selectedSource,
  showNewSourceInput,
  newSourceName,
  isCreatingSource,
  handleCreateSource,
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
  columnCounterparty,
  columnDescription,
  columnReference,
  isMappingComplete,
  baseMapping,
  columnOptions,
  dateFormatOptions,
  // Preview
  parse,
  previewRows,
  parseErrors,
  isParsing,
  parseError,
  selectedRows,
  saveMappingCheckbox,
  isSavingMapping,
  toggleRow,
  toggleAll,
  // Import
  isImporting,
  executeImport,
} = wizard

const fileInputRef = useTemplateRef<HTMLInputElement>('fileInput')

// --- Live Preview: auto-parse when mapping changes ---
let parseDebounceTimer: ReturnType<typeof setTimeout> | null = null

watch(baseMapping, (mapping) => {
  if (parseDebounceTimer)
    clearTimeout(parseDebounceTimer)

  if (!mapping || !file.value) {
    previewRows.value = []
    selectedRows.value = new Set()
    parseErrors.value = []
    return
  }

  parseDebounceTimer = setTimeout(async () => {
    const result = await parse(file.value!, mapping)
    if (!result)
      return

    previewRows.value = result.rows
    parseErrors.value = result.errors
    selectedRows.value = new Set(result.rows.map((_, i) => i))
  }, 300)
}, { deep: true })

// --- Step Navigation ---
async function goToStep2() {
  if (!file.value || !selectedSourceId.value)
    return

  const result = await analyze(file.value)
  if (!result)
    return

  applyAnalyzeResult(result)
  await loadMappingOrSuggest(selectedSourceId.value, result)
  currentStep.value = 2
}

// --- Import ---
async function handleImport() {
  await executeImport(previewRows.value)
  if (wizard.importResult.value) {
    navigateTo({ path: '/transactions', query: selectedSourceId.value ? { source_config_id: selectedSourceId.value } : undefined })
  }
}
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

    <!-- Step 1: Upload + Source Selection -->
    <SectionCard v-if="currentStep === 1" title="Schritt 1: Datei hochladen">
      <ImportFileUpload
        :file="file"
        :analyze-error="analyzeError"

        @drop="handleDrop"
        @click="fileInputRef?.click()"
      >
        <template #source>
          <UFormField label="Bank-Quelle" required>
            <div v-if="!showNewSourceInput" class="flex gap-2">
              <USelect
                v-model="selectedSourceId"
                :items="sources.map(s => ({ value: s.id, label: s.name }))"
                placeholder="Quelle auswählen..."
                class="flex-1"
              />
              <UButton
                variant="outline"
                icon="i-lucide-plus"
                @click="showNewSourceInput = true"
              >
                Neu
              </UButton>
            </div>
            <div v-else class="flex gap-2">
              <UInput
                v-model="newSourceName"
                placeholder="Name der neuen Quelle..."
                class="flex-1"
                @keyup.enter="handleCreateSource"
              />
              <UButton
                color="primary"
                :loading="isCreatingSource"
                :disabled="!newSourceName.trim()"
                @click="() => { handleCreateSource() }"
              >
                Erstellen
              </UButton>
              <UButton
                variant="ghost"
                @click="showNewSourceInput = false; newSourceName = ''"
              >
                Abbrechen
              </UButton>
            </div>
          </UFormField>
        </template>
      </ImportFileUpload>

      <template #footer>
        <div class="flex justify-end">
          <UButton
            color="primary"
            :disabled="!file || !selectedSourceId"
            :loading="isAnalyzing"
            @click="goToStep2"
          >
            Weiter
          </UButton>
        </div>
      </template>
    </SectionCard>

    <!-- Step 2: Column Mapping + Live Preview -->
    <SectionCard v-show="currentStep === 2 && analyzeResult" title="Transaktionen prüfen">
      <template #header>
        <div class="flex items-center gap-3">
          <UBadge v-if="selectedSource" color="neutral" variant="soft" size="sm">
            {{ selectedSource.name }}
          </UBadge>
          <UIcon v-if="isParsing" name="i-lucide-loader-2" class="size-4 animate-spin text-stone-400" />
          <UBadge v-if="previewRows.length > 0" color="neutral" variant="soft" size="sm">
            {{ previewRows.length }} Zeilen
          </UBadge>
        </div>
      </template>

      <!-- Import Options -->
      <div class="mb-4 grid grid-cols-5 gap-2">
        <UFormField label="Zahlenformat">
          <USelect
            v-model="amountFormat"
            :items="[
              { value: 'german', label: 'Deutsch (1.234,56)' },
              { value: 'english', label: 'Englisch (1,234.56)' },
            ]"
          />
        </UFormField>
        <UFormField label="Datumsformat">
          <USelect
            v-model="dateFormat"
            :items="dateFormatOptions"
            placeholder="Format..."
          />
        </UFormField>
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

      <!-- Column Mapping Row -->
      <div class="mb-4 grid grid-cols-5 gap-2">
        <UFormField label="Datum" required>
          <USelect v-model="columnDate" :items="columnOptions" placeholder="Spalte..." />
        </UFormField>
        <UFormField label="Name" required>
          <USelect v-model="columnCounterparty" :items="columnOptions" placeholder="Spalte..." />
        </UFormField>
        <UFormField label="Verwendungszweck" required>
          <USelect v-model="columnDescription" :items="columnOptions" placeholder="Spalte..." />
        </UFormField>
        <UFormField label="Betrag" required>
          <USelect v-model="columnAmount" :items="columnOptions" placeholder="Spalte..." />
        </UFormField>
        <UFormField label="Referenz">
          <USelect v-model="columnReference" :items="columnOptions" placeholder="Keine" />
        </UFormField>
      </div>

      <ImportParseErrors :parse-error="parseError" :parse-errors="parseErrors" />

      <ImportPreviewTable
        :rows="previewRows"
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
  </div>
</template>
