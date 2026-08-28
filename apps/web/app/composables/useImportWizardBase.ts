/**
 * Shared base logic for CSV import wizards (Bank + Marketplace).
 *
 * Extracts common state: step navigation, source selection, CSV analysis,
 * column mapping, live preview, row selection, import execution.
 * Each wizard extends with its own specifics (file_id, filter, enrichment).
 */
import type {
  CsvAnalyzeResponse,
  CsvMappingProfileCreate,
  CsvMappingProfileResponse,
  GenericCsvMappingRequest,
  ParsedRowResponse,
  SourceType,
  TransactionSourceConfigResponse,
} from '~/types/api'

export type MappingColumn = 'date' | 'amount' | 'counterparty' | 'description' | 'reference'

export interface ImportWizardBaseOptions {
  sourceType: SourceType
  /** Which columns are required for mapping to be complete. Defaults to bank mode: date+amount+counterparty+description */
  requiredColumns?: MappingColumn[]
}

const BANK_REQUIRED_COLUMNS: MappingColumn[] = ['date', 'amount', 'counterparty', 'description']

export function useImportWizardBase(options: ImportWizardBaseOptions) {
  const toast = useToast()

  // --- Sources ---
  const { data: allSources, refresh: refreshSources } = useSources()
  const { create: createSource } = useSourceMutations()

  const sources = computed(() =>
    allSources.value?.filter(s => s.type === options.sourceType) || [],
  )

  // --- Step State ---
  const currentStep = ref(1)
  const steps = [
    { number: 1, label: 'Upload', icon: 'i-lucide-upload' },
    { number: 2, label: 'Zuordnung & Vorschau', icon: 'i-lucide-columns' },
  ]

  // --- Step 1: Source Selection ---
  const selectedSourceId = ref<string | undefined>(undefined)
  const showNewSourceInput = ref(false)
  const newSourceName = ref('')
  const isCreatingSource = ref(false)

  const selectedSource = computed(() =>
    sources.value.find(s => s.id === selectedSourceId.value) || null,
  )

  async function handleCreateSource() {
    if (!newSourceName.value.trim())
      return

    isCreatingSource.value = true
    try {
      const source = await createSource({
        name: newSourceName.value.trim(),
        type: options.sourceType,
      })
      await refreshSources()
      selectedSourceId.value = source.id
      showNewSourceInput.value = false
      newSourceName.value = ''
      toast.add({ title: 'Quelle erstellt', color: 'success', icon: 'i-lucide-check' })
      return source
    }
    catch {
      toast.add({ title: 'Fehler beim Erstellen', color: 'error', icon: 'i-lucide-circle-x' })
      return null
    }
    finally {
      isCreatingSource.value = false
    }
  }

  // --- Step 1: File ---
  const file = ref<File | null>(null)

  function handleFileChange(event: Event) {
    const target = event.target as HTMLInputElement
    const selectedFile = target.files?.[0]
    if (selectedFile)
      file.value = selectedFile
  }

  function handleDrop(event: DragEvent) {
    event.preventDefault()
    const droppedFile = event.dataTransfer?.files[0]
    if (droppedFile)
      file.value = droppedFile
  }

  // --- Step 2: Analysis ---
  const { analyze, isAnalyzing, analyzeError } = useCsvAnalyze()
  const { getMapping } = useMappingBySource()

  const analyzeResult = ref<CsvAnalyzeResponse | null>(null)

  // --- Step 2: Mapping State ---
  const delimiter = ref(',')
  const encoding = ref('utf-8')
  const hasHeader = ref(true)
  const skipRows = ref(0)
  const dateFormat = ref<string | undefined>(undefined)
  const amountFormat = ref<'german' | 'english'>('german')

  // Column mapping
  const columnDate = ref<string | undefined>(undefined)
  const columnAmount = ref<string | undefined>(undefined)
  const columnCounterparty = ref<string | undefined>(undefined)
  const columnDescription = ref<string | undefined>(undefined)
  const columnReference = ref<string | undefined>(undefined)

  const requiredColumns = options.requiredColumns ?? BANK_REQUIRED_COLUMNS

  const isMappingComplete = computed(() => {
    const columnMap: Record<MappingColumn, Ref<string | undefined>> = {
      date: columnDate,
      amount: columnAmount,
      counterparty: columnCounterparty,
      description: columnDescription,
      reference: columnReference,
    }

    // Date format is required whenever date column is required
    if (requiredColumns.includes('date') && !dateFormat.value)
      return false

    return requiredColumns.every(col => !!columnMap[col].value)
  })

  /** Base mapping without filter fields. Wizards can extend this. Only includes set columns. */
  const baseMapping = computed<GenericCsvMappingRequest | null>(() => {
    if (!isMappingComplete.value)
      return null

    return {
      delimiter: delimiter.value,
      encoding: encoding.value,
      has_header: hasHeader.value,
      skip_rows: skipRows.value,
      date_format: dateFormat.value,
      amount_format: amountFormat.value,
      column_date: columnDate.value,
      column_amount: columnAmount.value,
      column_counterparty: columnCounterparty.value,
      column_description: columnDescription.value,
      column_reference: columnReference.value,
    }
  })

  // Column options for dropdowns
  const columnOptions = computed(() => {
    if (!analyzeResult.value)
      return []
    return analyzeResult.value.column_headers.map(header => ({
      value: header,
      label: header,
    }))
  })

  // Common date formats
  const dateFormatOptions = [
    { value: '%d.%m.%Y', label: 'DD.MM.YYYY (31.12.2025)' },
    { value: '%d.%m.%y', label: 'DD.MM.YY (31.12.25)' },
    { value: '%d.%m.%Y %H:%M:%S', label: 'DD.MM.YYYY HH:MM:SS (31.12.2025 14:30:00)' },
    { value: '%Y-%m-%d', label: 'YYYY-MM-DD (2025-12-31)' },
    { value: '%Y-%m-%d %H:%M:%S', label: 'YYYY-MM-DD HH:MM:SS (2025-12-31 14:30:00)' },
    { value: '%d/%m/%Y', label: 'DD/MM/YYYY (31/12/2025)' },
    { value: '%m/%d/%Y', label: 'MM/DD/YYYY (12/31/2025)' },
    { value: '%d. %B %Y', label: 'DD. Monat YYYY (31. January 2026)' },
    { value: '%B %d, %Y', label: 'Monat DD, YYYY (January 31, 2026)' },
    { value: '%d %B %Y', label: 'DD Monat YYYY (31 January 2026)' },
  ]

  // --- Preview State ---
  const { parse, isParsing, parseError } = useGenericCsvParse()
  const previewRows = ref<ParsedRowResponse[]>([])
  const parseErrors = ref<string[]>([])
  const filteredCount = ref(0)
  const selectedRows = ref<Set<number>>(new Set())
  const saveMappingCheckbox = ref(true)
  const { saveMapping: saveMappingApi, isSaving: isSavingMapping } = useMappingMutations()

  // --- Row Selection ---
  function toggleRow(index: number) {
    if (selectedRows.value.has(index)) {
      selectedRows.value.delete(index)
    }
    else {
      selectedRows.value.add(index)
    }
    selectedRows.value = new Set(selectedRows.value)
  }

  function toggleAll(totalCount: number = previewRows.value.length) {
    if (selectedRows.value.size === totalCount) {
      selectedRows.value = new Set()
    }
    else {
      selectedRows.value = new Set(Array.from({ length: totalCount }, (_, i) => i))
    }
  }

  // --- Analysis & Mapping Application ---

  /** Apply detected CSV options from analyze result */
  function applyAnalyzeResult(result: CsvAnalyzeResponse) {
    analyzeResult.value = result
    if (result.delimiter)
      delimiter.value = result.delimiter
    if (result.encoding)
      encoding.value = result.encoding
    hasHeader.value = result.has_header
    skipRows.value = result.skip_rows
    if (result.date_format)
      dateFormat.value = result.date_format
    if (result.amount_format)
      amountFormat.value = result.amount_format as 'german' | 'english'
  }

  /** Apply a saved mapping profile to all column/option refs */
  function applySavedMapping(mapping: {
    delimiter: string
    encoding: string
    has_header: boolean
    skip_rows: number
    date_format: string | null
    amount_format: string | null
    column_date: string | null
    column_amount: string | null
    column_counterparty: string | null
    column_description: string | null
    column_reference: string | null
  }) {
    delimiter.value = mapping.delimiter
    encoding.value = mapping.encoding
    hasHeader.value = mapping.has_header
    skipRows.value = mapping.skip_rows
    dateFormat.value = mapping.date_format ?? undefined
    if (mapping.amount_format)
      amountFormat.value = mapping.amount_format as 'german' | 'english'
    columnDate.value = mapping.column_date ?? undefined
    columnAmount.value = mapping.column_amount ?? undefined
    columnCounterparty.value = mapping.column_counterparty ?? undefined
    columnDescription.value = mapping.column_description ?? undefined
    columnReference.value = mapping.column_reference ?? undefined
  }

  /** Apply auto-detected column suggestions */
  function applySuggestedColumns(result: CsvAnalyzeResponse) {
    if (!result.suggested_columns)
      return
    const suggestions = result.suggested_columns
    if (suggestions.column_date)
      columnDate.value = suggestions.column_date
    if (suggestions.column_counterparty)
      columnCounterparty.value = suggestions.column_counterparty
    if (suggestions.column_description)
      columnDescription.value = suggestions.column_description
    if (suggestions.column_reference)
      columnReference.value = suggestions.column_reference
    columnAmount.value = suggestions.column_amount ?? undefined
  }

  /** Load saved mapping or apply suggestions. Returns the saved mapping if found. */
  async function loadMappingOrSuggest(sourceId: string, result: CsvAnalyzeResponse): Promise<CsvMappingProfileResponse | null> {
    const savedMapping = await getMapping(sourceId)
    if (savedMapping) {
      applySavedMapping(savedMapping)
      toast.add({ title: 'Gespeicherte Zuordnung geladen', color: 'info', icon: 'i-lucide-info' })
      return savedMapping
    }
    applySuggestedColumns(result)
    return null
  }

  // --- Import ---
  const { bulkImport } = useTransactionMutations()
  const isImporting = ref(false)
  const importResult = ref<{ imported: number, skipped: number, errors: number, linked?: number, noReceipt?: number, skippedLocked?: number } | null>(null)

  /** Build mapping profile create data from current state */
  function buildMappingProfileCreate(extraFields?: Partial<CsvMappingProfileCreate>): CsvMappingProfileCreate {
    return {
      source_id: selectedSourceId.value!,
      delimiter: delimiter.value,
      encoding: encoding.value,
      has_header: hasHeader.value,
      skip_rows: skipRows.value,
      date_format: dateFormat.value,
      amount_format: amountFormat.value,
      column_date: columnDate.value,
      column_amount: columnAmount.value,
      column_counterparty: columnCounterparty.value,
      column_description: columnDescription.value,
      column_reference: columnReference.value,
      ...extraFields,
    }
  }

  /** Execute import with given rows. Handles save-mapping, bulk-import, toast, result. */
  async function executeImport(
    rows: ParsedRowResponse[],
    mappingExtra?: Partial<CsvMappingProfileCreate>,
  ) {
    if (!selectedSourceId.value || selectedRows.value.size === 0)
      return

    isImporting.value = true

    try {
      if (saveMappingCheckbox.value) {
        await saveMappingApi(buildMappingProfileCreate(mappingExtra))
      }

      const items = rows
        .filter((_, i) => selectedRows.value.has(i))
        .filter(row => row.date && row.amount != null)
        .map(row => ({
          date: row.date!,
          amount: row.amount!,
          counterparty: row.counterparty || '',
          description: row.description || '',
          source_reference: row.source_reference || undefined,
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
      toast.add({ title: `${result.imported_count} Buchungen importiert${skippedText}`, color: 'success', icon: 'i-lucide-check' })
    }
    catch {
      toast.add({ title: 'Fehler beim Import', color: 'error', icon: 'i-lucide-circle-x' })
    }
    finally {
      isImporting.value = false
    }
  }

  // --- Reset ---
  function reset() {
    currentStep.value = 1
    file.value = null
    selectedSourceId.value = undefined
    analyzeResult.value = null
    previewRows.value = []
    parseErrors.value = []
    filteredCount.value = 0
    selectedRows.value = new Set()
    importResult.value = null
  }

  return {
    // Toast (for wizard-specific messages)
    toast,
    // Sources
    sources: sources as Readonly<Ref<TransactionSourceConfigResponse[]>>,
    refreshSources,
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
    hasHeader,
    skipRows,
    dateFormat,
    amountFormat,
    columnDate,
    columnAmount,
    columnCounterparty,
    columnDescription,
    columnReference,
    isMappingComplete,
    requiredColumns,
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
    executeImport,
    // Step
    currentStep,
    steps,
    // Reset
    reset,
  }
}
