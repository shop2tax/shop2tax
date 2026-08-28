/**
 * Composables for Site Settings API operations.
 */
import type { PublicSettingsResponse, SiteSettingsResponse, SiteSettingsUpdate } from '~/types/api'

/**
 * Fetch public settings (unauthenticated).
 * Used by login page to display company name.
 */
export function usePublicSettings() {
  return useFetch<PublicSettingsResponse>('/api/v1/settings/public', {
    key: 'public-settings',
  })
}

/**
 * Fetch full site settings (authenticated).
 * Returns all fields including tax/business settings.
 */
export function useSiteSettings() {
  return useFetch<SiteSettingsResponse>('/api/v1/settings', {
    key: 'site-settings',
  })
}

/**
 * Mutations for site settings.
 */
export function useSiteSettingsMutations() {
  const update = async (data: SiteSettingsUpdate): Promise<SiteSettingsResponse> => {
    return $fetch<SiteSettingsResponse>('/api/v1/settings', {
      method: 'PATCH',
      body: data,
    })
  }

  return { update }
}
