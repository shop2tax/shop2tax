<script setup lang="ts">
/**
 * TransactionsBulkLinkModal — Link selected transactions to a receipt.
 *
 * Two paths (tabs):
 * 1. Find matching receipt: POST /transactions/find-matching-receipts
 * 2. Create new receipt: Navigate to /receipts/new?bulk_transaction_ids=...
 */
import type { MatchingReceiptSummary } from '~/types/api'

const props = defineProps<{
  open: boolean
  selectedIds: Set<string>
  selectedTotal: number
}>()

const emit = defineEmits<{
  'update:open': [value: boolean]
  'linked': [receiptId: string]
}>()

const toast = useToast()
const router = useRouter()
const { formatCurrency, formatDate, receiptTypeLabel, receiptTypeColor } = useFormatters()
const { bulkLinkTransactions } = useLinkingMutations()

// --- Tab state ---
const activeTab = ref<'find' | 'create'>('find')

// --- Find matching receipts ---
const matchingReceipts = ref<MatchingReceiptSummary[]>([])
const isSearching = ref(false)
const searchPerformed = ref(false)
const selectedReceiptId = ref<string>()

// --- Linking state ---
const isLinking = ref(false)

// --- Computed ---
const selectedCount = computed(() => props.selectedIds.size)
const selectedIdsArray = computed(() => Array.from(props.selectedIds))

// --- Search for matching receipts ---
async function searchMatchingReceipts() {
  if (selectedIdsArray.value.length === 0)
    return

  isSearching.value = true
  searchPerformed.value = false
  matchingReceipts.value = []

  try {
    const response = await findMatchingReceipts(selectedIdsArray.value)
    matchingReceipts.value = response.matching_receipts
    searchPerformed.value = true
  }
  catch {
    toast.add({ title: 'Fehler beim Suchen', color: 'error', icon: 'i-lucide-circle-x' })
  }
  finally {
    isSearching.value = false
  }
}

// --- Link to existing receipt ---
async function handleLinkToReceipt(receiptId: string) {
  isLinking.value = true
  try {
    const response = await bulkLinkTransactions(receiptId, selectedIdsArray.value)
    const message = `${response.linked_count} Zahlungen mit Beleg verknüpft`
    toast.add({ title: message, color: 'success', icon: 'i-lucide-check' })
    emit('linked', receiptId)
    emit('update:open', false)
  }
  catch {
    toast.add({ title: 'Fehler beim Verknüpfen', color: 'error', icon: 'i-lucide-circle-x' })
  }
  finally {
    isLinking.value = false
  }
}

// --- Create new receipt with pre-filled data ---
function handleCreateReceipt() {
  const total = props.selectedTotal.toFixed(2)
  // For large selections, store IDs + total in sessionStorage to avoid URL length limits
  if (selectedIdsArray.value.length > 20) {
    const key = `bulk_transactions_${Date.now()}`
    sessionStorage.setItem(key, JSON.stringify({ ids: selectedIdsArray.value, total: props.selectedTotal }))
    router.push(`/receipts/new?bulk_storage_key=${key}`)
  }
  else {
    const idsParam = selectedIdsArray.value.join(',')
    router.push(`/receipts/new?bulk_transaction_ids=${idsParam}&bulk_total=${total}`)
  }
  emit('update:open', false)
}

// --- Reset on close ---
watch(() => props.open, (isOpen) => {
  if (isOpen) {
    activeTab.value = 'find'
    matchingReceipts.value = []
    searchPerformed.value = false
    selectedReceiptId.value = undefined
    // Auto-search when modal opens
    searchMatchingReceipts()
  }
})

// --- Helpers ---
function getMatchScoreColor(score: number): 'success' | 'warning' | 'neutral' {
  if (score >= 0.8)
    return 'success'
  if (score >= 0.5)
    return 'warning'
  return 'neutral'
}
</script>

