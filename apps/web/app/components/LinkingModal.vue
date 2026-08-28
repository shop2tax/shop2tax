<script setup lang="ts">
import type { LinkingMode, ReceiptSuggestionFilters, TransactionSuggestionFilters } from '~/composables/useLinkingModal'
/**
 * LinkingModal — Reusable modal for receipt↔transaction linking.
 *
 * Three modes:
 * - find-transaction: From a receipt, find a matching transaction (or record manual payment)
 * - find-receipt: From a transaction, find a matching receipt
 * - bulk: From a receipt, find and bulk-link multiple transactions (Sammelbeleg)
 */
import type { TransactionSourceConfigResponse } from '~/types/api'

const props = defineProps<{
  mode: LinkingMode
  receiptId?: string
  transactionId?: string
  open: boolean
}>()

const emit = defineEmits<{
  'linked': []
  'update:open': [value: boolean]
}>()

const toast = useToast()
const router = useRouter()

// --- Mode-specific refs ---
const receiptIdRef = computed(() => (props.mode === 'find-transaction' || props.mode === 'bulk') ? props.receiptId : undefined)
const transactionIdRef = computed(() => props.mode === 'find-receipt' ? props.transactionId : undefined)
const bulkReceiptIdRef = computed(() => props.mode === 'bulk' ? props.receiptId : undefined)

// --- Filters ---
const transactionFilters = ref<TransactionSuggestionFilters>({})
const receiptFilters = ref<ReceiptSuggestionFilters>({})

// --- Data fetching ---
const { data: receipt, refresh: refreshReceipt } = useReceiptForLinking(receiptIdRef)
const { data: transaction, refresh: refreshTransaction } = useTransactionForLinking(transactionIdRef)
const { data: transactionSuggestions, status: transactionSuggestionsStatus, refresh: refreshTransactionSuggestions } = useTransactionSuggestions(receiptIdRef, transactionFilters)
const { data: receiptSuggestions, status: receiptSuggestionsStatus, refresh: refreshReceiptSuggestions } = useReceiptSuggestions(transactionIdRef, receiptFilters)
const { data: bulkSuggestions, status: bulkSuggestionsStatus, refresh: refreshBulkSuggestions } = useBulkSuggestions(bulkReceiptIdRef)
const bulkTransactionMap = computed(() => {
  const map = new Map<string, { description: string, date: string, amount: string, counterparty: string | null }>()
  if (!bulkSuggestions.value?.transactions)
    return map
  for (const tx of bulkSuggestions.value.transactions) {
    map.set(tx.id, tx)
  }
  return map
})
const { data: sources } = useSources()

// --- Mutations ---
const { linkReceiptToTransaction, recordPayment, linkTransactionToReceipt, bulkLinkTransactions } = useLinkingMutations()

// --- UI State ---
const isLinking = ref(false)
const showManualPayment = ref(false)

// --- Bulk Mode State ---
const selectedTransactionIds = ref<Set<string>>(new Set())
const expandedGroups = ref<Set<string>>(new Set())

// --- Manual payment form ---
const manualPaymentForm = ref({
  source_config_id: '',
  date: '',
  amount: '',
})

// Initialize manual payment form when receipt loads
watch(receipt, (value) => {
  if (value) {
    manualPaymentForm.value.date = value.date
    manualPaymentForm.value.amount = value.amount
  }
}, { immediate: true })

// --- Computed ---
const modalTitle = computed(() => {
  if (props.mode === 'bulk')
    return 'Sammelbeleg verknüpfen'
  return props.mode === 'find-transaction' ? 'Zahlung zuordnen' : 'Beleg zuordnen'
})

const isLoading = computed(() => {
  if (props.mode === 'bulk')
    return bulkSuggestionsStatus.value === 'pending'
  return props.mode === 'find-transaction'
    ? transactionSuggestionsStatus.value === 'pending'
    : receiptSuggestionsStatus.value === 'pending'
})

// --- Bulk Mode Computed ---
const selectedTotal = computed(() => {
  if (!bulkSuggestions.value)
    return 0
  let sum = 0
  for (const tx of bulkSuggestions.value.transactions) {
    if (selectedTransactionIds.value.has(tx.id)) {
      sum += Math.abs(Number.parseFloat(tx.amount))
    }
  }
  return sum
})

