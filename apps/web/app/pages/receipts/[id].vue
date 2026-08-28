<script setup lang="ts">
import type { ExtractionResult, TagResponse } from '~/types/api'

definePageMeta({
  middleware: ['auth'],
})

const route = useRoute()
const router = useRouter()
const toast = useToast()

const receiptId = computed(() => route.params.id as string)

const { primaryProvider } = useOmsProviders()
const omsProviderName = computed(() => primaryProvider.value?.display_name ?? 'Warenwirtschaft')

// Fetch receipt data with all relationships
const { data: receipt, refresh, status: fetchStatus } = useReceipt(receiptId)

// Fetch all user tags for autocomplete
const { data: allTags } = useFetch<TagResponse[]>('/api/v1/tags', { key: 'user-tags' })

// File management
const { downloadFile, uploadFile, unlinkFromPayment, deleteReceipt } = useReceiptMutations()

// LinkingModal state
const isLinkingModalOpen = ref(false)
const isUnlinking = ref(false)
const linkingMode = ref<'find-transaction' | 'bulk'>('find-transaction')

async function handleUnlink() {
  if (!receipt.value)
    return
  isUnlinking.value = true
  try {
    await unlinkFromPayment(receipt.value.id)
    toast.add({ title: 'Verknüpfung aufgehoben', color: 'success', icon: 'i-lucide-check' })
    refresh()
  }
  catch {
    toast.add({ title: 'Fehler beim Aufheben', color: 'error', icon: 'i-lucide-circle-x' })
  }
  finally {
    isUnlinking.value = false
  }
}

function handleLinked() {
  isLinkingModalOpen.value = false
  refresh()
}
const { extracting, extractionError, extractionSource, extractFromFile } = useDocumentExtraction()

// Fetch site settings for rc_tax_rate
const { data: siteSettings } = useSiteSettings()
const rcTaxRate = computed(() => siteSettings.value?.rc_tax_rate ?? 0.19)

const isDraft = computed(() => receipt.value?.status === 'draft')
const canUploadFile = computed(() => isDraft.value && !receipt.value?.has_file && !receipt.value?.is_locked)

// Tag management state
const newTagInput = ref('')
const isAddingTag = ref(false)

// File viewer state
const fileUrl = ref<string | null>(null)
const isLoadingFile = ref(false)

// Load file preview when receipt changes
watch(receipt, async (r) => {
  if (r?.has_file) {
    await loadFilePreview(r.id)
  }
}, { immediate: true })

async function loadFilePreview(id: string) {
  isLoadingFile.value = true
  try {
    const blob = await downloadFile(id)
    if (fileUrl.value) {
      URL.revokeObjectURL(fileUrl.value)
    }
    fileUrl.value = URL.createObjectURL(blob)
  }
  catch {
    toast.add({ title: 'Fehler beim Laden der Datei', color: 'error', icon: 'i-lucide-circle-x' })
  }
  finally {
    isLoadingFile.value = false
  }
}

async function handleDownload() {
  if (!receipt.value)
    return
  try {
    const blob = await downloadFile(receipt.value.id)
    downloadBlob(blob, receipt.value.file_original_name || `beleg-${receipt.value.receipt_number}.pdf`)
  }
  catch {
    toast.add({ title: 'Fehler beim Download', color: 'error', icon: 'i-lucide-circle-x' })
  }
}

// Tag management
async function addTag() {
  if (!receipt.value || !newTagInput.value.trim())
    return

  isAddingTag.value = true
  try {
    await $fetch(`/api/v1/receipts/${receipt.value.id}/tags?tag_name=${encodeURIComponent(newTagInput.value.trim())}`, {
      method: 'POST',
    })
    newTagInput.value = ''
    toast.add({ title: 'Tag hinzugefügt', color: 'success', icon: 'i-lucide-check' })
    refresh()
  }
  catch {
    toast.add({ title: 'Fehler beim Hinzufügen', color: 'error', icon: 'i-lucide-circle-x' })
  }
  finally {
    isAddingTag.value = false
  }
}