<template>
  <UModal :open="open" @update:open="emit('update:open', $event)">
    <template #content>
      <UCard class="w-full max-w-2xl">
        <template #header>
          <div class="flex items-center justify-between">
            <h3 class="text-lg font-semibold">
              Transaktionen mit Beleg verknüpfen
            </h3>
            <UButton
              icon="i-lucide-x"
              color="neutral"
              variant="ghost"
              size="sm"
              @click="emit('update:open', false)"
            />
          </div>
        </template>

        <div class="space-y-4">
          <!-- Selection summary -->
          <div class="rounded-lg bg-stone-50 p-4 dark:bg-stone-800/50">
            <div class="flex items-center gap-3">
              <UIcon name="i-lucide-list-checks" class="size-5 text-stone-500 shrink-0" />
              <div class="flex-1">
                <p class="text-sm font-medium">
                  {{ selectedCount }} Transaktionen ausgewählt
                </p>
                <p class="text-sm text-stone-600 dark:text-stone-400">
                  Gesamtbetrag:
                  <span class="font-tabular font-medium">
                    {{ formatCurrency(selectedTotal) }}
                  </span>
                </p>
              </div>
            </div>
          </div>

          <!-- Tab navigation -->
          <TabNav
            v-model="activeTab"
            :tabs="[
              { label: 'Beleg suchen', value: 'find', icon: 'i-lucide-search' },
              { label: 'Neuen Beleg erstellen', value: 'create', icon: 'i-lucide-plus' },
            ]"
          />

          <!-- Tab: Find matching receipt -->
          <div v-if="activeTab === 'find'" class="space-y-3">
            <!-- Loading state -->
            <div v-if="isSearching" class="flex items-center justify-center py-8">
              <UIcon name="i-lucide-loader-2" class="size-5 animate-spin text-stone-400" />
              <span class="ml-2 text-sm text-stone-500">Suche passende Belege...</span>
            </div>

            <!-- Results -->
            <template v-else-if="searchPerformed">
              <div v-if="matchingReceipts.length > 0" class="max-h-64 overflow-y-auto space-y-2">
                <div
                  v-for="receipt in matchingReceipts"
                  :key="receipt.id"
                  class="flex items-center justify-between rounded-lg border border-stone-200 p-3 dark:border-stone-700 hover:border-primary-300 dark:hover:border-primary-600 transition-colors"
                >
                  <div class="flex-1 min-w-0">
                    <div class="flex items-center gap-2">
                      <span class="text-sm font-medium">{{ receipt.receipt_number }}</span>
                      <UBadge
                        :color="receiptTypeColor(receipt.type)"
                        variant="solid"
                        size="sm"
                      >
                        {{ receiptTypeLabel(receipt.type) }}
                      </UBadge>
                      <UBadge
                        v-if="receipt.match_score >= 0.5"
                        :color="getMatchScoreColor(receipt.match_score)"
                        variant="solid"
                        size="sm"
                      >
                        {{ Math.round(receipt.match_score * 100) }}%
                      </UBadge>
                      <UIcon
                        v-if="receipt.has_file"
                        name="i-lucide-paperclip"
                        class="size-3.5 text-stone-400"
                        title="Hat Datei"
                      />
                    </div>
                    <p class="text-xs text-stone-500 mt-0.5">
                      {{ receipt.counterparty }} · {{ formatDate(receipt.date) }} · {{ formatCurrency(receipt.amount) }}
                    </p>
                  </div>
                  <UButton
                    icon="i-lucide-link"
                    color="primary"
                    variant="ghost"
                    size="sm"
                    :loading="isLinking"
                    @click="handleLinkToReceipt(receipt.id)"
                  />
                </div>
              </div>

              <div v-else class="py-8 text-center">
                <UIcon name="i-lucide-search-x" class="mx-auto size-8 text-stone-400" />
                <p class="mt-2 text-sm text-stone-500">
                  Keine passenden Belege gefunden.
                </p>
                <p class="mt-1 text-xs text-stone-400">
                  Erstellen Sie einen neuen Beleg für diese Transaktionen.
                </p>
              </div>
            </template>

            <!-- Retry button -->
            <UButton
              v-if="searchPerformed && !isSearching"
              icon="i-lucide-refresh-cw"
              color="neutral"
              variant="ghost"
              size="sm"
              @click="searchMatchingReceipts"
            >
              Erneut suchen
            </UButton>
          </div>

          <!-- Tab: Create new receipt -->
          <div v-if="activeTab === 'create'" class="space-y-4">
            <div class="rounded-lg border border-dashed border-stone-300 p-6 dark:border-stone-600 text-center">
              <UIcon name="i-lucide-file-plus" class="mx-auto size-10 text-stone-400" />
              <p class="mt-3 text-sm font-medium text-stone-700 dark:text-stone-300">
                Neuen Sammelbeleg erstellen
              </p>
              <p class="mt-1 text-xs text-stone-500">
                Der Beleg wird mit {{ selectedCount }} Transaktionen vorausgefüllt.
              </p>
              <p class="mt-1 text-xs text-stone-500">
                Betrag: <span class="font-tabular font-medium">{{ formatCurrency(selectedTotal) }}</span>
              </p>
            </div>

            <UButton
              icon="i-lucide-plus"
              color="primary"
              size="md"
              block
              @click="handleCreateReceipt"
            >
              Beleg erstellen und verknüpfen
            </UButton>
          </div>
        </div>
      </UCard>
    </template>
  </UModal>
</template>
