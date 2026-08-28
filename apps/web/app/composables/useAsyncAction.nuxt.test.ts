import { mockNuxtImport } from '@nuxt/test-utils/runtime'
// @vitest-environment nuxt
import { describe, expect, it, vi } from 'vitest'
import { useAsyncAction } from './useAsyncAction'

const toastAdd = vi.fn()
mockNuxtImport('useToast', () => () => ({ add: toastAdd }))

describe('useAsyncAction', () => {
  it('toggles isLoading around the action and resets on success', async () => {
    let resolveAction: () => void
    const action = () => new Promise<void>((resolve) => {
      resolveAction = resolve
    })
    const { execute, isLoading } = useAsyncAction(action, { success: 'ok', error: 'fail' })

    expect(isLoading.value).toBe(false)
    const pending = execute()
    expect(isLoading.value).toBe(true)
    resolveAction!()
    await pending
    expect(isLoading.value).toBe(false)
  })

  it('shows a success toast when the action succeeds', async () => {
    toastAdd.mockClear()
    const { execute } = useAsyncAction(async () => {}, { success: 'Gelöscht', error: 'Fehler' })
    await execute()
    expect(toastAdd).toHaveBeenCalledWith(expect.objectContaining({ title: 'Gelöscht', color: 'success' }))
  })

  it('re-throws the error so callers can react, and still resets isLoading', async () => {
    toastAdd.mockClear()
    const boom = new Error('boom')
    const { execute, isLoading } = useAsyncAction(async () => {
      throw boom
    }, { success: 'ok', error: 'Fehler' })

    await expect(execute()).rejects.toThrow('boom')
    expect(isLoading.value).toBe(false)
    expect(toastAdd).toHaveBeenCalledWith(expect.objectContaining({ title: 'Fehler', color: 'error' }))
  })
})
