<script setup lang="ts">
import type { TransactionFilters } from '~/composables/useTransactions'
import type { OmsMatchSuggestion, PaginatedResponse, TransactionResponse, TransferSuggestion } from '~/types/api'

definePageMeta({
  middleware: ['auth'],
})

const router = useRouter()

// Dynamic source tabs from API
const { data: allSources } = useSources()
const sourceTabs = computed(() => {
  const tabs = [{ label: 'Alle', value: 'all' }]
  if (allSources.value) {
    for (const source of allSources.value) {
      tabs.push({ label: source.name, value: source.id })
    }
  }
  return tabs
})

// URL-synced filters (centralized)
const { filters, activeFilterCount, resetFilters, createDebouncedModel } = useUrlFilters({
  source_config_id: { default: 'all', queryKey: 'source_config_id', excludeFromCount: true },
  status: { default: 'all', queryKey: 'status' },
  date_from: { default: undefined, queryKey: 'date_from' },
  date_to: { default: undefined, queryKey: 'date_to' },
  search: { default: undefined, queryKey: 'search' },
  search_field: { default: undefined, queryKey: 'search_field', excludeFromCount: true },
  page: { default: 1, queryKey: 'page', excludeFromCount: true },
  page_size: { default: 25, queryKey: 'page_size', excludeFromCount: true },
})

const searchInput = createDebouncedModel('search')

// Toggle filter bar visibility
const { visible: showFilters, toggle: toggleFilters } = useFilterVisibility()

// Bridge: useTransactions expects Ref<TransactionFilters>
const transactionFilters = computed(() => ({
  source_config_id: filters.value.source_config_id === 'all' ? undefined : filters.value.source_config_id as string | undefined,
  status: filters.value.status as string,
  date_from: filters.value.date_from as string | undefined,
  date_to: filters.value.date_to as string | undefined,
  search: filters.value.search as string | undefined,
  search_field: filters.value.search_field as string | undefined,
  page: filters.value.page as number,
  page_size: filters.value.page_size as number,
}))

const { data: transactions, refresh, status: fetchStatus } = useTransactions(transactionFilters as unknown as Ref<TransactionFilters>)
const { setPrivate, remove, getTransferSuggestions, linkTransfer, unlinkTransfer, autoLinkReceipts } = useTransactionMutations()
const { linkTransaction, unlinkTransaction } = useOmsMutations()
const { hasAnyProvider, primaryProvider } = useOmsProviders()

const omsProviderName = computed(() => primaryProvider.value?.display_name ?? 'Warenwirtschaft')

const toast = useToast()

// Auto-link receipts (scoped to active page filters)
const isAutoLinking = ref(false)
async function handleAutoLink() {
  isAutoLinking.value = true
  try {
    const result = await autoLinkReceipts({
      date_from: transactionFilters.value.date_from,
      date_to: transactionFilters.value.date_to,
      source_config_id: transactionFilters.value.source_config_id,
    })
    const summary = [
      `${result.linked} zugeordnet`,
      result.already_linked > 0 ? `${result.already_linked} bereits verknüpft` : '',
      result.no_receipt > 0 ? `${result.no_receipt} ohne Beleg` : '',
      result.skipped_locked > 0 ? `${result.skipped_locked} gesperrt übersprungen` : '',
    ].filter(Boolean).join(' · ')
    toast.add({ title: summary, color: result.linked > 0 ? 'success' : 'neutral', icon: 'i-lucide-link' })
    refresh()
  }
  catch {
    toast.add({ title: 'Fehler bei der Belegzuordnung', color: 'error', icon: 'i-lucide-circle-x' })
  }
  finally {
    isAutoLinking.value = false
  }
}

// Delete modal
const isDeleteOpen = ref(false)
const transactionToDelete = ref<TransactionResponse | null>(null)
const { execute: confirmDelete, isLoading: isDeleting } = useAsyncAction(
  async () => {
    await remove(transactionToDelete.value!.id)
    isDeleteOpen.value = false
    transactionToDelete.value = null
    refresh()
  },
  { success: 'Buchung gelöscht', error: 'Fehler beim Löschen' },
)

// OMS order linking
const isOmsOpen = ref(false)
const omsTransaction = ref<TransactionResponse | null>(null)
const omsMatches = ref<OmsMatchSuggestion[]>([])
const omsLoading = ref(false)

