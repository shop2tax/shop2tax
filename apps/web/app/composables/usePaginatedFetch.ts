/**
 * Generic composable for paginated API fetches.
 *
 * Handles the common URLSearchParams building pattern:
 * - page/page_size → limit/offset conversion
 * - Auto-sets all other non-null filter values
 *
 * Usage:
 *   const filters = ref({ page: 1, page_size: 50, status: 'open' })
 *   const { data, refresh } = usePaginatedFetch<MyResponse>('/api/v1/items', filters)
 */

interface PaginatedFilters {
  page?: number
  page_size?: number
  [key: string]: unknown
}

export function usePaginatedFetch<T>(
  baseUrl: string,
  filters: Ref<PaginatedFilters>,
  options?: {
    keyPrefix?: string
    defaultPageSize?: number
  },
) {
  const query = computed(() => {
    const params = new URLSearchParams()
    const f = filters.value
    const pageSize = f.page_size ?? options?.defaultPageSize ?? 100
    const page = f.page ?? 1
    params.set('limit', String(pageSize))
    params.set('offset', String((page - 1) * pageSize))

    for (const [key, val] of Object.entries(f)) {
      if (key === 'page' || key === 'page_size')
        continue
      if (val == null)
        continue
      // Skip empty strings
      if (typeof val === 'string' && !val.trim())
        continue
      params.set(key, String(val))
    }
    return params.toString()
  })

  // Auto-generate key prefix from URL if not provided
  const keyPrefix = options?.keyPrefix ?? baseUrl.replace(/^\/api\/v1\//, '').replace(/\//g, '-')

  return useFetch<T>(
    () => `${baseUrl}${query.value ? `?${query.value}` : ''}`,
    {
      key: computed(() => `${keyPrefix}-${query.value}`).value,
      watch: [query],
    },
  )
}
