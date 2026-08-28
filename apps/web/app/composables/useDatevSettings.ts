/**
 * Composable for DATEV settings stored in the backend (per-user).
 * Replaces the old localStorage-based approach.
 */
import type { DatevConfig } from '~/types/api'

/**
 * Fetch the user's stored DATEV configuration.
 */
export function useDatevSettings() {
  return useFetch<DatevConfig | null>('/api/v1/export/datev/settings', {
    key: 'datev-settings',
  })
}

/**
 * Mutations for DATEV settings.
 */
export function useDatevSettingsMutations() {
  const save = async (config: DatevConfig): Promise<DatevConfig> => {
    return $fetch<DatevConfig>('/api/v1/export/datev/settings', {
      method: 'PUT',
      body: config,
    })
  }

  return { save }
}
