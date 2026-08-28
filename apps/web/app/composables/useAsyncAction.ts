/**
 * Composable for async actions with automatic toast notifications and loading state.
 *
 * Usage:
 * ```ts
 * // Setup-level (recommended for actions reading reactive state):
 * const { execute: confirmDelete, isLoading: isDeleting } = useAsyncAction(
 *   async () => { await remove(id.value); refresh() },
 *   { success: 'Gelöscht', error: 'Fehler beim Löschen' }
 * )
 * ```
 */
export function useAsyncAction(
  action: () => Promise<void>,
  labels: { success: string, error: string },
) {
  const isLoading = ref(false)
  const toast = useToast()

  async function execute() {
    isLoading.value = true
    try {
      await action()
      toast.add({ title: labels.success, color: 'success', icon: 'i-lucide-check' })
    }
    catch (error) {
      toast.add({ title: labels.error, color: 'error', icon: 'i-lucide-circle-x' })
      throw error // ⚠️ Must re-throw — callers depend on error propagation
    }
    finally {
      isLoading.value = false
    }
  }

  return { execute, isLoading }
}
