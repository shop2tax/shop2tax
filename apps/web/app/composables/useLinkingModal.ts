/**
 * Composable for LinkingModal — shared state and API calls for receipt↔transaction linking.
 *
 * Supports three modes:
 * - find-transaction: From a receipt, find and link to a transaction (or record manual payment)
 * - find-receipt: From a transaction, find and link to a receipt
 * - bulk: From a receipt, find and bulk-link multiple transactions (Sammelbeleg)
 */
import type {
  BulkLinkResponse,
  BulkSuggestionResponse,
  FindMatchingReceiptsResponse,
  ReceiptMatchSuggestion,
  ReceiptResponse,
  ReceiptSuggestionForPayment,
  RecordPaymentRequest,
  TransactionResponse,
} from '~/types/api'

export type LinkingMode = 'find-transaction' | 'find-receipt' | 'bulk'

export interface TransactionSuggestionFilters {
  source_config_id?: string
  search?: string
}

export interface ReceiptSuggestionFilters {
  receipt_type?: 'revenue' | 'expense'
  search?: string
}

/**
 * Fetch transaction suggestions for a receipt with reactive filters.
 */
export function useTransactionSuggestions(
  receiptId: Ref<string | undefined>,
  filters: Ref<TransactionSuggestionFilters>,
) {
  const query = computed(() => {
    const params = new URLSearchParams()
    const f = filters.value
    if (f.source_config_id)
      params.set('source_config_id', f.source_config_id)
    if (f.search?.trim())
      params.set('search', f.search.trim())
    return params.toString()
  })

  const url = computed(() => {
    const id = receiptId.value ?? '_'
    const queryString = query.value ? `?${query.value}` : ''
    return `/api/v1/receipts/${id}/suggestions${queryString}`
  })

  return useFetch<ReceiptMatchSuggestion[]>(url, {
    key: computed(() => `receipt-suggestions-${receiptId.value}-${query.value}`).value,
    watch: [receiptId, query],
    immediate: false,
  })
}

/**
 * Fetch receipt suggestions for a transaction with reactive filters.
 */
export function useReceiptSuggestions(
  transactionId: Ref<string | undefined>,
  filters: Ref<ReceiptSuggestionFilters>,
) {
  const query = computed(() => {
    const params = new URLSearchParams()
    const f = filters.value
    if (f.receipt_type)
      params.set('receipt_type', f.receipt_type)
    if (f.search?.trim())
      params.set('search', f.search.trim())
    return params.toString()
  })

  const url = computed(() => {
    const id = transactionId.value ?? '_'
    const queryString = query.value ? `?${query.value}` : ''
    return `/api/v1/transactions/${id}/receipt-suggestions${queryString}`
  })

  return useFetch<ReceiptSuggestionForPayment[]>(url, {
    key: computed(() => `transaction-receipt-suggestions-${transactionId.value}-${query.value}`).value,
    watch: [transactionId, query],
    immediate: false,
  })
}

/**
 * Mutations for linking modal operations.
 */
export function useLinkingMutations() {
  /**
   * Link a receipt to a transaction (same API call regardless of direction).
   */
  const linkReceiptToTransaction = async (receiptId: string, transactionId: string): Promise<void> => {
    await $fetch(`/api/v1/receipts/${receiptId}/link`, {
      method: 'POST',
      body: { transaction_id: transactionId },
    })
  }

  // Alias — same API endpoint, kept for semantic clarity at call sites
  const linkTransactionToReceipt = linkReceiptToTransaction

  /**
   * Record a manual payment for a receipt.
   * Creates a new transaction and links it to the receipt.
   */
  const recordPayment = async (receiptId: string, data: RecordPaymentRequest): Promise<TransactionResponse> => {
    return $fetch<TransactionResponse>(`/api/v1/receipts/${receiptId}/record-payment`, {
      method: 'POST',
      body: data,
    })
  }

  /**
   * Unlink a receipt from its transaction.
   */
  const unlinkReceipt = async (receiptId: string): Promise<void> => {
    await $fetch(`/api/v1/receipts/${receiptId}/unlink`, {
      method: 'POST',
    })
  }

  /**
   * Bulk-link multiple transactions to a receipt (Sammelbeleg).
   * Used for: Etsy-PDF → 200 Fees, PayPal-Gebührenabrechnung → N Fees.
   */
  const bulkLinkTransactions = async (receiptId: string, transactionIds: string[]): Promise<BulkLinkResponse> => {
    return $fetch<BulkLinkResponse>(`/api/v1/receipts/${receiptId}/link-bulk`, {
      method: 'POST',
      body: { transaction_ids: transactionIds },
    })
  }

  /**
   * Bulk-unlink specific transactions from a receipt.
   * Requires at least one transaction ID (empty list is rejected by API).
   */
  const bulkUnlinkTransactions = async (receiptId: string, transactionIds: string[]): Promise<{ unlinked_count: number, remaining_link_count: number }> => {
    return $fetch(`/api/v1/receipts/${receiptId}/unlink-bulk`, {
      method: 'POST',
      body: { transaction_ids: transactionIds },
    })
  }

  return {
    linkReceiptToTransaction,
    recordPayment,
    linkTransactionToReceipt,
    unlinkReceipt,
    bulkLinkTransactions,
    bulkUnlinkTransactions,
  }
}

/**
 * Fetch bulk suggestions for a receipt (Sammelbeleg matching).
 * Groups transactions by type and calculates totals for quick selection.
 * Uses mode=bulk parameter on the existing suggestions endpoint.
 */
export function useBulkSuggestions(receiptId: Ref<string | undefined>) {
  const url = computed(() => `/api/v1/receipts/${receiptId.value ?? '_'}/suggestions?mode=bulk`)

  return useFetch<BulkSuggestionResponse>(url, {
    key: computed(() => `receipt-bulk-suggestions-${receiptId.value}`).value,
    watch: [receiptId],
    immediate: false,
  })
}

/**
 * Find matching receipts for selected transactions (reverse lookup).
 * Used when user selects transactions first and wants to find/create a receipt.
 */
export async function findMatchingReceipts(transactionIds: string[]): Promise<FindMatchingReceiptsResponse> {
  return $fetch<FindMatchingReceiptsResponse>('/api/v1/transactions/find-matching-receipts', {
    method: 'POST',
    body: { transaction_ids: transactionIds },
  })
}

/**
 * Helper to get receipt details for display in modal header.
 */
export function useReceiptForLinking(receiptId: Ref<string | undefined>) {
  const url = computed(() => `/api/v1/receipts/${receiptId.value ?? '_'}`)

  return useFetch<ReceiptResponse>(url, {
    key: computed(() => `receipt-linking-${receiptId.value}`).value,
    watch: [receiptId],
    immediate: false,
  })
}

/**
 * Helper to get transaction details for display in modal header.
 */
export function useTransactionForLinking(transactionId: Ref<string | undefined>) {
  const url = computed(() => `/api/v1/transactions/${transactionId.value ?? '_'}`)

  return useFetch<TransactionResponse>(url, {
    key: computed(() => `transaction-linking-${transactionId.value}`).value,
    watch: [transactionId],
    immediate: false,
  })
}
