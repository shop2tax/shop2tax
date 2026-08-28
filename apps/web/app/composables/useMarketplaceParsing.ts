/**
 * Composable for parsing marketplace CSV files using dedicated parsers (Etsy, Amazon, Shopify).
 *
 * These parsers skip the analyze + column mapping steps and go directly to parsing
 * with built-in knowledge of the CSV format.
 *
 * If an OMS store is linked, sales rows (with order_id) are automatically enriched
 * with customer data from the OMS provider.
 */
import type { MarketplaceCsvParseResponse, MarketplaceEnrichmentStats, MarketplaceParsedRowResponse } from '~/types/api'

export function useMarketplaceParsing() {
  const isParsing = ref(false)
  const parseError = ref<string | null>(null)
  const parseResult = ref<MarketplaceCsvParseResponse | null>(null)

  /**
   * Parse a marketplace CSV file using a dedicated parser.
   * Skips analyze + column mapping — the parser knows the format.
   * If omsStoreId is provided, sales rows are enriched with customer data.
   */
  async function parseMarketplaceCsv(
    fileId: string,
    sourceConfigId: string,
    omsStoreId?: string,
  ): Promise<MarketplaceCsvParseResponse | null> {
    isParsing.value = true
    parseError.value = null
    parseResult.value = null

    try {
      const formData = new FormData()
      formData.append('file_id', fileId)
      formData.append('source_config_id', sourceConfigId)
      if (omsStoreId) {
        formData.append('oms_store_id', omsStoreId)
      }

      const result = await $fetch<MarketplaceCsvParseResponse>('/api/v1/csv/parse-marketplace', {
        method: 'POST',
        body: formData,
      })

      if (!result.success) {
        parseError.value = result.error ?? 'Parsing fehlgeschlagen'
        return null
      }

      parseResult.value = result
      return result
    }
    catch (error) {
      parseError.value = error instanceof Error ? error.message : 'Parsing fehlgeschlagen'
      return null
    }
    finally {
      isParsing.value = false
    }
  }

  const enrichmentStats = computed<MarketplaceEnrichmentStats | null>(
    () => parseResult.value?.enrichment ?? null,
  )

  /**
   * Group parsed rows by marketplace_type (transaction type) for summary display.
   */
  function groupByType(rows: MarketplaceParsedRowResponse[]): Map<string, { count: number, total: number }> {
    const groups = new Map<string, { count: number, total: number }>()

    for (const row of rows) {
      const type = row.marketplace_type ?? 'unknown'
      const existing = groups.get(type) ?? { count: 0, total: 0 }
      existing.count++
      existing.total += Number.parseFloat(row.amount)
      groups.set(type, existing)
    }

    return groups
  }

  function reset() {
    isParsing.value = false
    parseError.value = null
    parseResult.value = null
  }

  return {
    // State
    isParsing,
    parseError,
    parseResult,
    enrichmentStats,
    // Actions
    parseMarketplaceCsv,
    groupByType,
    reset,
  }
}