// Receipt linking via LinkingModal
const isLinkingModalOpen = ref(false)
const linkingTransactionId = ref<string>()

const searchFieldOptions = [
  { label: 'Alle Spalten', value: '_all' },
  { label: 'Name', value: 'counterparty' },
  { label: 'Verwendungszweck', value: 'description' },
  { label: 'Betrag', value: 'amount' },
]

const statusOptions = [
  { label: 'Alle', value: 'all' },
  { label: 'Offen', value: 'open' },
  { label: 'Zugeordnet', value: 'assigned' },
  { label: 'Gebucht', value: 'booked' },
  { label: 'Automatisch', value: 'automatic' },
  { label: 'Privat', value: 'private' },
  { label: 'Geldbewegung', value: 'internal' },
]

// Transfer (Geldbewegung) modal
const isTransferOpen = ref(false)
const transferTransaction = ref<TransactionResponse | null>(null)
const transferSuggestions = ref<TransferSuggestion[]>([])
const transferLoading = ref(false)
const isTransferLinking = ref(false)
const transferSearchQuery = ref('')
const transferSearchResults = ref<TransactionResponse[]>([])
const transferSearchLoading = ref(false)

// Verknüpfungen modal (linked receipts)
const isLinkedReceiptsOpen = ref(false)
const linkedReceiptsTransaction = ref<TransactionResponse | null>(null)
const isUnlinkingReceipt = ref(false)

// --- Multi-select mode (Phase 5c: Weg 2) ---
// Map<id, absAmount> — tracks amounts across pages so the total stays correct
const selectedTransactionAmounts = ref<Map<string, number>>(new Map())
const isBulkLinkModalOpen = ref(false)

const selectedTransactionIds = computed({
  get: () => new Set(selectedTransactionAmounts.value.keys()),
  set: (newIds: Set<string>) => {
    const currentItems = transactions.value?.items ?? []
    const itemMap = new Map(currentItems.map(tx => [tx.id, Math.abs(Number.parseFloat(tx.amount))]))
    const newMap = new Map<string, number>()
    for (const id of newIds) {
      // Preserve existing amount or look up from current page
      newMap.set(id, selectedTransactionAmounts.value.get(id) ?? itemMap.get(id) ?? 0)
    }
    selectedTransactionAmounts.value = newMap
  },
})

const selectedCount = computed(() => selectedTransactionAmounts.value.size)

const selectedTransactionsTotal = computed(() => {
  let sum = 0
  for (const amount of selectedTransactionAmounts.value.values()) {
    sum += amount
  }
  return sum
})

function clearSelection() {
  selectedTransactionAmounts.value = new Map()
}

function openBulkLinkModal() {
  isBulkLinkModalOpen.value = true
}

function handleBulkLinked() {
  isBulkLinkModalOpen.value = false
  clearSelection()
  refresh()
}

// Toggle private
async function handleTogglePrivate(transaction: TransactionResponse) {
  try {
    await setPrivate(transaction.id, !transaction.is_private)
    toast.add({ title: transaction.is_private ? 'Als geschäftlich markiert' : 'Als privat markiert', color: 'success', icon: 'i-lucide-check' })
    refresh()
  }
  catch {
    toast.add({ title: 'Fehler beim Ändern', color: 'error', icon: 'i-lucide-circle-x' })
  }
}

// Delete transaction
function openDeleteConfirm(transaction: TransactionResponse) {
  transactionToDelete.value = transaction
  isDeleteOpen.value = true
}

// OMS order linking
async function openOmsModal(transaction: TransactionResponse) {
  omsTransaction.value = transaction
  omsMatches.value = []
  omsLoading.value = true
  isOmsOpen.value = true

  const { data } = await useFetch<OmsMatchSuggestion[]>(
    `/api/v1/oms/match/${transaction.id}`,
  )
  omsMatches.value = data.value || []
  omsLoading.value = false
}

async function handleLinkOms(match: OmsMatchSuggestion) {
  if (!omsTransaction.value)
    return
  try {
    await linkTransaction(omsTransaction.value.id, {
      oms_order_id: String(match.oms_order_id),
    })
    toast.add({ title: 'Bestellung verknüpft', color: 'success', icon: 'i-lucide-link' })
    isOmsOpen.value = false
    omsTransaction.value = null
    refresh()
  }
  catch {
    toast.add({ title: 'Fehler beim Verknüpfen', color: 'error', icon: 'i-lucide-circle-x' })
  }
}

