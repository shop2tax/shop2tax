/**
 * Syncs a tab value with a URL query parameter.
 * Reads from and writes to the query string, with validation against allowed values.
 *
 * Accepts static arrays or reactive (Ref/Computed) arrays for dynamic tabs.
 */
export function useQueryTab<T extends string>(
  allowedValues: MaybeRef<readonly T[]> | MaybeRef<T[]>,
  defaultValue: T,
  queryKey = 'tab',
) {
  const route = useRoute()
  const router = useRouter()

  return computed<T>({
    get: () => {
      const value = route.query[queryKey] as string
      const values = toValue(allowedValues)
      return values.includes(value as T) ? (value as T) : defaultValue
    },
    set: (value) => {
      router.replace({
        query: {
          ...route.query,
          [queryKey]: value === defaultValue ? undefined : value,
        },
      })
    },
  })
}
