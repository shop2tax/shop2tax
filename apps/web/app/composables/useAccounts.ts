/**
 * Composables for SKR03 Account API operations.
 */
import type { SKR03AccountCreate, SKR03AccountResponse, SKR03AccountUpdate } from '~/types/api'

export function useAccounts() {
  return useFetch<SKR03AccountResponse[]>('/api/v1/accounts?active_only=false', {
    key: 'skr03-accounts-all',
  })
}

export function useActiveAccounts() {
  return useFetch<SKR03AccountResponse[]>('/api/v1/accounts?active_only=true', {
    key: 'skr03-accounts-active',
  })
}

export function useAccountMutations() {
  async function createAccount(data: SKR03AccountCreate) {
    return $fetch<SKR03AccountResponse>('/api/v1/accounts', {
      method: 'POST',
      body: data,
    })
  }

  async function updateAccount(accountId: number, data: SKR03AccountUpdate) {
    return $fetch<SKR03AccountResponse>(`/api/v1/accounts/${accountId}`, {
      method: 'PATCH',
      body: data,
    })
  }

  return { createAccount, updateAccount }
}
