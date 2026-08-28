export function useFilterVisibility() {
  // useCookie is SSR-compatible — value is available on both server and client,
  // preventing hydration mismatches (unlike useLocalStorage which is client-only)
  const visible = useCookie('shop2tax:filters-visible', {
    default: () => false,
    watch: true,
  })

  function toggle() {
    visible.value = !visible.value
  }

  return { visible, toggle }
}
