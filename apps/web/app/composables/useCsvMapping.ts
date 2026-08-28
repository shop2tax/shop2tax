/**
 * Composables for Generic CSV Import with column mapping.
 *
 * Used by BankImportWizard for bank CSV imports that need user-defined column mapping.
 * Pattern: $fetch for all operations (no caching needed - file-based flow)
 */
import type {
  CsvAnalyzeResponse,
  CsvMappingProfileCreate,
  CsvMappingProfileResponse,
  GenericCsvMappingRequest,
  GenericCsvParseResponse,
} from '~/types/api'

/**
 * Analyze a CSV file to detect options and get column headers.
 * Supports both direct file upload and file_id reference.
 */
export function useCsvAnalyze() {
  const isAnalyzing = ref(false)
  const analyzeError = ref<string | null>(null)

  const analyze = async (fileOrId: File | string): Promise<CsvAnalyzeResponse | null> => {
    isAnalyzing.value = true
    analyzeError.value = null

    try {
      const formData = new FormData()
      if (typeof fileOrId === 'string') {
        formData.append('file_id', fileOrId)
      }
      else {
        formData.append('file', fileOrId)
      }

      const result = await $fetch<CsvAnalyzeResponse>('/api/v1/csv/analyze', {
        method: 'POST',
        body: formData,
      })

      if (!result.success) {
        analyzeError.value = result.error || 'Analyse fehlgeschlagen'
        return null
      }

      return result
    }
    catch (error) {
      analyzeError.value = error instanceof Error ? error.message : 'Unbekannter Fehler'
      return null
    }
    finally {
      isAnalyzing.value = false
    }
  }

  return {
    analyze,
    isAnalyzing,
    analyzeError,
  }
}

/**
 * Parse CSV with user-provided column mapping.
 * Supports both direct file upload and file_id reference.
 */
export function useGenericCsvParse() {
  const isParsing = ref(false)
  const parseError = ref<string | null>(null)

  const parse = async (fileOrId: File | string, mapping: GenericCsvMappingRequest): Promise<GenericCsvParseResponse | null> => {
    isParsing.value = true
    parseError.value = null

    try {
      const formData = new FormData()
      if (typeof fileOrId === 'string') {
        formData.append('file_id', fileOrId)
      }
      else {
        formData.append('file', fileOrId)
      }

      // Build query params from mapping — only send set columns
      const params = new URLSearchParams()
      params.set('delimiter', mapping.delimiter)
      params.set('encoding', mapping.encoding)
      params.set('has_header', String(mapping.has_header))
      params.set('skip_rows', String(mapping.skip_rows))

      if (mapping.date_format)
        params.set('date_format', mapping.date_format)
      if (mapping.amount_format)
        params.set('amount_format', mapping.amount_format)
      if (mapping.column_date)
        params.set('column_date', mapping.column_date)
      if (mapping.column_amount)
        params.set('column_amount', mapping.column_amount)
      if (mapping.column_counterparty)
        params.set('column_counterparty', mapping.column_counterparty)
      if (mapping.column_description)
        params.set('column_description', mapping.column_description)
      if (mapping.column_reference)
        params.set('column_reference', mapping.column_reference)
      if (mapping.column_filter)
        params.set('column_filter', mapping.column_filter)
      // FastAPI Depends() expects repeated query params for list[str]
      if (mapping.filter_include_values) {
        for (const value of mapping.filter_include_values)
          params.append('filter_include_values', value)
      }

      const result = await $fetch<GenericCsvParseResponse>(`/api/v1/csv/parse-generic?${params.toString()}`, {
        method: 'POST',
        body: formData,
      })

      if (!result.success) {
        parseError.value = result.error || 'Parsing fehlgeschlagen'
        return null
      }

      return result
    }
    catch (error) {
      parseError.value = error instanceof Error ? error.message : 'Unbekannter Fehler'
      return null
    }
    finally {
      isParsing.value = false
    }
  }

  return {
    parse,
    isParsing,
    parseError,
  }
}

/**
 * Fetch saved mapping profile for a specific source.
 */
export function useMappingBySource() {
  const getMapping = async (sourceId: string): Promise<CsvMappingProfileResponse | null> => {
    return await $fetch<CsvMappingProfileResponse | null>(`/api/v1/mappings/by-source/${sourceId}`)
  }

  return { getMapping }
}

/**
 * Create or update a CSV mapping profile.
 */
export function useMappingMutations() {
  const isSaving = ref(false)
  const saveError = ref<string | null>(null)

  const saveMapping = async (data: CsvMappingProfileCreate): Promise<CsvMappingProfileResponse | null> => {
    isSaving.value = true
    saveError.value = null

    try {
      return await $fetch<CsvMappingProfileResponse>('/api/v1/mappings', {
        method: 'POST',
        body: data,
      })
    }
    catch (error) {
      saveError.value = error instanceof Error ? error.message : 'Speichern fehlgeschlagen'
      return null
    }
    finally {
      isSaving.value = false
    }
  }

  return {
    saveMapping,
    isSaving,
    saveError,
  }
}
