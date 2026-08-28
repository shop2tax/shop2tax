/**
 * Composables for Transaction Source API operations.
 *
 * Pattern: useFetch for queries (cached), $fetch for mutations (uncached)
 */
import type {
  TransactionSourceConfigCreate,
  TransactionSourceConfigResponse,
  TransactionSourceConfigUpdate,
} from '~/types/api'

// --- Query Composables ---

/**
 * Fetch all transaction sources (CSV parsers, API syncs, user-configured mappings).
 * Sources are cached and deduped across components.
 */
export function useSources() {
  return useFetch<TransactionSourceConfigResponse[]>('/api/v1/sources', {
    key: 'sources',
  })
}

/**
 * Fetch only CSV_MAPPING sources (user-configured bank imports).
 */
export function useBankSources() {
  return useFetch<TransactionSourceConfigResponse[]>('/api/v1/sources?type=csv_mapping', {
    key: 'sources-csv_mapping',
  })
}

// --- Mutation Functions ---

export function useSourceMutations() {
  /**
   * Create a new source.
   * Defaults to CSV_MAPPING type (user-configured bank imports).
   */
  const create = async (data: TransactionSourceConfigCreate): Promise<TransactionSourceConfigResponse> => {
    return $fetch<TransactionSourceConfigResponse>('/api/v1/sources', {
      method: 'POST',
      body: data,
    })
  }

  /**
   * Update a source.
   * Only user-owned sources can be updated.
   */
  const update = async (id: string, data: TransactionSourceConfigUpdate): Promise<TransactionSourceConfigResponse> => {
    return $fetch<TransactionSourceConfigResponse>(`/api/v1/sources/${id}`, {
      method: 'PUT',
      body: data,
    })
  }

  /**
   * Delete a source.
   * Only allowed if no transactions reference this source.
   */
  const remove = async (id: string): Promise<void> => {
    await $fetch(`/api/v1/sources/${id}`, {
      method: 'DELETE',
    })
  }

  return {
    create,
    update,
    remove,
  }
}