async function handleUnlinkOms(transaction: TransactionResponse) {
  const { execute } = useAsyncAction(
    async () => {
      await unlinkTransaction(transaction.id)
      refresh()
    },
    { success: 'Verknüpfung aufgehoben', error: 'Fehler beim Aufheben' },
  )
  try {
    await execute()
  }
  catch { /* toast already shown */ }
}

// Receipt linking via LinkingModal
function openReceiptLinkModal(transaction: TransactionResponse) {
  linkingTransactionId.value = transaction.id
  isLinkingModalOpen.value = true
}

function handleLinkingLinked() {
  isLinkingModalOpen.value = false
  refresh()
}

const { formatCurrency, formatDate, amountColorClass, receiptTypeLabel, receiptTypeColor } = useFormatters()

// Navigation helpers

function navigateToReceipt(receiptId: string) {
  router.push(`/receipts/${receiptId}`)
}

function navigateToCreateReceipt(transactionId: string) {
  router.push(`/receipts/new?transaction=${transactionId}`)
}

// Linked receipts modal
function openLinkedReceiptsModal(transaction: TransactionResponse) {
  linkedReceiptsTransaction.value = transaction
  isLinkedReceiptsOpen.value = true
}

// Transfer (Geldbewegung) modal
async function openTransferModal(transaction: TransactionResponse) {
  transferTransaction.value = transaction
  transferSuggestions.value = []
  transferSearchQuery.value = ''
  transferSearchResults.value = []
  transferLoading.value = true
  isTransferOpen.value = true

  try {
    const suggestions = await getTransferSuggestions(transaction.id)
    transferSuggestions.value = suggestions
  }
  catch {
    toast.add({ title: 'Fehler beim Laden der Vorschläge', color: 'error', icon: 'i-lucide-circle-x' })
  }
  finally {
    transferLoading.value = false
  }
}

// Manual transfer search
async function handleTransferSearch() {
  if (!transferTransaction.value || !transferSearchQuery.value.trim())
    return
  transferSearchLoading.value = true
  try {
    const result = await $fetch<PaginatedResponse<TransactionResponse>>(
      `/api/v1/transactions?search=${encodeURIComponent(transferSearchQuery.value.trim())}&limit=10`,
    )
    // Exclude the current transaction from results
    transferSearchResults.value = (result.items || []).filter(
      t => t.id !== transferTransaction.value!.id && !t.is_internal_transfer,
    )
  }
  catch {
    toast.add({ title: 'Fehler bei der Suche', color: 'error', icon: 'i-lucide-circle-x' })
  }
  finally {
    transferSearchLoading.value = false
  }
}

async function handleLinkTransfer(targetId: string) {
  if (!transferTransaction.value)
    return
  isTransferLinking.value = true
  try {
    await linkTransfer(transferTransaction.value.id, targetId)
    toast.add({ title: 'Geldbewegung verknüpft', color: 'success', icon: 'i-lucide-arrow-right-left' })
    isTransferOpen.value = false
    transferTransaction.value = null
    refresh()
  }
  catch {
    toast.add({ title: 'Fehler beim Verknüpfen', color: 'error', icon: 'i-lucide-circle-x' })
  }
  finally {
    isTransferLinking.value = false
  }
}

async function handleUnlinkTransfer(transaction: TransactionResponse) {
  const { execute } = useAsyncAction(
    async () => {
      await unlinkTransfer(transaction.id)
      refresh()
    },
    { success: 'Geldbewegung aufgehoben', error: 'Fehler beim Aufheben' },
  )
  try {
    await execute()
  }
  catch { /* toast already shown */ }
}

// Unlink receipt
async function handleUnlinkReceipt(receiptId: string) {
  isUnlinkingReceipt.value = true
  try {
    await $fetch(`/api/v1/receipts/${receiptId}/unlink`, { method: 'POST' })
    toast.add({ title: 'Belegverknüpfung gelöst', color: 'success', icon: 'i-lucide-unlink' })
    isLinkedReceiptsOpen.value = false
    linkedReceiptsTransaction.value = null
    refresh()
  }
  catch {
    toast.add({ title: 'Fehler beim Lösen der Verknüpfung', color: 'error', icon: 'i-lucide-circle-x' })
  }
  finally {
    isUnlinkingReceipt.value = false
  }
}