async function removeTag(tagId: string) {
  if (!receipt.value)
    return
  try {
    await $fetch(`/api/v1/receipts/${receipt.value.id}/tags/${tagId}`, {
      method: 'DELETE',
    })
    toast.add({ title: 'Tag entfernt', color: 'success', icon: 'i-lucide-check' })
    refresh()
  }
  catch {
    toast.add({ title: 'Fehler beim Entfernen', color: 'error', icon: 'i-lucide-circle-x' })
  }
}

// Available tags (not yet assigned to this receipt)
const availableTags = computed(() => {
  if (!allTags.value || !receipt.value)
    return []
  const assignedIds = new Set(receipt.value.tags.map(t => t.id))
  return allTags.value.filter(t => !assignedIds.has(t.id))
})

// Navigation
function goBack() {
  router.push('/receipts')
}

function handleEdit() {
  router.push(`/receipts/new?edit=${receiptId.value}`)
}

const isReverting = ref(false)

async function handleRevertToDraft() {
  isReverting.value = true
  try {
    await $fetch(`/api/v1/receipts/${receiptId.value}/revert-to-draft`, { method: 'POST' })
    toast.add({ title: 'Beleg in Entwurf zurückgesetzt', color: 'success', icon: 'i-lucide-check' })
    router.push(`/receipts/new?edit=${receiptId.value}`)
  }
  catch {
    toast.add({ title: 'Fehler beim Zurücksetzen', color: 'error', icon: 'i-lucide-circle-x' })
  }
  finally {
    isReverting.value = false
  }
}

const isDeleteOpen = ref(false)
const isDeleting = ref(false)

async function confirmDelete() {
  isDeleting.value = true
  try {
    await deleteReceipt(receiptId.value)
    toast.add({ title: 'Beleg gelöscht', color: 'success', icon: 'i-lucide-check' })
    router.push('/receipts')
  }
  catch {
    toast.add({ title: 'Fehler beim Löschen', color: 'error', icon: 'i-lucide-circle-x' })
  }
  finally {
    isDeleting.value = false
  }
}

// Format helpers
const { formatCurrency, formatDate, formatDateTime, receiptTypeLabel, receiptTypeColor } = useFormatters()

function formatDateOrDash(dateStr: string | null): string {
  return dateStr ? formatDate(dateStr) : '—'
}

// Compute totals from line items (using rc_tax_rate from SiteSettings)
const receiptLineItems = computed(() => receipt.value?.line_items ?? [])
const linkedTransactions = computed(() => receipt.value?.linked_transactions ?? [])
const { totalNetto, taxBreakdown, totalBrutto } = useReceiptTotals(receiptLineItems, rcTaxRate)

// Tax rule display
function taxRuleLabel(rule: string): string {
  const labels: Record<string, string> = {
    tax_included: 'USt ausgewiesen',
    tax_excluded: 'USt nicht ausgewiesen',
    no_tax: 'Keine USt',
    reverse_charge: 'Reverse Charge',
  }
  return labels[rule] || rule
}

// File upload + extraction for draft receipts (triggered by ReceiptDocumentViewer)
async function handleFileSelected(file: File) {
  if (!receipt.value)
    return

  try {
    await uploadFile(receipt.value.id, file)
    toast.add({ title: 'Datei hochgeladen', color: 'success', icon: 'i-lucide-check' })

    const result = await extractFromFile(file)
    if (result) {
      await applyExtractionToReceipt(receipt.value.id, result)
    }

    refresh()
  }
  catch {
    toast.add({ title: 'Fehler beim Hochladen', color: 'error', icon: 'i-lucide-circle-x' })
  }
}

