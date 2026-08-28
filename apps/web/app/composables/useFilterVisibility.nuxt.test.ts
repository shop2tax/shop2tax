// @vitest-environment nuxt
import { describe, expect, it } from 'vitest'
import { useFilterVisibility } from './useFilterVisibility'

// Runs under the Nuxt runtime so the auto-imported `useCookie` is available.
describe('useFilterVisibility', () => {
  it('defaults to hidden', () => {
    const { visible } = useFilterVisibility()
    expect(visible.value).toBe(false)
  })

  it('toggles between hidden and visible', () => {
    const { visible, toggle } = useFilterVisibility()
    toggle()
    expect(visible.value).toBe(true)
    toggle()
    expect(visible.value).toBe(false)
  })
})
