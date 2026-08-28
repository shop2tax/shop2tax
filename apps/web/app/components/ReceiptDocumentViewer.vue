<script setup lang="ts">
const props = defineProps<{
  /** Blob URL for preview (image or PDF) */
  fileUrl?: string | null
  /** MIME type of the file */
  mimeType?: string | null
  /** Original file name */
  fileName?: string | null
  /** File size in bytes */
  fileSize?: number | null
  /** Show loading spinner */
  loading?: boolean
  /** Show upload dropzone when no file */
  canUpload?: boolean
  /** Show remove button in file header */
  canRemove?: boolean
  /** Show download button */
  canDownload?: boolean
}>()

const emit = defineEmits<{
  fileSelect: [file: File]
  remove: []
  download: []
}>()

const VuePdfEmbed = defineAsyncComponent(() => import('vue-pdf-embed'))

const toast = useToast()
const fileInputRef = ref<HTMLInputElement | null>(null)

const isPdf = computed(() => props.mimeType === 'application/pdf')
const isImage = computed(() => props.mimeType?.startsWith('image/'))
const hasFile = computed(() => !!props.fileUrl)

// PDF state
const currentPage = ref(1)
const totalPages = ref(1)
const pdfWidth = ref(600)
const pdfLoading = ref(false)

const zoomLevels = [400, 500, 600, 800, 1000]
const zoomIndex = ref(2) // start at 600

function zoomIn() {
  if (zoomIndex.value < zoomLevels.length - 1) {
    zoomIndex.value++
    pdfWidth.value = zoomLevels[zoomIndex.value]!
  }
}

function zoomOut() {
  if (zoomIndex.value > 0) {
    zoomIndex.value--
    pdfWidth.value = zoomLevels[zoomIndex.value]!
  }
}

const zoomPercent = computed(() => Math.round((pdfWidth.value / 600) * 100))

function handlePdfLoaded(pdfDocument: { numPages: number }) {
  totalPages.value = pdfDocument.numPages
  pdfLoading.value = false
}

// Reset PDF state when file changes
watch(() => props.fileUrl, () => {
  currentPage.value = 1
  totalPages.value = 1
  zoomIndex.value = 2
  pdfWidth.value = 600
  pdfLoading.value = true
})

function handleFileInput(event: Event) {
  const input = event.target as HTMLInputElement
  if (input.files?.[0]) {
    validateAndEmit(input.files[0])
  }
}

function handleDrop(event: DragEvent) {
  event.preventDefault()
  if (event.dataTransfer?.files?.[0]) {
    validateAndEmit(event.dataTransfer.files[0])
  }
}

function validateAndEmit(file: File) {
  const allowedTypes = ['image/jpeg', 'image/jpg', 'image/png', 'application/pdf', 'application/xml', 'text/xml']
  if (!allowedTypes.includes(file.type)) {
    toast.add({ title: 'Ungültiger Dateityp', description: 'Erlaubt: JPG, PNG, PDF, XML', color: 'error', icon: 'i-lucide-circle-x' })
    return
  }
  if (file.size > 10 * 1024 * 1024) {
    toast.add({ title: 'Datei zu groß', description: 'Maximale Größe: 10 MB', color: 'error', icon: 'i-lucide-circle-x' })
    return
  }
  emit('fileSelect', file)
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024)
    return `${bytes} B`
  return `${(bytes / 1024).toFixed(1)} KB`
}
</script>