// Dynamic row menu items
type DropdownMenuItem = { label: string, icon?: string, onSelect: () => void } | { type: 'separator' }

function getRowMenuItems(transaction: TransactionResponse): DropdownMenuItem[] {
  const items: DropdownMenuItem[] = []

  // Private toggle
  items.push({ label: transaction.is_private ? 'Als geschäftlich' : 'Als privat', icon: 'i-lucide-eye-off', onSelect: () => handleTogglePrivate(transaction) })

  // Geldbewegung: link or unlink
  if (transaction.is_internal_transfer) {
    items.push({ label: 'Geldbewegung aufheben', icon: 'i-lucide-unlink', onSelect: () => handleUnlinkTransfer(transaction) })
  }
  else {
    items.push({ label: 'Geldbewegung', icon: 'i-lucide-arrow-right-left', onSelect: () => openTransferModal(transaction) })
  }

  // OMS order: link or unlink (only when a provider is configured)
  if (hasAnyProvider.value) {
    if (transaction.oms_order_id) {
      items.push({ label: 'Bestellung trennen', icon: 'i-lucide-unlink', onSelect: () => handleUnlinkOms(transaction) })
    }
    else {
      items.push({ label: 'Bestellung verknüpfen', icon: 'i-lucide-link', onSelect: () => openOmsModal(transaction) })
    }
  }

  // Unlink receipts (only if linked)
  if (transaction.linked_receipts.length > 0) {
    items.push({ label: 'Belegverknüpfung lösen', icon: 'i-lucide-file-x', onSelect: () => openLinkedReceiptsModal(transaction) })
  }

  items.push({ type: 'separator' })
  items.push({ label: 'Löschen', icon: 'i-lucide-trash-2', onSelect: () => openDeleteConfirm(transaction) })

  return items
}
</script>