async function applyExtractionToReceipt(receiptId: string, result: ExtractionResult) {
  // Build PATCH payload with only fields that are currently empty on the receipt
  const updates: Record<string, unknown> = {}
  const r = receipt.value!

  if (!r.receipt_number && result.receipt_number)
    updates.receipt_number = result.receipt_number
  if (!r.counterparty && result.counterparty)
    updates.counterparty = result.counterparty
  if (!r.due_date && result.due_date)
    updates.due_date = result.due_date
  if (!r.delivery_period && result.billing_period)
    updates.delivery_period = result.billing_period
  if (result.date && r.date !== result.date)
    updates.date = result.date
  if (result.delivery_date)
    updates.delivery_date = result.delivery_date

  updates.extraction_source = result.source

  if (Object.keys(updates).length > 1) {
    await $fetch(`/api/v1/receipts/${receiptId}`, {
      method: 'PATCH',
      body: updates,
    })
    toast.add({ title: 'Daten aus Dokument übernommen', color: 'success', icon: 'i-lucide-sparkles' })
  }
}

// Cleanup
onUnmounted(() => {
  if (fileUrl.value) {
    URL.revokeObjectURL(fileUrl.value)
  }
})
</script>

<template>
  <div class="flex-1 min-w-0">
    <PageHeader :title="receipt?.receipt_number || 'Beleg'" back-to="/receipts">
      <template v-if="receipt">
        <UBadge
          :color="receiptTypeColor(receipt.type)"
          variant="solid"
          size="lg"
        >
          {{ receiptTypeLabel(receipt.type) }}
        </UBadge>
        <UBadge
          v-if="receipt.status === 'draft'"
          color="neutral"
          variant="solid"
          size="lg"
        >
          Entwurf
        </UBadge>
        <UBadge
          :color="receipt.payment_status === 'paid' ? 'success' : 'warning'"
          variant="solid"
          size="lg"
        >
          {{ receipt.payment_status === 'paid' ? 'Bezahlt' : 'Unbezahlt' }}
        </UBadge>
        <UBadge
          v-if="receipt.is_locked"
          color="neutral"
          variant="solid"
          size="lg"
        >
          <UIcon name="i-lucide-lock" class="size-3 mr-1" />
          Festgeschrieben
        </UBadge>
      </template>
    </PageHeader>
    <!-- Loading state -->
    <div v-if="fetchStatus === 'pending'" class="flex items-center justify-center py-16">
      <UIcon name="i-lucide-loader-2" class="size-8 animate-spin text-primary" />
    </div>

    <!-- Receipt not found -->
    <div v-else-if="!receipt" class="flex flex-col items-center justify-center py-16">
      <UIcon name="i-lucide-file-x" class="size-12 text-stone-400" />
      <p class="mt-4 text-stone-500">
        Beleg nicht gefunden
      </p>
      <UButton
        class="mt-4"
        color="primary"
        variant="outline"
        @click="goBack"
      >
        Zurück zur Übersicht
      </UButton>
    </div>

    <!-- Receipt content -->
    <div v-else class="p-6">
      <div class="grid gap-6 lg:grid-cols-2">
        <!-- Left: Document viewer -->
        <ReceiptDocumentViewer
          :file-url="fileUrl"
          :mime-type="receipt.file_mime_type"
          :file-name="receipt.file_original_name"
          :loading="isLoadingFile"
          :can-upload="canUploadFile"
          can-download
          @file-select="handleFileSelected"
          @download="handleDownload"
        />

        <!-- Right: Metadata + Positions -->
        <div class="relative space-y-6">
          <!-- Extraction overlay -->
          <div v-if="extracting" class="absolute inset-0 z-10 flex items-center justify-center rounded-lg bg-white/80 dark:bg-stone-900/80">
            <div class="flex flex-col items-center gap-3">
              <UIcon name="i-lucide-loader-2" class="size-8 animate-spin text-primary" />
              <p class="text-sm font-medium text-stone-600 dark:text-stone-400">
                Daten werden erkannt...
              </p>
            </div>
          </div>

          <!-- Extraction error -->
          <div v-if="extractionError" class="flex items-center gap-3 rounded-lg border border-red-200 bg-red-50 p-3 dark:border-red-800 dark:bg-red-950/30">
            <UIcon name="i-lucide-circle-x" class="size-5 text-red-500 shrink-0" />
            <p class="flex-1 text-sm text-red-700 dark:text-red-300">
              {{ extractionError }}
            </p>
          </div>

          <!-- Payment link section -->
          <div v-if="linkedTransactions.length > 0" class="rounded-lg bg-emerald-50 p-4 dark:bg-emerald-950/30">
            <!-- Single transaction: show details -->
            <div v-if="linkedTransactions.length === 1 && linkedTransactions[0]" class="flex items-start gap-3">
              <UIcon name="i-lucide-check-circle" class="size-5 text-emerald-600 shrink-0 mt-0.5" />
              <div class="flex-1">
                <p class="text-sm font-medium text-emerald-800 dark:text-emerald-200">
                  Bezahlt am {{ formatDate(linkedTransactions[0].date) }}
                </p>
                <p class="text-sm text-emerald-700 dark:text-emerald-300">
                  {{ formatCurrency(linkedTransactions[0].amount) }} · {{ linkedTransactions[0].source_config_name ?? 'Bank' }}
                </p>
                <p class="text-xs text-emerald-600 dark:text-emerald-400 mt-1">
                  {{ linkedTransactions[0].counterparty }}
                </p>
              </div>
              <UButton
                v-if="!receipt.is_locked"
                icon="i-lucide-unlink"
                color="neutral"
                variant="ghost"
                size="xs"
                :loading="isUnlinking"
                title="Verknüpfung aufheben"
                @click="handleUnlink"
              />
            </div>
            <!-- Multiple transactions (Sammelbeleg): show summary -->
            <div v-else class="flex items-start gap-3">
              <UIcon name="i-lucide-check-circle" class="size-5 text-emerald-600 shrink-0 mt-0.5" />
              <div class="flex-1">
                <p class="text-sm font-medium text-emerald-800 dark:text-emerald-200">
                  {{ linkedTransactions.length }} Zahlungen verknüpft
                </p>
                <p class="text-sm text-emerald-700 dark:text-emerald-300">
                  {{ formatCurrency(linkedTransactions.reduce((sum: number, t) => sum + Number(t.amount), 0)) }} gesamt · {{ linkedTransactions[0]?.source_config_name ?? 'Bank' }}
                </p>
              </div>
              <UButton
                v-if="!receipt.is_locked"
                icon="i-lucide-unlink"
                color="neutral"
                variant="ghost"
                size="xs"
                :loading="isUnlinking"
                title="Alle Verknüpfungen aufheben"
                @click="handleUnlink"
              />
            </div>
          </div>
          <div v-else-if="!receipt.is_locked" class="flex items-center gap-3">
            <UDropdownMenu
              :items="[
                { label: 'Einzelne Zahlung', icon: 'i-lucide-link', onSelect: () => { linkingMode = 'find-transaction'; isLinkingModalOpen = true } },
                { label: 'Sammelbeleg (M:N)', icon: 'i-lucide-link-2', onSelect: () => { linkingMode = 'bulk'; isLinkingModalOpen = true } },
              ]"
            >
              <UButton
                icon="i-lucide-link"
                color="primary"
                variant="outline"
                size="md"
                trailing-icon="i-lucide-chevron-down"
              >
                Zahlung zuordnen
              </UButton>
            </UDropdownMenu>
          </div>

          <!-- Metadata section -->
          <div class="space-y-4">
            <div class="grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
              <div>
                <span class="text-stone-500">Belegdatum</span>
                <p class="font-medium">
                  {{ formatDate(receipt.date) }}
                </p>
              </div>
              <div>
                <span class="text-stone-500">Fälligkeit</span>
                <p class="font-medium">
                  {{ formatDateOrDash(receipt.due_date) }}
                </p>
              </div>
              <div>
                <span class="text-stone-500">Bezahldatum</span>
                <p class="font-medium">
                  {{ formatDateOrDash(receipt.payment_date) }}
                </p>
              </div>
              <div>
                <span class="text-stone-500">Lieferant</span>
                <p class="font-medium">
                  {{ receipt.counterparty }}
                </p>
              </div>
              <div>
                <span class="text-stone-500">Lieferdatum</span>
                <p class="font-medium">
                  {{ receipt.delivery_period || formatDate(receipt.date) }}
                </p>
              </div>
              <div>
                <span class="text-stone-500">Belegnummer</span>
                <p class="font-medium font-tabular">
                  {{ receipt.receipt_number }}
                </p>
              </div>
              <div v-if="receipt.is_locked">
                <span class="text-stone-500">Festgeschrieben</span>
                <p class="font-medium">
                  {{ formatDateTime(receipt.locked_at!) }}
                </p>
              </div>
            </div>

            <!-- Tags (hidden for now) -->
            <div v-if="false" class="space-y-2">
              <span class="text-sm text-stone-500">Tags</span>
              <div class="flex flex-wrap items-center gap-2">
                <UBadge
                  v-for="tag in receipt?.tags"
                  :key="tag.id"
                  color="neutral"
                  variant="soft"
                  class="group"
                >
                  {{ tag.name }}
                  <UButton
                    icon="i-lucide-x"
                    color="neutral"
                    variant="link"
                    size="xs"
                    class="ml-1 opacity-60 hover:opacity-100"
                    @click="removeTag(tag.id)"
                  />
                </UBadge>

                <!-- Add tag input -->
                <div class="flex items-center gap-1">
                  <UInput
                    v-model="newTagInput"
                    placeholder="Tag hinzufügen"
                    size="xs"
                    class="w-28"
                    :list="availableTags.length > 0 ? 'available-tags' : undefined"
                    @keydown.enter="addTag"
                  />
                  <datalist v-if="availableTags.length > 0" id="available-tags">
                    <option v-for="tag in availableTags" :key="tag.id" :value="tag.name" />
                  </datalist>
                  <UButton
                    icon="i-lucide-plus"
                    color="primary"
                    variant="ghost"
                    size="xs"
                    :loading="isAddingTag"
                    :disabled="!newTagInput.trim()"
                    @click="addTag"
                  />
                </div>
              </div>
            </div>
          </div>

          <!-- Positions section -->
          <div class="space-y-4">
            <h3 class="text-sm font-medium text-stone-700 dark:text-stone-300">
              Positionen
            </h3>

            <div class="space-y-3">
              <div
                v-for="(item, index) in receipt.line_items"
                :key="item.id"
                class="rounded-lg border border-stone-200 p-3 dark:border-stone-700"
              >
                <div class="flex items-start justify-between mb-2">
                  <span class="text-xs font-medium text-stone-500">Position {{ index + 1 }}</span>
                  <span
                    class="font-medium font-tabular"
                    :class="receipt.type === 'revenue' ? 'text-emerald-600' : 'text-red-500'"
                  >
                    {{ receipt.type === 'expense' ? '-' : '' }}{{ formatCurrency(item.amount) }}
                  </span>
                </div>

                <div class="space-y-1 text-sm">
                  <div v-if="item.description" class="text-stone-700 dark:text-stone-300">
                    {{ item.description }}
                  </div>
                  <div v-if="item.skr03_account_name" class="flex items-center gap-2 text-stone-500">
                    <UIcon name="i-lucide-folder" class="size-3.5" />
                    <span>{{ item.skr03_account_number }} - {{ item.skr03_account_name }}</span>
                  </div>
                  <div v-if="item.depreciation" class="flex items-center gap-2 text-stone-500">
                    <UIcon name="i-lucide-clock" class="size-3.5" />
                    <span>{{ item.depreciation }}</span>
                  </div>
                  <div class="flex items-center gap-2 text-stone-500">
                    <UIcon name="i-lucide-percent" class="size-3.5" />
                    <span>{{ taxRuleLabel(item.tax_rule) }}, {{ item.tax_rate }}%</span>
                  </div>
                </div>
              </div>
            </div>

            <!-- Summary -->
            <div class="rounded-lg bg-stone-100 p-4 dark:bg-stone-800">
              <div class="space-y-2 text-sm">
                <div class="flex justify-between">
                  <span class="text-stone-500">Gesamt Netto</span>
                  <span class="font-tabular">{{ formatCurrency(totalNetto.toFixed(2)) }}</span>
                </div>
                <div
                  v-for="tax in taxBreakdown"
                  :key="tax.rate"
                  class="flex justify-between text-stone-500"
                >
                  <span>USt {{ tax.rate }}</span>
                  <span class="font-tabular">{{ formatCurrency(tax.amount.toFixed(2)) }}</span>
                </div>
                <div class="flex justify-between border-t border-stone-200 pt-2 dark:border-stone-700">
                  <span class="font-medium">Gesamt Brutto</span>
                  <span
                    class="text-lg font-bold font-tabular"
                    :class="receipt.type === 'revenue' ? 'text-emerald-600' : 'text-red-500'"
                  >
                    {{ receipt.type === 'expense' ? '-' : '' }}{{ formatCurrency(totalBrutto.toFixed(2)) }}
                  </span>
                </div>
              </div>
            </div>
          </div>

          <!-- OMS info (if imported from an OMS provider) -->
          <div v-if="receipt.oms_order_id" class="space-y-3">
            <h3 class="text-sm font-medium text-stone-700 dark:text-stone-300">
              {{ omsProviderName }}
            </h3>
            <div class="rounded-lg border border-stone-200 p-3 text-sm dark:border-stone-700">
              <div class="grid grid-cols-3 gap-2">
                <div>
                  <span class="text-stone-500">Bestellnummer</span>
                  <p class="font-medium font-tabular">
                    {{ receipt.oms_invoice_number }}
                  </p>
                </div>
                <div>
                  <span class="text-stone-500">Shop</span>
                  <p class="font-medium">
                    {{ receipt.oms_shop_name }}
                  </p>
                </div>
                <div v-if="receipt.oms_platform">
                  <span class="text-stone-500">Plattform</span>
                  <p class="font-medium">
                    {{ receipt.oms_platform }}
                  </p>
                </div>
              </div>
            </div>
          </div>

          <!-- Timestamps -->
          <div class="text-xs text-stone-400 space-y-1">
            <p>Erstellt: {{ formatDateTime(receipt.created_at) }}</p>
            <p>Aktualisiert: {{ formatDateTime(receipt.updated_at) }}</p>
            <p v-if="receipt.extraction_source || extractionSource">
              Erkannt via {{ (receipt.extraction_source || extractionSource) === 'zugferd' ? 'ZUGFeRD' : (receipt.extraction_source || extractionSource) }}
            </p>
          </div>

          <!-- Actions for draft receipts -->
          <div v-if="receipt.status === 'draft'" class="flex items-center justify-between border-t border-stone-200 pt-6 dark:border-stone-700">
            <UButton
              icon="i-lucide-trash-2"
              variant="outline"
              color="error"
              @click="isDeleteOpen = true"
            >
              Löschen
            </UButton>
            <UButton
              icon="i-lucide-pencil"
              color="primary"
              @click="handleEdit"
            >
              Bearbeiten
            </UButton>
          </div>

          <!-- Actions for final (unlocked) receipts -->
          <div v-else-if="receipt.status === 'final' && !receipt.is_locked" class="flex items-center justify-end border-t border-stone-200 pt-6 dark:border-stone-700">
            <UButton
              icon="i-lucide-pencil"
              variant="outline"
              :loading="isReverting"
              @click="handleRevertToDraft"
            >
              Bearbeiten
            </UButton>
          </div>
        </div>
      </div>
    </div>

    <!-- Delete Confirmation Modal -->
    <ConfirmModal
      v-model:open="isDeleteOpen"
      title="Beleg löschen"
      :message="`Beleg ${receipt?.receipt_number} wirklich löschen? Diese Aktion kann nicht rückgängig gemacht werden.`"
      confirm-label="Löschen"
      confirm-color="error"
      :loading="isDeleting"
      @confirm="confirmDelete"
    />

    <!-- Linking Modal -->
    <LinkingModal
      v-if="receipt"
      :mode="linkingMode"
      :receipt-id="receipt.id"
      :open="isLinkingModalOpen"
      @update:open="isLinkingModalOpen = $event"
      @linked="handleLinked"
    />
  </div>
</template>