<template>
  <div class="space-y-4">
    <!-- Dropzone (no file, upload allowed) -->
    <div
      v-if="!hasFile && !loading && canUpload"
      class="relative rounded-lg border-2 border-dashed border-stone-300 p-8 text-center transition-colors hover:border-primary-400 dark:border-stone-700 dark:hover:border-primary-500 cursor-pointer"
      @dragover.prevent
      @drop="handleDrop"
      @click="fileInputRef?.click()"
    >
      <input
        ref="fileInputRef"
        type="file"
        accept=".jpg,.jpeg,.png,.pdf,.xml"
        class="hidden"
        @change="handleFileInput"
      >
      <UIcon name="i-lucide-upload" class="mx-auto size-12 text-stone-400" />
      <p class="mt-4 text-sm font-medium text-stone-600 dark:text-stone-400">
        Datei hierher ziehen oder klicken
      </p>
      <p class="mt-1 text-xs text-stone-500">
        JPG, PNG, PDF, XML · max. 10 MB
      </p>
    </div>

    <!-- No file, no upload -->
    <div
      v-else-if="!hasFile && !loading && !canUpload"
      class="flex flex-col items-center justify-center rounded-lg border border-stone-200 bg-stone-50 py-24 text-stone-400 dark:border-stone-700 dark:bg-stone-900/50"
    >
      <UIcon name="i-lucide-file-x-2" class="size-16" />
      <p class="mt-4 text-sm">
        Kein Dokument hochgeladen
      </p>
    </div>

    <!-- Loading -->
    <div
      v-else-if="loading"
      class="flex items-center justify-center rounded-lg border border-stone-200 bg-stone-50 py-24 dark:border-stone-700 dark:bg-stone-900/50"
    >
      <UIcon name="i-lucide-loader-2" class="size-8 animate-spin text-primary" />
    </div>

    <!-- File preview -->
    <div v-else-if="hasFile" class="rounded-lg border border-stone-200 dark:border-stone-700 overflow-hidden">
      <!-- File info bar -->
      <div class="flex items-center justify-between border-b border-stone-200 px-4 py-2 dark:border-stone-700">
        <div class="flex items-center gap-2">
          <UIcon
            :name="isImage ? 'i-lucide-image' : isPdf ? 'i-lucide-file-text' : 'i-lucide-file-code'"
            class="size-4 text-stone-500"
          />
          <span v-if="fileName" class="text-sm font-medium truncate max-w-48">{{ fileName }}</span>
          <span v-if="fileSize" class="text-xs text-stone-500">({{ formatFileSize(fileSize) }})</span>
        </div>

        <div class="flex items-center gap-1">
          <!-- PDF controls -->
          <template v-if="isPdf">
            <UButton
              icon="i-lucide-minus"
              color="neutral"
              variant="ghost"
              size="xs"
              :disabled="zoomIndex <= 0"
              @click="zoomOut"
            />
            <span class="text-xs text-stone-500 w-10 text-center tabular-nums">{{ zoomPercent }}%</span>
            <UButton
              icon="i-lucide-plus"
              color="neutral"
              variant="ghost"
              size="xs"
              :disabled="zoomIndex >= zoomLevels.length - 1"
              @click="zoomIn"
            />

            <span class="mx-1 h-4 w-px bg-stone-200 dark:bg-stone-700" />

            <UButton
              icon="i-lucide-chevron-left"
              color="neutral"
              variant="ghost"
              size="xs"
              :disabled="currentPage <= 1"
              @click="currentPage--"
            />
            <span class="text-xs text-stone-500 tabular-nums">{{ currentPage }} / {{ totalPages }}</span>
            <UButton
              icon="i-lucide-chevron-right"
              color="neutral"
              variant="ghost"
              size="xs"
              :disabled="currentPage >= totalPages"
              @click="currentPage++"
            />
          </template>

          <span v-if="canRemove" class="mx-1 h-4 w-px bg-stone-200 dark:bg-stone-700" />
          <UButton
            v-if="canRemove"
            icon="i-lucide-x"
            color="neutral"
            variant="ghost"
            size="xs"
            @click="emit('remove')"
          />
        </div>
      </div>

      <!-- Image -->
      <div v-if="isImage" class="p-4">
        <img :src="fileUrl!" :alt="fileName || 'Vorschau'" class="max-h-[600px] w-full object-contain rounded">
      </div>

      <!-- PDF -->
      <div v-else-if="isPdf" class="relative overflow-auto bg-stone-100 dark:bg-stone-900" style="max-height: 700px;">
        <div v-if="pdfLoading" class="absolute inset-0 z-10 flex items-center justify-center bg-stone-100/80 dark:bg-stone-900/80">
          <UIcon name="i-lucide-loader-2" class="size-8 animate-spin text-primary" />
        </div>
        <div class="flex justify-center p-4">
          <ClientOnly>
            <VuePdfEmbed
              :source="fileUrl!"
              :page="currentPage"
              :width="pdfWidth"
              @loaded="handlePdfLoaded"
            />
          </ClientOnly>
        </div>
      </div>

      <!-- XML / other -->
      <div v-else class="flex items-center justify-center py-12 text-stone-400">
        <UIcon name="i-lucide-file-code" class="size-16" />
      </div>
    </div>

    <!-- Download button (below document) -->
    <div v-if="canDownload && hasFile" class="flex items-center justify-end">
      <UButton
        icon="i-lucide-download"
        color="neutral"
        variant="ghost"
        size="xs"
        @click="emit('download')"
      >
        Herunterladen
      </UButton>
    </div>
  </div>
</template>
