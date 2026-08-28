/**
 * Composables for OMS (Order Management System) integration.
 */
import type {
  OmsLinkRequest,
  OmsOrderListResponse,
  OmsSettingsResponse,
  OmsStoreCreate,
  OmsStoreResponse,
  OmsStoreUpdate,
  OmsSyncLogListResponse,
  OmsSyncLogResponse,
  SyncResultResponse,
} from '~/types/api'

// --- Query Composables ---

export function useOmsSettings() {
  return useFetch<OmsSettingsResponse>('/api/v1/oms/settings', {
    key: 'oms-settings',
  })
}

export function useOmsLastSync() {
  return useFetch<OmsSyncLogResponse | null>('/api/v1/oms/sync/last', {
    key: 'oms-last-sync',
  })
}

export interface OmsSyncHistoryFilters {
  page?: number
  page_size?: number
}

export function useOmsSyncHistory(filters: Ref<OmsSyncHistoryFilters> = ref({})) {
  const query = computed(() => {
    const params = new URLSearchParams()
    const f = filters.value
    const pageSize = f.page_size ?? 100
    const page = f.page ?? 1
    params.set('limit', String(pageSize))
    params.set('offset', String((page - 1) * pageSize))
    return params.toString()
  })

  return useFetch<OmsSyncLogListResponse>(
    () => `/api/v1/oms/sync/history${query.value ? `?${query.value}` : ''}`,
    {
      key: computed(() => `oms-sync-history-${query.value}`).value,
      watch: [query],
    },
  )
}

// --- Mutation Functions ---

export function useOmsMutations() {
  const createStore = async (data: OmsStoreCreate): Promise<OmsStoreResponse> => {
    return $fetch<OmsStoreResponse>('/api/v1/oms/stores', {
      method: 'POST',
      body: data,
    })
  }

  const updateStore = async (id: string, data: OmsStoreUpdate): Promise<OmsStoreResponse> => {
    return $fetch<OmsStoreResponse>(`/api/v1/oms/stores/${id}`, {
      method: 'PUT',
      body: data,
    })
  }

  const deleteStore = async (id: string): Promise<void> => {
    await $fetch(`/api/v1/oms/stores/${id}`, {
      method: 'DELETE',
    })
  }

  const linkTransaction = async (transactionId: string, data: OmsLinkRequest): Promise<void> => {
    await $fetch(`/api/v1/oms/link/${transactionId}`, {
      method: 'POST',
      body: data,
    })
  }

  const unlinkTransaction = async (transactionId: string): Promise<void> => {
    await $fetch(`/api/v1/oms/link/${transactionId}`, {
      method: 'DELETE',
    })
  }

  const refreshCache = async (): Promise<OmsOrderListResponse> => {
    return $fetch<OmsOrderListResponse>('/api/v1/oms/orders?refresh=true')
  }

  /**
   * Trigger OMS sync with streaming progress updates.
   *
   * The API returns newline-delimited JSON (NDJSON):
   * - Progress events: {"type": "progress", "processed": N, "total": M, ...}
   * - Final event: {"type": "complete", "imported_count": N, ...}
   *
   * @param startDate - Start date for sync range (ISO format)
   * @param endDate - End date for sync range (ISO format)
   * @param onProgress - Callback for progress updates during sync
   * @returns Final sync result after stream completes
   */
  const triggerSync = async (
    startDate?: string,
    endDate?: string,
    onProgress?: (event: { processed: number, total: number, imported: number, skipped: number, errors: number }) => void,
  ): Promise<SyncResultResponse> => {
    const params = new URLSearchParams()
    if (startDate)
      params.set('start_date', startDate)
    if (endDate)
      params.set('end_date', endDate)
    const queryString = params.toString()

    // Use native fetch for streaming response (Nuxt $fetch doesn't support streams)
    const response = await fetch(`/api/v1/oms/sync${queryString ? `?${queryString}` : ''}`, {
      method: 'POST',
    })

    if (!response.ok) {
      const errorText = await response.text()
      throw new Error(errorText || `Sync failed: ${response.status}`)
    }

    const reader = response.body?.getReader()
    if (!reader) {
      throw new Error('Response body is not readable')
    }

    const decoder = new TextDecoder()
    let buffer = ''
    let finalResult: SyncResultResponse | null = null

    while (true) {
      const { done, value } = await reader.read()
      if (done)
        break

      buffer += decoder.decode(value, { stream: true })

      // Process complete NDJSON lines
      const lines = buffer.split('\n')
      buffer = lines.pop() ?? '' // Keep incomplete line in buffer

      for (const line of lines) {
        if (!line.trim())
          continue

        const event = JSON.parse(line) as { type: string } & Record<string, unknown>

        if (event.type === 'error') {
          throw new Error(event.error as string || `Sync failed (code ${event.code})`)
        }
        else if (event.type === 'progress' && onProgress) {
          onProgress({
            processed: event.processed as number,
            total: event.total as number,
            imported: event.imported as number,
            skipped: event.skipped as number,
            errors: event.errors as number,
          })
        }
        else if (event.type === 'complete') {
          finalResult = {
            imported_count: event.imported_count as number,
            skipped_count: event.skipped_count as number,
            pdf_count: event.pdf_count as number,
            pdf_error_count: event.pdf_error_count as number,
            linked_count: (event.linked_count as number) ?? 0,
            errors: event.errors as string[],
          }
        }
      }
    }

    // Process any remaining buffer content
    if (buffer.trim()) {
      const event = JSON.parse(buffer) as { type: string } & Record<string, unknown>
      if (event.type === 'complete') {
        finalResult = {
          imported_count: event.imported_count as number,
          skipped_count: event.skipped_count as number,
          pdf_count: event.pdf_count as number,
          pdf_error_count: event.pdf_error_count as number,
          linked_count: (event.linked_count as number) ?? 0,
          errors: event.errors as string[],
        }
      }
    }

    if (!finalResult) {
      throw new Error('Sync stream ended without complete event')
    }

    return finalResult
  }

  return {
    createStore,
    updateStore,
    deleteStore,
    linkTransaction,
    unlinkTransaction,
    refreshCache,
    triggerSync,
  }
}
