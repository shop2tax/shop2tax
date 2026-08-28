/**
 * Composables for DATEV export operations.
 */
import type {
  DatevExportRequest,
  DatevExportResponse,
  DatevValidationResult,
  ExportHistoryResponse,
} from '~/types/api'

// --- Query Composables ---

export function useDatevHistory() {
  return useFetch<ExportHistoryResponse>('/api/v1/export/history', {
    key: 'datev-history',
  })
}

// --- Mutation Functions ---

export function useDatevMutations() {
  const exportJson = async (data: DatevExportRequest): Promise<DatevExportResponse> => {
    return $fetch<DatevExportResponse>('/api/v1/export/datev', {
      method: 'POST',
      body: data,
    })
  }

  const downloadCsv = async (data: DatevExportRequest): Promise<Blob> => {
    return $fetch<Blob>('/api/v1/export/datev/download', {
      method: 'POST',
      body: data,
      responseType: 'blob',
    })
  }

  const preview = async (data: DatevExportRequest): Promise<DatevExportResponse> => {
    return $fetch<DatevExportResponse>('/api/v1/export/datev', {
      method: 'POST',
      body: data,
    })
  }

  const validate = async (data: DatevExportRequest): Promise<DatevValidationResult> => {
    return $fetch<DatevValidationResult>('/api/v1/export/datev/validate', {
      method: 'POST',
      body: data,
    })
  }

  return {
    exportJson,
    downloadCsv,
    preview,
    validate,
  }
}

// --- ZIP Export Mutations ---

export interface DatevZipExportRequest {
  config: {
    beraternummer: string
    mandantennummer: string
    wirtschaftsjahr_beginn: string
    sachkontenlaenge?: number
  }
  date_from?: string
  date_to?: string
  include_receipts?: boolean
  finalized_only?: boolean
  document_types?: string[] | null
}

export interface DatevZipValidationResult {
  valid: boolean
  errors: string[]
  warnings: string[]
  receipts_without_file: string[]
  estimated_size_bytes: number
}

export function useDatevZipMutations() {
  const downloadZip = async (data: DatevZipExportRequest): Promise<Blob> => {
    return $fetch<Blob>('/api/v1/export/datev/download/zip', {
      method: 'POST',
      body: data,
      responseType: 'blob',
    })
  }

  const validateZip = async (data: DatevZipExportRequest): Promise<DatevZipValidationResult> => {
    return $fetch<DatevZipValidationResult>('/api/v1/export/datev/validate/zip', {
      method: 'POST',
      body: data,
    })
  }

  return {
    downloadZip,
    validateZip,
  }
}
