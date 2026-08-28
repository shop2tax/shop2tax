/**
 * Composable for server-side CSV file upload with file_id reference.
 *
 * Uploads a CSV file once, receives a file_id (UUID) for follow-up
 * operations (analyze, parse-generic, enrich). TTL: 30 minutes.
 */
import type { CsvFileUploadResponse } from '~/types/api'

export function useCsvFileUpload() {
  const isUploading = ref(false)
  const uploadError = ref<string | null>(null)
  const fileId = ref<string | null>(null)

  const uploadFile = async (file: File): Promise<CsvFileUploadResponse | null> => {
    isUploading.value = true
    uploadError.value = null
    fileId.value = null

    try {
      const formData = new FormData()
      formData.append('file', file)

      const result = await $fetch<CsvFileUploadResponse>('/api/v1/csv/upload-file', {
        method: 'POST',
        body: formData,
      })

      if (!result.success) {
        uploadError.value = 'Upload fehlgeschlagen'
        return null
      }

      fileId.value = result.file_id
      return result
    }
    catch (error) {
      uploadError.value = error instanceof Error ? error.message : 'Upload fehlgeschlagen'
      return null
    }
    finally {
      isUploading.value = false
    }
  }

  const reset = () => {
    fileId.value = null
    uploadError.value = null
  }

  return {
    uploadFile,
    isUploading: readonly(isUploading),
    uploadError: readonly(uploadError),
    fileId: readonly(fileId),
    reset,
  }
}