const bulkAmountDifference = computed(() => {
  if (!receipt.value)
    return 0
  const receiptAmount = Math.abs(Number.parseFloat(receipt.value.amount))
  return receiptAmount - selectedTotal.value
})

const bulkAmountMatchLevel = computed<'match' | 'close' | 'far'>(() => {
  const diff = Math.abs(bulkAmountDifference.value)
  if (diff <= 0.02)
    return 'match'
  if (diff <= 1.0)
    return 'close'
  return 'far'
})

const selectedCount = computed(() => selectedTransactionIds.value.size)

const sourceOptions = computed(() => {
  if (!sources.value)
    return []
  return [
    { value: undefined, label: 'Alle' },
    ...sources.value.map((source: TransactionSourceConfigResponse) => ({
      value: source.id,
      label: source.name,
    })),
  ]
})

const receiptTypeOptions = [
  { value: '', label: 'Alle Typen' },
  { value: 'revenue', label: 'Einnahme' },
  { value: 'expense', label: 'Ausgabe' },
]

// --- Handlers ---
async function handleLinkTransaction(transactionId: string) {
  if (!props.receiptId)
    return
  isLinking.value = true
  try {
    await linkReceiptToTransaction(props.receiptId, transactionId)
    toast.add({ title: 'Zahlung verknüpft', color: 'success', icon: 'i-lucide-check' })
    emit('linked')
    emit('update:open', false)
  }
  catch {
    toast.add({ title: 'Fehler beim Verknüpfen', color: 'error', icon: 'i-lucide-circle-x' })
  }
  finally {
    isLinking.value = false
  }
}

async function handleLinkReceipt(receiptId: string) {
  if (!props.transactionId)
    return
  isLinking.value = true
  try {
    await linkTransactionToReceipt(receiptId, props.transactionId)
    toast.add({ title: 'Beleg verknüpft', color: 'success', icon: 'i-lucide-check' })
    emit('linked')
    emit('update:open', false)
  }
  catch {
    toast.add({ title: 'Fehler beim Verknüpfen', color: 'error', icon: 'i-lucide-circle-x' })
  }
  finally {
    isLinking.value = false
  }
}

async function handleRecordPayment() {
  if (!props.receiptId || !manualPaymentForm.value.source_config_id || !manualPaymentForm.value.date)
    return

  isLinking.value = true
  try {
    await recordPayment(props.receiptId, {
      source_config_id: manualPaymentForm.value.source_config_id,
      date: manualPaymentForm.value.date,
      amount: manualPaymentForm.value.amount || undefined,
    })
    toast.add({ title: 'Zahlung erfasst und verknüpft', color: 'success', icon: 'i-lucide-check' })
    emit('linked')
    emit('update:open', false)
  }
  catch {
    toast.add({ title: 'Fehler beim Erfassen der Zahlung', color: 'error', icon: 'i-lucide-circle-x' })
  }
  finally {
    isLinking.value = false
  }
}

function handleCreateReceipt() {
  if (!transaction.value)
    return

  // Navigate to receipt creation with pre-filled data
  const params = new URLSearchParams()
  params.set('transaction_id', transaction.value.id)
  params.set('amount', transaction.value.amount)
  params.set('date', transaction.value.date)
  params.set('counterparty', transaction.value.counterparty)

  router.push(`/receipts/new?${params.toString()}`)
  emit('update:open', false)
}

// --- Bulk Mode Handlers ---
function toggleTransaction(transactionId: string) {
  const newSet = new Set(selectedTransactionIds.value)
  if (newSet.has(transactionId)) {
    newSet.delete(transactionId)
  }
  else {
    newSet.add(transactionId)
  }
  selectedTransactionIds.value = newSet
}

function selectGroup(group: { transaction_ids: string[] }) {
  const newSet = new Set(selectedTransactionIds.value)
  for (const id of group.transaction_ids) {
    newSet.add(id)
  }
  selectedTransactionIds.value = newSet
}