<template>
  <div class="flex-1 min-w-0">
    <PageHeader title="Buchungen">
      <span class="shrink-0 text-[13px] text-stone-500">
        <span class="font-tabular">{{ transactions?.total || 0 }}</span> Buchungen
      </span>
      <UButton
        :icon="showFilters ? 'i-lucide-filter-x' : 'i-lucide-filter'"
        color="neutral"
        variant="ghost"
        @click="toggleFilters()"
      >
        Filter
        <UBadge
          v-if="activeFilterCount > 0"
          color="primary"
          variant="solid"
          size="xs"
        >
          {{ activeFilterCount }}
        </UBadge>
      </UButton>
      <UButton
        icon="i-lucide-link"
        color="neutral"
        variant="subtle"
        :loading="isAutoLinking"
        @click="handleAutoLink()"
      >
        Belege zuordnen
      </UButton>
      <UButton
        to="/import"
        icon="i-lucide-upload"
        color="primary"
      >
        Importieren
      </UButton>
    </PageHeader>

    <div class="p-6 space-y-4">
      <!-- Source tabs -->
      <TabNav v-model="filters.source_config_id" :tabs="sourceTabs" />

      <!-- Collapsible filter bar -->
      <FilterToolbar v-show="showFilters">
        <div class="flex flex-col gap-1">
          <label class="text-xs font-medium text-stone-500 dark:text-stone-400">Suche in</label>
          <USelect
            :model-value="filters.search_field ?? '_all'"
            :items="searchFieldOptions"
            class="min-w-36"
            size="md"
            @update:model-value="(v: string) => filters.search_field = v === '_all' ? undefined : v"
          />
        </div>
        <div class="flex flex-col gap-1 flex-1 min-w-60">
          <label class="text-xs font-medium text-stone-500 dark:text-stone-400">&nbsp;</label>
          <UInput
            v-model="searchInput"
            placeholder="Suchbegriff eingeben..."
            icon="i-lucide-search"
            size="md"
          />
        </div>

        <div class="h-5 w-px bg-stone-200 dark:bg-stone-700" />

        <div class="flex flex-col gap-1">
          <label class="text-xs font-medium text-stone-500 dark:text-stone-400">Status</label>
          <USelect
            v-model="filters.status"
            :items="statusOptions"
            class="min-w-40"
            size="md"
          />
        </div>

        <div class="h-5 w-px bg-stone-200 dark:bg-stone-700" />

        <FilterDateRange
          v-model:start-date="filters.date_from"
          v-model:end-date="filters.date_to"
        />

        <UButton
          class="mt-5"
          variant="link"
          color="neutral"
          size="md"
          @click="resetFilters(['source_config_id', 'page_size'])"
        >
          Filter zurücksetzen
        </UButton>
      </FilterToolbar>

      <!-- Transactions Table -->
      <UCard :ui="{ body: 'p-0' }">
        <TransactionsTable
          v-model:page="filters.page"
          v-model:selected-ids="selectedTransactionIds"
          v-model:page-size="filters.page_size"
          :transactions="transactions?.items || []"
          :total="transactions?.total || 0"
          :loading="fetchStatus === 'pending'"
          :row-menu-items="getRowMenuItems"
          selectable
          @navigate-receipt="navigateToReceipt"
          @open-linked-receipts="openLinkedReceiptsModal"
          @create-receipt="navigateToCreateReceipt"
          @link-receipt="openReceiptLinkModal"
        />
      </UCard>
    </div>

    <!-- Bulk Actions Toolbar (sticky bottom, visible when selection exists) -->
    <Transition
      enter-active-class="transition-transform duration-200 ease-out"
      enter-from-class="translate-y-full"
      enter-to-class="translate-y-0"
      leave-active-class="transition-transform duration-150 ease-in"
      leave-from-class="translate-y-0"
      leave-to-class="translate-y-full"
    >
      <div
        v-if="selectedCount > 0"
        class="fixed bottom-0 left-0 right-0 z-50 border-t border-stone-200 bg-white/95 backdrop-blur-sm shadow-lg dark:border-stone-700 dark:bg-stone-900/95"
      >
        <div class="mx-auto max-w-7xl px-6 py-3">
          <div class="flex items-center justify-between gap-4">
            <!-- Selection info -->
            <div class="flex items-center gap-3">
              <UBadge color="primary" variant="solid" size="lg">
                {{ selectedCount }}
              </UBadge>
              <span class="text-sm text-stone-600 dark:text-stone-400">
                Transaktionen ausgewählt
              </span>
              <span class="text-stone-400">·</span>
              <span class="font-tabular text-sm font-medium text-stone-700 dark:text-stone-300">
                {{ formatCurrency(selectedTransactionsTotal) }}
              </span>
              <span
                v-if="selectedCount > 500"
                class="text-xs text-amber-600 dark:text-amber-400"
              >
                ⚠️ Große Auswahl
              </span>
            </div>

            <!-- Actions -->
            <div class="flex items-center gap-2">
              <UButton
                icon="i-lucide-link"
                color="primary"
                size="md"
                @click="openBulkLinkModal"
              >
                Beleg verknüpfen
              </UButton>
              <UButton
                icon="i-lucide-x"
                color="neutral"
                variant="ghost"
                size="md"
                @click="clearSelection"
              >
                Auswahl aufheben
              </UButton>
            </div>
          </div>
        </div>
      </div>
    </Transition>

    <!-- Bulk Link Modal (Transactions → Receipt) -->
    <TransactionsBulkLinkModal
      :open="isBulkLinkModalOpen"
      :selected-ids="selectedTransactionIds"
      :selected-total="selectedTransactionsTotal"
      @update:open="isBulkLinkModalOpen = $event"
      @linked="handleBulkLinked"
    />

    <!-- Delete Confirmation Modal -->
    <ConfirmModal
      v-model:open="isDeleteOpen"
      title="Buchung löschen"
      message="Buchung wirklich löschen? Diese Aktion kann nicht rückgängig gemacht werden."
      confirm-label="Löschen"
      :loading="isDeleting"
      @confirm="confirmDelete"
    />

    <!-- OMS Order Linking Modal -->
    <UModal v-model:open="isOmsOpen">
      <template #content>
        <UCard>
          <template #header>
            <h3 class="text-lg font-semibold">
              {{ omsProviderName }}-Bestellungen
            </h3>
          </template>

          <div v-if="omsTransaction" class="space-y-4">
            <!-- Transaction info -->
            <div class="rounded-lg bg-gray-50 p-4 dark:bg-gray-800">
              <p class="font-medium">
                {{ omsTransaction.counterparty }}
              </p>
              <p class="text-sm text-gray-500">
                {{ formatDate(omsTransaction.date) }} · {{ omsTransaction.description }}
              </p>
              <p
                class="mt-2 text-lg font-bold"
                :class="amountColorClass(omsTransaction.amount)"
              >
                {{ formatCurrency(omsTransaction.amount) }}
              </p>
            </div>

            <!-- Loading state -->
            <div v-if="omsLoading" class="flex items-center justify-center py-8">
              <UIcon name="i-lucide-loader-2" class="size-6 animate-spin text-primary" />
              <span class="ml-2 text-sm text-gray-500">Suche passende Bestellungen...</span>
            </div>

            <!-- Match suggestions -->
            <div v-else-if="omsMatches.length > 0" class="space-y-2">
              <p class="text-sm font-medium text-gray-700 dark:text-gray-300">
                {{ omsMatches.length }} passende Bestellung{{ omsMatches.length > 1 ? 'en' : '' }} gefunden:
              </p>

              <div
                v-for="match in omsMatches"
                :key="match.oms_order_id"
                class="flex items-center justify-between rounded-lg border border-default p-3 hover:bg-gray-50 dark:hover:bg-gray-800"
              >
                <div class="min-w-0 flex-1">
                  <div class="flex items-center gap-2">
                    <span class="font-tabular text-sm font-medium">#{{ match.order_number }}</span>
                    <UBadge
                      :color="match.confidence >= 0.8 ? 'success' : match.confidence >= 0.5 ? 'warning' : 'neutral'"
                      variant="soft"
                      size="xs"
                    >
                      {{ Math.round(match.confidence * 100) }}%
                    </UBadge>
                  </div>
                  <p class="text-sm text-gray-500">
                    {{ match.customer_name }} · {{ formatDate(match.order_date) }}
                    · {{ formatCurrency(match.order_amount) }}
                  </p>
                  <div class="mt-1 flex flex-wrap gap-1">
                    <UBadge
                      v-for="reason in match.match_reasons"
                      :key="reason"
                      color="neutral"
                      variant="subtle"
                      size="xs"
                    >
                      {{ reason }}
                    </UBadge>
                  </div>
                </div>

                <UButton
                  icon="i-lucide-link"
                  color="primary"
                  size="md"
                  class="ml-4 shrink-0"
                  @click="handleLinkOms(match)"
                >
                  Verknüpfen
                </UButton>
              </div>
            </div>

            <!-- No matches -->
            <div v-else class="py-8 text-center">
              <UIcon name="i-lucide-search-x" class="mx-auto size-8 text-gray-400" />
              <p class="mt-2 text-sm text-gray-500">
                Keine passenden {{ omsProviderName }}-Bestellungen gefunden.
              </p>
            </div>
          </div>

          <template #footer>
            <div class="flex justify-end">
              <UButton
                color="neutral"
                variant="ghost"
                @click="isOmsOpen = false"
              >
                Schließen
              </UButton>
            </div>
          </template>
        </UCard>
      </template>
    </UModal>

    <!-- Receipt Linking Modal -->
    <LinkingModal
      mode="find-receipt"
      :transaction-id="linkingTransactionId"
      :open="isLinkingModalOpen"
      @update:open="isLinkingModalOpen = $event"
      @linked="handleLinkingLinked"
    />

    <!-- Transfer (Geldbewegung) Modal -->
    <UModal v-model:open="isTransferOpen">
      <template #content>
        <UCard>
          <template #header>
            <h3 class="text-lg font-semibold">
              Geldbewegung verknüpfen
            </h3>
          </template>

          <div v-if="transferTransaction" class="space-y-4">
            <!-- Transaction info -->
            <div class="rounded-lg bg-gray-50 p-4 dark:bg-gray-800">
              <p class="font-medium">
                {{ transferTransaction.counterparty }}
              </p>
              <p class="text-sm text-gray-500">
                {{ formatDate(transferTransaction.date) }} · {{ transferTransaction.source_config_name ?? '–' }}
              </p>
              <p
                class="mt-2 text-lg font-bold"
                :class="amountColorClass(transferTransaction.amount)"
              >
                {{ formatCurrency(transferTransaction.amount) }}
              </p>
            </div>

            <!-- Loading state -->
            <div v-if="transferLoading" class="flex items-center justify-center py-8">
              <UIcon name="i-lucide-loader-2" class="size-6 animate-spin text-primary" />
              <span class="ml-2 text-sm text-gray-500">Suche Gegenbuchungen...</span>
            </div>

            <!-- Transfer suggestions -->
            <div v-else-if="transferSuggestions.length > 0" class="space-y-2">
              <p class="text-sm font-medium text-gray-700 dark:text-gray-300">
                {{ transferSuggestions.length }} passende Gegenbuchung{{ transferSuggestions.length > 1 ? 'en' : '' }}:
              </p>

              <div
                v-for="suggestion in transferSuggestions"
                :key="suggestion.id"
                class="flex items-center justify-between rounded-lg border border-default p-3 hover:bg-gray-50 dark:hover:bg-gray-800"
              >
                <div class="min-w-0 flex-1">
                  <div class="flex items-center gap-2">
                    <UBadge color="neutral" variant="soft" size="xs">
                      {{ suggestion.source_config_name ?? '–' }}
                    </UBadge>
                    <span class="font-tabular text-sm">
                      {{ formatDate(suggestion.date) }}
                    </span>
                  </div>
                  <p class="text-sm font-medium mt-1">
                    {{ suggestion.counterparty }}
                  </p>
                  <p class="text-xs text-gray-500 truncate">
                    {{ suggestion.description }}
                  </p>
                  <p
                    class="mt-1 font-tabular font-medium"
                    :class="amountColorClass(suggestion.amount)"
                  >
                    {{ formatCurrency(suggestion.amount) }}
                  </p>
                </div>

                <UButton
                  icon="i-lucide-arrow-right-left"
                  color="primary"
                  size="md"
                  class="ml-4 shrink-0"
                  :loading="isTransferLinking"
                  @click="handleLinkTransfer(suggestion.id)"
                >
                  Verknüpfen
                </UButton>
              </div>
            </div>

            <!-- No suggestions -->
            <div v-else class="py-8 text-center">
              <UIcon name="i-lucide-search-x" class="mx-auto size-8 text-gray-400" />
              <p class="mt-2 text-sm text-gray-500">
                Keine passenden Gegenbuchungen gefunden.
              </p>
              <p class="mt-1 text-xs text-gray-400">
                Gegenbuchungen müssen ähnlichen Betrag, anderes Konto und Datum ±5 Tage haben.
              </p>
            </div>

            <!-- Manual search section -->
            <div class="border-t border-default pt-4">
              <p class="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                Manuelle Suche
              </p>
              <div class="flex gap-2">
                <UInput
                  v-model="transferSearchQuery"
                  placeholder="Name oder Verwendungszweck..."
                  icon="i-lucide-search"
                  class="flex-1"
                  size="md"
                  @keydown.enter="handleTransferSearch"
                />
                <UButton
                  icon="i-lucide-search"
                  color="neutral"
                  size="md"
                  :loading="transferSearchLoading"
                  @click="handleTransferSearch"
                >
                  Suchen
                </UButton>
              </div>

              <!-- Search results -->
              <div v-if="transferSearchResults.length > 0" class="mt-3 space-y-2">
                <div
                  v-for="result in transferSearchResults"
                  :key="result.id"
                  class="flex items-center justify-between rounded-lg border border-default p-3 hover:bg-gray-50 dark:hover:bg-gray-800"
                >
                  <div class="min-w-0 flex-1">
                    <div class="flex items-center gap-2">
                      <UBadge color="neutral" variant="soft" size="xs">
                        {{ result.source_config_name ?? '–' }}
                      </UBadge>
                      <span class="font-tabular text-sm">
                        {{ formatDate(result.date) }}
                      </span>
                    </div>
                    <p class="text-sm font-medium mt-1">
                      {{ result.counterparty }}
                    </p>
                    <p class="text-xs text-gray-500 truncate">
                      {{ result.description }}
                    </p>
                    <p
                      class="mt-1 font-tabular font-medium"
                      :class="amountColorClass(result.amount)"
                    >
                      {{ formatCurrency(result.amount) }}
                    </p>
                  </div>

                  <UButton
                    icon="i-lucide-arrow-right-left"
                    color="primary"
                    size="md"
                    class="ml-4 shrink-0"
                    :loading="isTransferLinking"
                    @click="handleLinkTransfer(result.id)"
                  >
                    Verknüpfen
                  </UButton>
                </div>
              </div>

              <div v-else-if="transferSearchQuery && !transferSearchLoading && transferSearchResults.length === 0" class="mt-3 text-center py-4">
                <p class="text-sm text-gray-500">
                  Keine Ergebnisse für "{{ transferSearchQuery }}"
                </p>
              </div>
            </div>
          </div>

          <template #footer>
            <div class="flex justify-end">
              <UButton
                color="neutral"
                variant="ghost"
                @click="isTransferOpen = false"
              >
                Schließen
              </UButton>
            </div>
          </template>
        </UCard>
      </template>
    </UModal>

    <!-- Linked Receipts Modal -->
    <UModal v-model:open="isLinkedReceiptsOpen">
      <template #content>
        <UCard>
          <template #header>
            <h3 class="text-lg font-semibold">
              Verknüpfte Dokumente
            </h3>
          </template>

          <div v-if="linkedReceiptsTransaction" class="space-y-4">
            <!-- Transaction info -->
            <div class="rounded-lg bg-gray-50 p-4 dark:bg-gray-800">
              <p class="font-medium">
                {{ linkedReceiptsTransaction.counterparty }}
              </p>
              <p class="text-sm text-gray-500">
                {{ formatDate(linkedReceiptsTransaction.date) }}
              </p>
              <p
                class="mt-2 text-lg font-bold"
                :class="amountColorClass(linkedReceiptsTransaction.amount)"
              >
                {{ formatCurrency(linkedReceiptsTransaction.amount) }}
              </p>
            </div>

            <!-- Linked receipts list -->
            <div class="space-y-2">
              <div
                v-for="receipt in linkedReceiptsTransaction.linked_receipts"
                :key="receipt.id"
                class="flex items-center justify-between rounded-lg border border-default p-3"
              >
                <div class="flex items-center gap-3 min-w-0 flex-1">
                  <!-- File thumbnail indicator -->
                  <div
                    class="flex size-10 shrink-0 items-center justify-center rounded-lg"
                    :class="receipt.has_file ? 'bg-primary-50 dark:bg-primary-950' : 'bg-gray-100 dark:bg-gray-800'"
                  >
                    <UIcon
                      :name="receipt.has_file ? 'i-lucide-file-check' : 'i-lucide-file-x'"
                      class="size-5"
                      :class="receipt.has_file ? 'text-primary' : 'text-gray-400'"
                    />
                  </div>

                  <div class="min-w-0 flex-1">
                    <div class="flex items-center gap-2">
                      <span class="font-tabular text-sm font-medium">{{ receipt.receipt_number }}</span>
                      <UBadge
                        :color="receiptTypeColor(receipt.type)"
                        variant="soft"
                        size="xs"
                      >
                        {{ receiptTypeLabel(receipt.type) }}
                      </UBadge>
                    </div>
                    <p class="text-sm text-gray-500">
                      {{ receipt.counterparty }} · {{ formatDate(receipt.date) }}
                    </p>
                    <p
                      class="mt-1 font-tabular text-sm"
                      :class="receipt.type === 'revenue' ? 'text-emerald-600' : 'text-red-500'"
                    >
                      {{ formatCurrency(receipt.amount) }}
                    </p>
                  </div>
                </div>

                <div class="flex items-center gap-1 ml-4 shrink-0">
                  <UButton
                    icon="i-lucide-eye"
                    color="neutral"
                    variant="ghost"
                    size="xs"
                    title="Beleg anzeigen"
                    @click="navigateToReceipt(receipt.id)"
                  />
                  <UButton
                    icon="i-lucide-x"
                    color="error"
                    variant="ghost"
                    size="xs"
                    title="Verknüpfung lösen"
                    :loading="isUnlinkingReceipt"
                    @click="handleUnlinkReceipt(receipt.id)"
                  />
                </div>
              </div>
            </div>
          </div>

          <template #footer>
            <div class="flex justify-end">
              <UButton
                color="neutral"
                variant="ghost"
                @click="isLinkedReceiptsOpen = false"
              >
                Schließen
              </UButton>
            </div>
          </template>
        </UCard>
      </template>
    </UModal>
  </div>
</template>
