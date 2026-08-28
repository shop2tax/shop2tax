/**
 * Composable for OMS (Order Management System) provider discovery.
 *
 * Loads the list of configured providers (e.g. Billbee) and exposes
 * helpers for gating OMS-related UI and resolving display names.
 */
import type { OmsProviderInfo } from '~/types/api'

export function useOmsProviders() {
  const { data: providers, refresh } = useFetch<OmsProviderInfo[]>('/api/v1/oms/providers', {
    key: 'oms-providers',
    default: () => [],
  })

  const hasAnyProvider = computed(() => (providers.value?.length ?? 0) > 0)
  const activeProviders = computed(() => providers.value?.filter(p => p.is_active) ?? [])
  const primaryProvider = computed(() => activeProviders.value[0])

  return { providers, hasAnyProvider, activeProviders, primaryProvider, refresh }
}