function deselectGroup(group: { transaction_ids: string[] }) {
  const newSet = new Set(selectedTransactionIds.value)
  for (const id of group.transaction_ids) {
    newSet.delete(id)
  }
  selectedTransactionIds.value = newSet
}

function toggleGroup(groupType: string) {
  const newSet = new Set(expandedGroups.value)
  if (newSet.has(groupType)) {
    newSet.delete(groupType)
  }
  else {
    newSet.add(groupType)
  }
  expandedGroups.value = newSet
}

function selectAll() {
  if (!bulkSuggestions.value)
    return
  selectedTransactionIds.value = new Set(bulkSuggestions.value.transactions.map(tx => tx.id))
}

function deselectAll() {
  selectedTransactionIds.value = new Set()
}

function isGroupFullySelected(group: { transaction_ids: string[] }): boolean {
  return group.transaction_ids.every(id => selectedTransactionIds.value.has(id))
}

async function handleBulkLink() {
  if (!props.receiptId || selectedTransactionIds.value.size === 0)
    return

  isLinking.value = true
  try {
    const response = await bulkLinkTransactions(props.receiptId, Array.from(selectedTransactionIds.value))
    const message = `${response.linked_count} Zahlungen verknüpft`
    toast.add({ title: message, color: 'success', icon: 'i-lucide-check' })
    emit('linked')
    emit('update:open', false)
  }
  catch {
    toast.add({ title: 'Fehler beim Verknüpfen', color: 'error', icon: 'i-lucide-circle-x' })
  }
  finally {
    isLinking.value = false
  }
}

// --- Formatters ---
const { formatCurrency, formatDate, receiptTypeLabel, receiptTypeColor } = useFormatters()

function formatConfidence(confidence: number): string {
  return `${Math.round(confidence * 100)}%`
}

// --- Refresh on open ---
watch(() => props.open, (isOpen) => {
  if (isOpen) {
    showManualPayment.value = false
    transactionFilters.value = {}
    receiptFilters.value = {}
    manualPaymentForm.value = { source_config_id: '', date: '', amount: '' }
    selectedTransactionIds.value = new Set()
    expandedGroups.value = new Set()

    if (props.mode === 'find-transaction' && props.receiptId) {
      refreshReceipt()
      refreshTransactionSuggestions()
    }
    else if (props.mode === 'find-receipt' && props.transactionId) {
      refreshTransaction()
      refreshReceiptSuggestions()
    }
    else if (props.mode === 'bulk' && props.receiptId) {
      refreshReceipt()
      refreshBulkSuggestions()
    }
  }
})
</script>

