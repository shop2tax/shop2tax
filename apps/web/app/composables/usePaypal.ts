/**
 * Composables for PayPal API sync.
 */
import type {
  PayPalSyncLogListResponse,
  PayPalSyncLogResponse,
  PayPalSyncRequest,
  PayPalSyncResponse,
} from '~/types/api'

// --- Query Composables ---

export function usePaypalLastSync() {
  return useFetch<PayPalSyncLogResponse | null>('/api/v1/paypal/sync/last', {
    key: 'paypal-last-sync',
  })
}

export interface PaypalSyncHistoryFilters {
  page?: number
  page_size?: number
}

export function usePaypalSyncHistory(filters: Ref<PaypalSyncHistoryFilters> = ref({})) {
  const query = computed(() => {
    const params = new URLSearchParams()
    const f = filters.value
    const pageSize = f.page_size ?? 100
    const page = f.page ?? 1
    params.set('limit', String(pageSize))
    params.set('offset', String((page - 1) * pageSize))
    return params.toString()
  })

  return useFetch<PayPalSyncLogListResponse>(
    () => `/api/v1/paypal/sync/history${query.value ? `?${query.value}` : ''}`,
    {
      key: computed(() => `paypal-sync-history-${query.value}`).value,
      watch: [query],
    },
  )
}

// --- Mutation Functions ---

export function usePaypalMutations() {
  const triggerSync = async (data: PayPalSyncRequest): Promise<PayPalSyncResponse> => {
    return $fetch<PayPalSyncResponse>('/api/v1/paypal/sync', {
      method: 'POST',
      body: data,
    })
  }

  return {
    triggerSync,
  }
}
