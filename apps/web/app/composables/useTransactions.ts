/**
 * Composables for Transaction API operations.
 *
 * Pattern: useFetch for queries (cached), $fetch for mutations (uncached)
 */
import type {
  AutoLinkResponse,
  PaginatedResponse,
  TransactionCreate,
  TransactionImportRequest,
  TransactionImportResponse,
  TransactionResponse,
  TransactionUpdate,
  TransferSuggestion,
} from '~/types/api'

// --- Query Composables ---

export interface TransactionFilters {
  date_from?: string
  date_to?: string
  source_config_id?: string
  skr03_account_id?: number
  status?: string // TransactionStatus: open, assigned, booked, automatic, private, internal
  is_private?: boolean
  search?: string
  search_field?: string // counterparty, description, amount (undefined = all)
  page?: number
  page_size?: number
}

export function useTransactions(filters: Ref<TransactionFilters> = ref({})) {
  const query = computed(() => {
    const params = new URLSearchParams()
    const f = filters.value
    if (f.date_from)
      params.set('date_from', f.date_from)
    if (f.date_to)
      params.set('date_to', f.date_to)
    if (f.source_config_id)
      params.set('source_config_id', f.source_config_id)
    if (f.skr03_account_id)
      params.set('skr03_account_id', String(f.skr03_account_id))
    if (f.status && f.status !== 'all')
      params.set('status', f.status)
    if (f.is_private !== undefined)
      params.set('is_private', String(f.is_private))
    if (f.search)
      params.set('search', f.search)
    if (f.search_field)
      params.set('search_field', f.search_field)
    const pageSize = f.page_size ?? 100
    const page = f.page ?? 1
    params.set('limit', String(pageSize))
    params.set('offset', String((page - 1) * pageSize))
    return params.toString()
  })

  return useFetch<PaginatedResponse<TransactionResponse>>(
    () => `/api/v1/transactions${query.value ? `?${query.value}` : ''}`,
    {
      key: computed(() => `transactions-${query.value}`).value,
      watch: [query],
    },
  )
}

// --- Mutation Functions ---

export function useTransactionMutations() {
  const create = async (data: TransactionCreate): Promise<TransactionResponse> => {
    return $fetch<TransactionResponse>('/api/v1/transactions', {
      method: 'POST',
      body: data,
    })
  }

  const update = async (id: string, data: TransactionUpdate): Promise<TransactionResponse> => {
    return $fetch<TransactionResponse>(`/api/v1/transactions/${id}`, {
      method: 'PATCH',
      body: data,
    })
  }

  const remove = async (id: string): Promise<void> => {
    await $fetch(`/api/v1/transactions/${id}`, {
      method: 'DELETE',
    })
  }

  const setPrivate = async (id: string, isPrivate: boolean): Promise<TransactionResponse> => {
    return $fetch<TransactionResponse>(`/api/v1/transactions/${id}/private`, {
      method: 'PUT',
      body: { is_private: isPrivate },
    })
  }

  const bulkImport = async (data: TransactionImportRequest): Promise<TransactionImportResponse> => {
    return $fetch<TransactionImportResponse>('/api/v1/transactions/import', {
      method: 'POST',
      body: data,
    })
  }

  // Transfer (Geldbewegung) operations
  const getTransferSuggestions = async (id: string): Promise<TransferSuggestion[]> => {
    return $fetch<TransferSuggestion[]>(`/api/v1/transactions/${id}/transfer-suggestions`)
  }

  const linkTransfer = async (id: string, targetId: string): Promise<void> => {
    await $fetch(`/api/v1/transactions/${id}/link-transfer`, {
      method: 'POST',
      body: { target_transaction_id: targetId },
    })
  }

  const unlinkTransfer = async (id: string): Promise<void> => {
    await $fetch(`/api/v1/transactions/${id}/unlink-transfer`, {
      method: 'POST',
    })
  }

  const autoLinkReceipts = async (
    filters: { date_from?: string, date_to?: string, source_config_id?: string } = {},
  ): Promise<AutoLinkResponse> => {
    return $fetch<AutoLinkResponse>('/api/v1/transactions/auto-link-receipts', {
      method: 'POST',
      body: { transaction_ids: null },
      query: filters,
    })
  }

  return {
    create,
    update,
    remove,
    setPrivate,
    bulkImport,
    getTransferSuggestions,
    linkTransfer,
    unlinkTransfer,
    autoLinkReceipts,
  }
}
