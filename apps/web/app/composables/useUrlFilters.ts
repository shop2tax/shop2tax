/**
 * Centralized URL-synced filter management.
 *
 * Handles:
 * - Two-way sync between filter state and URL query params
 * - Debounced search input (300ms)
 * - Page reset on filter change
 * - Active filter count for badge indicators
 * - Reset to defaults (preserving tab/source)
 *
 * Usage:
 *   const { filters, activeFilterCount, resetFilters, debouncedSearch } = useUrlFilters({
 *     search: { default: undefined, queryKey: 'search' },
 *     type: { default: undefined, queryKey: 'type' },
 *     status: { default: 'all', queryKey: 'status' },
 *   })
 */

type FilterValue = string | number | boolean | undefined

interface FilterFieldConfig {
  default: FilterValue
  /** URL query parameter name. Defaults to the field key. */
  queryKey?: string
  /** If true, this field is excluded from activeFilterCount (e.g. tab, page). */
  excludeFromCount?: boolean
  /** If true, changes to this field are debounced (for search inputs). */
  debounce?: number
}

type FilterSchema = Record<string, FilterFieldConfig>

type FilterState<_T extends FilterSchema> = Record<string, any>

export function useUrlFilters<T extends FilterSchema>(schema: T) {
  const route = useRoute()
  const router = useRouter()

  // Build initial state from URL query + defaults
  function buildState(): FilterState<T> {
    const state = {} as Record<string, FilterValue>
    for (const [key, config] of Object.entries(schema)) {
      const queryKey = config.queryKey ?? key
      const queryValue = route.query[queryKey] as string | undefined
      if (queryValue !== undefined && queryValue !== null) {
        // Coerce to the type of the default value
        if (typeof config.default === 'boolean') {
          state[key] = queryValue === 'true'
        }
        else if (typeof config.default === 'number') {
          state[key] = Number(queryValue)
        }
        else {
          state[key] = queryValue
        }
      }
      else {
        state[key] = config.default
      }
    }
    return state as FilterState<T>
  }

  const filters = ref(buildState()) as Ref<FilterState<T>>

  // Debounce timers for search fields
  const debounceTimers = new Map<string, ReturnType<typeof setTimeout>>()

  // Sync filters → URL (skip internal fields like page)
  function syncToUrl() {
    const query = { ...route.query } as Record<string, string | undefined>

    for (const [key, config] of Object.entries(schema)) {
      const queryKey = config.queryKey ?? key
      const value = (filters.value as Record<string, FilterValue>)[key]
      const defaultValue = config.default

      // Only write to URL if value differs from default
      if (value !== undefined && value !== null && value !== defaultValue && value !== '') {
        query[queryKey] = String(value)
      }
      else {
        query[queryKey] = undefined
      }
    }

    router.replace({ query })
  }

  // Watch for filter changes → sync to URL + reset page
  let skipUrlSync = false

  watch(filters, (newFilters, oldFilters) => {
    if (skipUrlSync)
      return

    // Reset page to 1 if any non-page filter changed
    const pageKey = Object.keys(schema).find(k => k === 'page')
    if (pageKey && oldFilters) {
      const changed = Object.keys(schema).some(k =>
        k !== 'page' && k !== 'page_size'
        && (newFilters as Record<string, FilterValue>)[k] !== (oldFilters as Record<string, FilterValue>)[k],
      )
      if (changed) {
        (filters.value as Record<string, FilterValue>).page = schema.page?.default ?? 1
      }
    }

    syncToUrl()
  }, { deep: true })

  // Count active filters (excludes fields marked with excludeFromCount)
  const activeFilterCount = computed(() => {
    let count = 0
    for (const [key, config] of Object.entries(schema)) {
      if (config.excludeFromCount)
        continue
      const value = (filters.value as Record<string, FilterValue>)[key]
      if (value !== undefined && value !== null && value !== config.default && value !== '') {
        count++
      }
    }
    return count
  })

  // Create a debounced model for search fields
  function createDebouncedModel(fieldKey: keyof T & string, delayMs = 300) {
    const immediate = ref((filters.value as Record<string, FilterValue>)[fieldKey] as string | undefined)

    // When the debounced filter changes externally (e.g. reset), update immediate
    watch(() => (filters.value as Record<string, FilterValue>)[fieldKey], (value) => {
      immediate.value = value as string | undefined
    })

    // When immediate changes (user typing), debounce the filter update
    watch(immediate, (value) => {
      const existing = debounceTimers.get(fieldKey)
      if (existing)
        clearTimeout(existing)

      debounceTimers.set(fieldKey, setTimeout(() => {
        (filters.value as Record<string, FilterValue>)[fieldKey] = value
        debounceTimers.delete(fieldKey)
      }, delayMs))
    })

    return immediate
  }

  // Reset all filters to defaults
  function resetFilters(preserve?: (keyof T)[]) {
    skipUrlSync = true
    const state = {} as Record<string, FilterValue>
    for (const [key, config] of Object.entries(schema)) {
      if (preserve?.includes(key as keyof T)) {
        state[key] = (filters.value as Record<string, FilterValue>)[key]
      }
      else {
        state[key] = config.default
      }
    }
    filters.value = state as FilterState<T>
    skipUrlSync = false
    syncToUrl()
  }

  // Set a single filter value
  function setFilter<K extends keyof T & string>(key: K, value: FilterState<T>[K]) {
    (filters.value as Record<string, FilterValue>)[key] = value as FilterValue
  }

  return {
    filters,
    activeFilterCount,
    resetFilters,
    setFilter,
    createDebouncedModel,
  }
}