<template>
  <UModal :open="open" @update:open="emit('update:open', $event)">
    <template #content>
      <UCard class="w-full max-w-2xl">
        <template #header>
          <div class="flex items-center justify-between">
            <h3 class="text-lg font-semibold">
              {{ modalTitle }}
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
          <!-- Mode: find-transaction (from receipt) -->
          <template v-if="mode === 'find-transaction' && receipt">
            <!-- Receipt info card -->
            <div class="rounded-lg bg-stone-50 p-4 dark:bg-stone-800/50">
              <div class="flex items-start gap-3">
                <UIcon name="i-lucide-file-text" class="size-5 text-stone-500 shrink-0 mt-0.5" />
                <div class="flex-1 min-w-0">
                  <p class="text-sm font-medium">
                    Beleg {{ receipt.receipt_number }}
                  </p>
                  <p class="text-sm text-stone-600 dark:text-stone-400">
                    {{ formatCurrency(receipt.amount) }} · {{ formatDate(receipt.date) }}
                  </p>
                  <p class="text-xs text-stone-500 mt-0.5 truncate">
                    {{ receipt.counterparty }}
                  </p>
                </div>
                <UBadge
                  :color="receiptTypeColor(receipt.type)"
                  variant="solid"
                  size="sm"
                >
                  {{ receiptTypeLabel(receipt.type) }}
                </UBadge>
              </div>
            </div>

            <!-- Filters -->
            <div class="flex gap-2">
              <USelect
                v-model="transactionFilters.source_config_id"
                :items="sourceOptions"
                placeholder="Alle Konten"
                size="md"
                class="min-w-40"
                value-key="value"
              />
              <UInput
                v-model="transactionFilters.search"
                placeholder="Suchen..."
                size="md"
                icon="i-lucide-search"
                class="flex-1"
              />
            </div>

            <!-- Transaction suggestions -->
            <div class="max-h-64 overflow-y-auto space-y-2">
              <div v-if="isLoading" class="flex items-center justify-center py-8">
                <UIcon name="i-lucide-loader-2" class="size-5 animate-spin text-stone-400" />
              </div>
              <template v-else-if="transactionSuggestions?.length">
                <div
                  v-for="suggestion in transactionSuggestions"
                  :key="suggestion.id"
                  class="flex items-center justify-between rounded-lg border border-stone-200 p-3 dark:border-stone-700 hover:border-primary-300 dark:hover:border-primary-600 transition-colors"
                >
                  <div class="flex-1 min-w-0">
                    <div class="flex items-center gap-2">
                      <p class="text-sm font-medium truncate">
                        {{ suggestion.counterparty }}
                      </p>
                      <UBadge
                        v-if="suggestion.confidence >= 0.8"
                        color="success"
                        variant="solid"
                        size="sm"
                      >
                        {{ formatConfidence(suggestion.confidence) }}
                      </UBadge>
                    </div>
                    <p class="text-xs text-stone-500 mt-0.5">
                      {{ formatDate(suggestion.date) }} · {{ formatCurrency(suggestion.amount) }}
                    </p>
                    <p v-if="suggestion.reasons.length" class="text-xs text-stone-400 mt-0.5">
                      {{ suggestion.reasons.join(' · ') }}
                    </p>
                  </div>
                  <UButton
                    icon="i-lucide-link"
                    color="primary"
                    variant="ghost"
                    size="sm"
                    :loading="isLinking"
                    @click="handleLinkTransaction(suggestion.id)"
                  />
                </div>
              </template>
              <p v-else class="py-8 text-center text-sm text-stone-400">
                Keine passenden Zahlungen gefunden
              </p>
            </div>

            <!-- Divider + Manual payment -->
            <div class="relative">
              <div class="absolute inset-0 flex items-center">
                <span class="w-full border-t border-stone-200 dark:border-stone-700" />
              </div>
              <div class="relative flex justify-center">
                <span class="bg-white px-2 text-xs text-stone-400 dark:bg-stone-900">oder</span>
              </div>
            </div>

            <UButton
              v-if="!showManualPayment"
              icon="i-lucide-plus"
              color="neutral"
              variant="outline"
              size="md"
              block
              @click="showManualPayment = true"
            >
              Zahlung manuell erfassen
            </UButton>

            <!-- Manual payment form -->
            <div v-if="showManualPayment" class="space-y-3 rounded-lg border border-stone-200 p-4 dark:border-stone-700">
              <p class="text-sm font-medium">
                Zahlung manuell erfassen
              </p>
              <USelect
                v-model="manualPaymentForm.source_config_id"
                :items="sourceOptions"
                placeholder="Konto wählen *"
                size="md"
                required
                value-key="value"
              />
              <UInput
                v-model="manualPaymentForm.date"
                type="date"
                size="md"
                required
              />
              <UInput
                v-model="manualPaymentForm.amount"
                type="number"
                step="0.01"
                placeholder="Betrag (optional, Standard: Belegbetrag)"
                size="md"
              />
              <div class="flex justify-end gap-2">
                <UButton
                  color="neutral"
                  variant="ghost"
                  size="md"
                  @click="showManualPayment = false"
                >
                  Abbrechen
                </UButton>
                <UButton
                  color="primary"
                  size="md"
                  :loading="isLinking"
                  :disabled="!manualPaymentForm.source_config_id || !manualPaymentForm.date"
                  @click="handleRecordPayment"
                >
                  Zahlung erfassen
                </UButton>
              </div>
            </div>
          </template>

          <!-- Mode: find-receipt (from transaction) -->
          <template v-else-if="mode === 'find-receipt' && transaction">
            <!-- Transaction info card -->
            <div class="rounded-lg bg-stone-50 p-4 dark:bg-stone-800/50">
              <div class="flex items-start gap-3">
                <UIcon name="i-lucide-arrow-left-right" class="size-5 text-stone-500 shrink-0 mt-0.5" />
                <div class="flex-1 min-w-0">
                  <p class="text-sm font-medium truncate">
                    {{ transaction.counterparty }}
                  </p>
                  <p class="text-sm text-stone-600 dark:text-stone-400">
                    {{ formatCurrency(transaction.amount) }} · {{ formatDate(transaction.date) }}
                  </p>
                  <p v-if="transaction.source_config_name" class="text-xs text-stone-500 mt-0.5">
                    {{ transaction.source_config_name }}
                  </p>
                </div>
                <UBadge
                  :color="Number.parseFloat(transaction.amount) > 0 ? 'success' : 'error'"
                  variant="solid"
                  size="sm"
                >
                  {{ Number.parseFloat(transaction.amount) > 0 ? 'Eingang' : 'Ausgang' }}
                </UBadge>
              </div>
            </div>

            <!-- Filters -->
            <div class="flex gap-2">
              <USelect
                v-model="receiptFilters.receipt_type"
                :items="receiptTypeOptions"
                placeholder="Alle Typen"
                size="md"
                class="min-w-40"
                value-key="value"
              />
              <UInput
                v-model="receiptFilters.search"
                placeholder="Suchen..."
                size="md"
                icon="i-lucide-search"
                class="flex-1"
              />
            </div>

            <!-- Receipt suggestions -->
            <div class="max-h-64 overflow-y-auto space-y-2">
              <div v-if="isLoading" class="flex items-center justify-center py-8">
                <UIcon name="i-lucide-loader-2" class="size-5 animate-spin text-stone-400" />
              </div>
              <template v-else-if="receiptSuggestions?.length">
                <div
                  v-for="suggestion in receiptSuggestions"
                  :key="suggestion.id"
                  class="flex items-center justify-between rounded-lg border border-stone-200 p-3 dark:border-stone-700 hover:border-primary-300 dark:hover:border-primary-600 transition-colors"
                >
                  <div class="flex-1 min-w-0">
                    <div class="flex items-center gap-2">
                      <p class="text-sm font-medium truncate">
                        {{ suggestion.receipt_number }}
                      </p>
                      <UBadge
                        :color="receiptTypeColor(suggestion.type)"
                        variant="solid"
                        size="sm"
                      >
                        {{ receiptTypeLabel(suggestion.type) }}
                      </UBadge>
                      <UBadge
                        v-if="suggestion.confidence >= 0.8"
                        color="primary"
                        variant="solid"
                        size="sm"
                      >
                        {{ formatConfidence(suggestion.confidence) }}
                      </UBadge>
                    </div>
                    <p class="text-xs text-stone-500 mt-0.5">
                      {{ suggestion.counterparty }} · {{ formatDate(suggestion.date) }} · {{ formatCurrency(suggestion.amount) }}
                    </p>
                    <p v-if="suggestion.reasons.length" class="text-xs text-stone-400 mt-0.5">
                      {{ suggestion.reasons.join(' · ') }}
                    </p>
                  </div>
                  <UButton
                    icon="i-lucide-link"
                    color="primary"
                    variant="ghost"
                    size="sm"
                    :loading="isLinking"
                    @click="handleLinkReceipt(suggestion.id)"
                  />
                </div>
              </template>
              <p v-else class="py-8 text-center text-sm text-stone-400">
                Keine passenden Belege gefunden
              </p>
            </div>

            <!-- Divider + Create receipt -->
            <div class="relative">
              <div class="absolute inset-0 flex items-center">
                <span class="w-full border-t border-stone-200 dark:border-stone-700" />
              </div>
              <div class="relative flex justify-center">
                <span class="bg-white px-2 text-xs text-stone-400 dark:bg-stone-900">oder</span>
              </div>
            </div>

            <UButton
              icon="i-lucide-plus"
              color="neutral"
              variant="outline"
              size="md"
              block
              @click="handleCreateReceipt"
            >
              Neuen Beleg anlegen
            </UButton>
          </template>

          <!-- Mode: bulk (Sammelbeleg) -->
          <template v-else-if="mode === 'bulk' && receipt">
            <!-- Receipt info card -->
            <div class="rounded-lg bg-stone-50 p-4 dark:bg-stone-800/50">
              <div class="flex items-start gap-3">
                <UIcon name="i-lucide-file-stack" class="size-5 text-stone-500 shrink-0 mt-0.5" />
                <div class="flex-1 min-w-0">
                  <div class="flex items-center gap-2">
                    <p class="text-sm font-medium">
                      Sammelbeleg {{ receipt.receipt_number }}
                    </p>
                    <UBadge color="primary" variant="soft" size="sm">
                      M:N
                    </UBadge>
                  </div>
                  <p class="text-sm text-stone-600 dark:text-stone-400">
                    {{ formatCurrency(receipt.amount) }} · {{ formatDate(receipt.date) }}
                  </p>
                  <p class="text-xs text-stone-500 mt-0.5 truncate">
                    {{ receipt.counterparty }}
                  </p>
                </div>
                <UBadge
                  :color="receiptTypeColor(receipt.type)"
                  variant="solid"
                  size="sm"
                >
                  {{ receiptTypeLabel(receipt.type) }}
                </UBadge>
              </div>
            </div>

            <!-- Selection summary -->
            <div class="flex items-center justify-between rounded-lg border border-dashed border-stone-300 p-3 dark:border-stone-600">
              <div class="flex items-center gap-3">
                <span class="text-sm font-medium">Auswahl:</span>
                <span class="font-tabular text-sm">{{ selectedCount }} Zahlungen</span>
                <span class="text-stone-400">·</span>
                <span
                  class="font-tabular text-sm font-medium"
                  :class="{
                    'text-emerald-600': bulkAmountMatchLevel === 'match',
                    'text-amber-600': bulkAmountMatchLevel === 'close',
                    'text-red-600': bulkAmountMatchLevel === 'far',
                  }"
                >
                  {{ formatCurrency(selectedTotal) }}
                </span>
              </div>
              <div class="flex items-center gap-1">
                <UButton
                  size="xs"
                  color="neutral"
                  variant="ghost"
                  :disabled="selectedCount === 0"
                  @click="deselectAll"
                >
                  Keine
                </UButton>
                <UButton
                  size="xs"
                  color="neutral"
                  variant="ghost"
                  @click="selectAll"
                >
                  Alle
                </UButton>
              </div>
            </div>

            <!-- Amount match indicator -->
            <div
              v-if="selectedCount > 0"
              class="flex items-center gap-2 rounded-lg px-3 py-2"
              :class="{
                'bg-emerald-50 dark:bg-emerald-950/30': bulkAmountMatchLevel === 'match',
                'bg-amber-50 dark:bg-amber-950/30': bulkAmountMatchLevel === 'close',
                'bg-red-50 dark:bg-red-950/30': bulkAmountMatchLevel === 'far',
              }"
            >
              <UIcon
                :name="bulkAmountMatchLevel === 'match' ? 'i-lucide-check-circle' : bulkAmountMatchLevel === 'close' ? 'i-lucide-alert-circle' : 'i-lucide-circle-x'"
                class="size-4"
                :class="{
                  'text-emerald-600': bulkAmountMatchLevel === 'match',
                  'text-amber-600': bulkAmountMatchLevel === 'close',
                  'text-red-600': bulkAmountMatchLevel === 'far',
                }"
              />
              <span
                class="text-sm"
                :class="{
                  'text-emerald-700 dark:text-emerald-400': bulkAmountMatchLevel === 'match',
                  'text-amber-700 dark:text-amber-400': bulkAmountMatchLevel === 'close',
                  'text-red-700 dark:text-red-400': bulkAmountMatchLevel === 'far',
                }"
              >
                <template v-if="bulkAmountMatchLevel === 'match'">
                  Betrag stimmt überein
                </template>
                <template v-else>
                  Differenz: {{ formatCurrency(bulkAmountDifference) }}
                </template>
              </span>
            </div>

            <!-- Grouped transaction list -->
            <div class="max-h-80 overflow-y-auto space-y-3">
              <div v-if="isLoading" class="flex items-center justify-center py-8">
                <UIcon name="i-lucide-loader-2" class="size-5 animate-spin text-stone-400" />
              </div>
              <template v-else-if="bulkSuggestions?.groups.length">
                <div
                  v-for="group in bulkSuggestions.groups"
                  :key="group.type"
                  class="rounded-lg border border-stone-200 dark:border-stone-700 overflow-hidden"
                >
                  <!-- Group header -->
                  <div
                    class="flex items-center justify-between px-3 py-2 bg-stone-100 dark:bg-stone-800 cursor-pointer"
                    @click="toggleGroup(group.type)"
                  >
                    <div class="flex items-center gap-2">
                      <UIcon
                        :name="expandedGroups.has(group.type) ? 'i-lucide-chevron-down' : 'i-lucide-chevron-right'"
                        class="size-4 text-stone-500"
                      />
                      <span class="text-sm font-medium">{{ group.type }}</span>
                      <UBadge color="neutral" variant="soft" size="xs">
                        {{ group.count }}
                      </UBadge>
                    </div>
                    <div class="flex items-center gap-2">
                      <span class="font-tabular text-sm text-stone-600 dark:text-stone-400">
                        {{ formatCurrency(group.total) }}
                      </span>
                      <UButton
                        v-if="isGroupFullySelected(group)"
                        size="xs"
                        color="neutral"
                        variant="ghost"
                        icon="i-lucide-x"
                        @click.stop="deselectGroup(group)"
                      />
                      <UButton
                        v-else
                        size="xs"
                        color="primary"
                        variant="ghost"
                        icon="i-lucide-check"
                        @click.stop="selectGroup(group)"
                      />
                    </div>
                  </div>

                  <!-- Group transactions (expanded) -->
                  <div v-if="expandedGroups.has(group.type)" class="divide-y divide-stone-100 dark:divide-stone-700">
                    <div
                      v-for="txId in group.transaction_ids"
                      :key="txId"
                      class="flex items-center justify-between px-3 py-2 hover:bg-stone-50 dark:hover:bg-stone-800/50 cursor-pointer"
                      @click="toggleTransaction(txId)"
                    >
                      <div class="flex items-center gap-2 flex-1 min-w-0">
                        <UCheckbox
                          :model-value="selectedTransactionIds.has(txId)"
                          @click.stop
                          @update:model-value="toggleTransaction(txId)"
                        />
                        <div class="min-w-0 flex-1">
                          <p class="text-sm truncate">
                            <span v-if="bulkTransactionMap.get(txId)?.counterparty" class="font-medium">{{ bulkTransactionMap.get(txId)?.counterparty }}</span>
                            <span v-if="bulkTransactionMap.get(txId)?.counterparty && bulkTransactionMap.get(txId)?.description" class="text-stone-400"> · </span>
                            <span>{{ bulkTransactionMap.get(txId)?.description ?? '–' }}</span>
                          </p>
                          <p class="text-xs text-stone-500">
                            {{ formatDate(bulkTransactionMap.get(txId)?.date ?? '') }}
                          </p>
                        </div>
                      </div>
                      <span class="font-tabular text-sm text-stone-600 dark:text-stone-400 shrink-0">
                        {{ formatCurrency(bulkTransactionMap.get(txId)?.amount ?? '0') }}
                      </span>
                    </div>
                  </div>
                </div>
              </template>
              <p v-else class="py-8 text-center text-sm text-stone-400">
                Keine passenden Zahlungen gefunden
              </p>
            </div>

            <!-- Action button -->
            <UButton
              color="primary"
              size="md"
              block
              :loading="isLinking"
              :disabled="selectedCount === 0"
              @click="handleBulkLink"
            >
              <UIcon name="i-lucide-link" class="size-4 mr-1" />
              {{ selectedCount }} Zahlungen verknüpfen
            </UButton>
          </template>

          <!-- Loading state when no data yet -->
          <div v-else class="flex items-center justify-center py-12">
            <UIcon name="i-lucide-loader-2" class="size-6 animate-spin text-stone-400" />
          </div>
        </div>
      </UCard>
    </template>
  </UModal>
</template>
