import type { ExtractionResult } from '~/types/api'

export function useDocumentExtraction() {
  const extracting = ref(false)
  const extractionError = ref<string | null>(null)
  const extractionSource = ref<string | null>(null)
  const extractionWarnings = ref<string[]>([])

  async function extractFromFile(file: File): Promise<ExtractionResult | null> {
    extracting.value = true
    extractionError.value = null
    extractionWarnings.value = []
    try {
      const formData = new FormData()
      formData.append('file', file)
      const result = await $fetch<ExtractionResult>('/api/v1/receipts/extract', {
        method: 'POST',
        body: formData,
      })
      extractionSource.value = result.source
      extractionWarnings.value = result.warnings ?? []
      return result
    }
    catch (error: unknown) {
      const fetchError = error as { response?: { status?: number } }
      if (fetchError?.response?.status === 429) {
        extractionError.value = 'Stündliches Limit erreicht. Bitte warten oder manuell eingeben.'
      }
      else {
        extractionError.value = 'Automatische Erkennung fehlgeschlagen'
      }
      return null
    }
    finally {
      extracting.value = false
    }
  }

  return { extracting, extractionError, extractionSource, extractionWarnings, extractFromFile }
}
