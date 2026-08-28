/**
 * Composables for Receipt (Beleg) management.
 */
import type {
  AccountSuggestionResponse,
  ReceiptCreate,
  ReceiptCreateAndLink,
  ReceiptListResponse,
  ReceiptLockRequest,
  ReceiptResponse,
  ReceiptStatus,
  ReceiptType,
} from '~/types/api'

// --- Query Composables ---

export type ReceiptTab = 'all' | 'draft' | 'open' | 'overdue' | 'finalized'

export interface ReceiptFilters {
  page?: number
  page_size?: number
  type?: ReceiptType
  status?: ReceiptStatus
  start_date?: string
  end_date?: string
  linked?: boolean
  locked?: boolean
  payment_status?: string
  tab?: ReceiptTab
  search?: string
}

export function useReceipts(filters: Ref<ReceiptFilters> = ref({})) {
  // Transform ReceiptFilters to API param names
  const apiFilters = computed(() => {
    const f = filters.value
    return {
      page: f.page,
      page_size: f.page_size,
      receipt_type: f.type,
      status: f.status,
      start_date: f.start_date,
      end_date: f.end_date,
      is_linked: f.linked,
      is_locked: f.locked,
      payment_status: f.payment_status,
      tab: f.tab && f.tab !== 'all' ? f.tab : undefined,
      search: f.search?.trim() || undefined,
    }
  })

  return usePaginatedFetch<ReceiptListResponse>('/api/v1/receipts', apiFilters, {
    keyPrefix: 'receipts',
  })
}

export function useReceipt(id: string | Ref<string>) {
  const idRef = toRef(id)
  return useFetch<ReceiptResponse>(
    () => `/api/v1/receipts/${idRef.value}`,
    { key: `receipt-${idRef.value}` },
  )
}

/**
 * Suggest SKR03 account for a counterparty based on learned patterns.
 * Debounced (300ms). Returns null when no suggestion or counterparty is empty.
 */
export function useSuggestAccount(counterparty: Ref<string>) {
  const suggestedAccountId = ref<number | null>(null)
  const confidence = ref<number | null>(null)

  let debounceTimer: ReturnType<typeof setTimeout> | null = null

  watch(counterparty, (value) => {
    if (debounceTimer)
      clearTimeout(debounceTimer)

    if (!value.trim()) {
      suggestedAccountId.value = null
      confidence.value = null
      return
    }

    debounceTimer = setTimeout(async () => {
      try {
        const result = await $fetch<AccountSuggestionResponse>(
          `/api/v1/receipts/suggest-account?counterparty=${encodeURIComponent(value.trim())}`,
        )
        suggestedAccountId.value = result.skr03_account_id
        confidence.value = result.confidence
      }
      catch {
        suggestedAccountId.value = null
        confidence.value = null
      }
    }, 300)
  })

  return { suggestedAccountId, confidence }
}

// --- Mutation Functions ---

export function useReceiptMutations() {
  /**
   * Soft-delete a receipt (only if unlinked + unlocked).
   */
  const deleteReceipt = async (id: string): Promise<void> => {
    await $fetch(`/api/v1/receipts/${id}`, {
      method: 'DELETE',
    })
  }

  /**
   * Link a receipt to a payment (transaction).
   */
  const linkToPayment = async (receiptId: string, transactionId: string): Promise<void> => {
    await $fetch(`/api/v1/receipts/${receiptId}/link`, {
      method: 'POST',
      body: { transaction_id: transactionId },
    })
  }

  /**
   * Unlink a receipt from its payment.
   */
  const unlinkFromPayment = async (receiptId: string): Promise<void> => {
    await $fetch(`/api/v1/receipts/${receiptId}/unlink`, {
      method: 'POST',
    })
  }

  /**
   * Lock receipts in a date range (GoBD finalization).
   */
  const lockReceipts = async (data: ReceiptLockRequest): Promise<{ locked_count: number }> => {
    return $fetch<{ locked_count: number }>('/api/v1/receipts/lock', {
      method: 'POST',
      body: data,
    })
  }

  /**
   * Download receipt file.
   */
  const downloadFile = async (receiptId: string): Promise<Blob> => {
    return $fetch<Blob>(`/api/v1/receipts/${receiptId}/file`, {
      responseType: 'blob',
    })
  }

  /**
   * Create a receipt (without linking to a transaction).
   * File upload is handled separately via uploadFile.
   */
  const createReceipt = async (
    data: ReceiptCreate,
  ): Promise<ReceiptResponse> => {
    return $fetch<ReceiptResponse>('/api/v1/receipts', {
      method: 'POST',
      body: data,
    })
  }

  /**
   * Create a receipt and link it to a transaction in one request.
   * File upload is handled separately via uploadFile.
   */
  const createAndLinkReceipt = async (
    data: ReceiptCreateAndLink,
  ): Promise<ReceiptResponse> => {
    return $fetch<ReceiptResponse>('/api/v1/receipts/create-and-link', {
      method: 'POST',
      body: data,
    })
  }

  /**
   * Create a receipt and bulk-link to multiple transactions (Sammelbeleg).
   * Used when creating from selected transactions (e.g., Etsy-PDF → 200 Fees).
   * File upload is handled separately via uploadFile.
   */
  const createAndLinkBulkReceipt = async (
    data: ReceiptCreate,
    transactionIds: string[],
  ): Promise<ReceiptResponse> => {
    return $fetch<ReceiptResponse>('/api/v1/receipts/create-and-link-bulk', {
      method: 'POST',
      body: { ...data, transaction_ids: transactionIds },
    })
  }

  /**
   * Upload a file to an existing receipt.
   */
  const uploadFile = async (
    receiptId: string,
    file: File,
  ): Promise<ReceiptResponse> => {
    const formData = new FormData()
    formData.append('file', file)
    return $fetch<ReceiptResponse>(`/api/v1/receipts/${receiptId}/upload`, {
      method: 'POST',
      body: formData,
    })
  }

  /**
   * Update a draft receipt (PATCH).
   */
  const updateReceipt = async (
    receiptId: string,
    data: Record<string, unknown>,
  ): Promise<ReceiptResponse> => {
    return $fetch<ReceiptResponse>(`/api/v1/receipts/${receiptId}`, {
      method: 'PATCH',
      body: data,
    })
  }

  return {
    createReceipt,
    updateReceipt,
    deleteReceipt,
    linkToPayment,
    unlinkFromPayment,
    lockReceipts,
    downloadFile,
    createAndLinkReceipt,
    createAndLinkBulkReceipt,
    uploadFile,
  }
}
