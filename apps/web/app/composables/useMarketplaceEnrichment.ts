/**
 * Composable for OMS enrichment of CSV rows.
 *
 * Calls POST /api/v1/csv/enrich with file_id + mapping + oms_store_id.
 * Returns enriched rows with customer names and invoice numbers from the OMS provider.
 */
import type { CsvEnrichResponse, EnrichedRowResponse, GenericCsvMappingRequest } from '~/types/api'

export function useMarketplaceEnrichment() {
  const isEnriching = ref(false)
  const enrichError = ref<string | null>(null)
  const enrichedRows = ref<EnrichedRowResponse[]>([])
  const matchedCount = ref(0)
  const unmatchedCount = ref(0)

  const enrichRows = async (
    fileId: string,
    mapping: GenericCsvMappingRequest,
    omsStoreId: string,
  ): Promise<CsvEnrichResponse | null> => {
    isEnriching.value = true
    enrichError.value = null

    try {
      // file_id + oms_store_id as FormData (Form fields)
      const formData = new FormData()
      formData.append('file_id', fileId)
      formData.append('oms_store_id', omsStoreId)

      // Mapping as query params (Depends() reads query params, not form data)
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
      if (mapping.filter_include_values) {
        for (const value of mapping.filter_include_values)
          params.append('filter_include_values', value)
      }

      const result = await $fetch<CsvEnrichResponse>(`/api/v1/csv/enrich?${params.toString()}`, {
        method: 'POST',
        body: formData,
      })

      if (!result.success) {
        enrichError.value = result.error || 'Enrichment fehlgeschlagen'
        return null
      }

      enrichedRows.value = result.rows
      matchedCount.value = result.matched_count
      unmatchedCount.value = result.unmatched_count
      return result
    }
    catch (error) {
      enrichError.value = error instanceof Error ? error.message : 'Enrichment fehlgeschlagen'
      return null
    }
    finally {
      isEnriching.value = false
    }
  }

  const reset = () => {
    enrichedRows.value = []
    matchedCount.value = 0
    unmatchedCount.value = 0
    enrichError.value = null
  }

  return {
    enrichRows,
    isEnriching: readonly(isEnriching),
    enrichError: readonly(enrichError),
    enrichedRows: readonly(enrichedRows),
    matchedCount: readonly(matchedCount),
    unmatchedCount: readonly(unmatchedCount),
    reset,
  }
}
