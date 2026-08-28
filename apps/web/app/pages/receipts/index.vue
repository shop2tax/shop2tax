<script setup lang="ts">
import type { ReceiptFilters } from '~/composables/useReceipts'
import type { ReceiptResponse } from '~/types/api'

definePageMeta({
  middleware: ['auth'],
})

const toast = useToast()
const router = useRouter()

// Status tabs
const statusTabs = [
  { label: 'Alle', value: 'all' },
  { label: 'Entwurf', value: 'draft' },
  { label: 'Offen', value: 'open' },
  { label: 'Fällig', value: 'overdue' },
  { label: 'Festgeschrieben', value: 'finalized' },
]

// URL-synced filters (centralized)
const { filters, activeFilterCount, resetFilters, createDebouncedModel } = useUrlFilters({
  tab: { default: 'all', queryKey: 'tab', excludeFromCount: true },
  type: { default: undefined, queryKey: 'type' },
  start_date: { default: undefined, queryKey: 'start_date' },
  end_date: { default: undefined, queryKey: 'end_date' },
  payment_status: { default: undefined, queryKey: 'payment_status' },
  search: { default: undefined, queryKey: 'search' },
  page: { default: 1, queryKey: 'page', excludeFromCount: true },
  page_size: { default: 25, queryKey: 'page_size', excludeFromCount: true },
})

const searchInput = createDebouncedModel('search')

// Filter visibility toggle
const { visible: showFilters, toggle: toggleFilters } = useFilterVisibility()

// Bridge: useReceipts expects Ref<ReceiptFilters> — derive from URL filters
const receiptFilters = computed(() => ({
  type: filters.value.type as string | undefined,
  start_date: filters.value.start_date as string | undefined,
  end_date: filters.value.end_date as string | undefined,
  payment_status: filters.value.payment_status as string | undefined,
  tab: filters.value.tab === 'all' ? undefined : filters.value.tab as string | undefined,
  search: filters.value.search as string | undefined,
  page: filters.value.page as number,
  page_size: filters.value.page_size as number,
}))

const { data: receipts, refresh, status } = useReceipts(receiptFilters as unknown as Ref<ReceiptFilters>)
const {
  deleteReceipt,
  unlinkFromPayment,
  downloadFile,
} = useReceiptMutations()

// Loading states
const isDeleting = ref(false)

// Filter options (with "Alle" for easy clearing — '_all' sentinel maps to undefined)
const FILTER_ALL = '_all'

const typeOptions = [
  { label: 'Alle Typen', value: FILTER_ALL },
  { label: 'Einnahme', value: 'revenue' },
  { label: 'Ausgabe', value: 'expense' },
]

const paymentStatusOptions = [
  { label: 'Alle', value: FILTER_ALL },
  { label: 'Offen', value: 'unpaid' },
  { label: 'Bezahlt', value: 'paid' },
]

function fromSelect(value: string): string | undefined {
  return value === FILTER_ALL ? undefined : value
}

function toSelect(value: unknown): string {
  return (value as string) ?? FILTER_ALL
}

// LinkingModal state
const isLinkingModalOpen = ref(false)
const linkingReceiptId = ref<string>()
const linkingMode = ref<'find-transaction' | 'bulk'>('find-transaction')

function openLinkingModal(receipt: ReceiptResponse, mode: 'find-transaction' | 'bulk' = 'find-transaction') {
  linkingReceiptId.value = receipt.id
  linkingMode.value = mode
  isLinkingModalOpen.value = true
}

function handleLinked() {
  isLinkingModalOpen.value = false
  refresh()
}

// Delete receipt
const isDeleteOpen = ref(false)
const receiptToDelete = ref<ReceiptResponse | null>(null)

function openDeleteConfirm(receipt: ReceiptResponse) {
  if (receipt.linked_transaction_id) {
    toast.add({ title: 'Verknüpfter Beleg kann nicht gelöscht werden', color: 'warning', icon: 'i-lucide-alert-circle' })
    return
  }
  if (receipt.is_locked) {
    toast.add({ title: 'Festgeschriebener Beleg kann nicht gelöscht werden', color: 'warning', icon: 'i-lucide-lock' })
    return
  }
  receiptToDelete.value = receipt
  isDeleteOpen.value = true
}

async function confirmDelete() {
  if (!receiptToDelete.value)
    return
  isDeleting.value = true
  try {
    await deleteReceipt(receiptToDelete.value.id)
    toast.add({ title: 'Beleg gelöscht', color: 'success', icon: 'i-lucide-check' })
    isDeleteOpen.value = false
    receiptToDelete.value = null
    refresh()
  }
  catch {
    toast.add({ title: 'Fehler beim Löschen', color: 'error', icon: 'i-lucide-circle-x' })
  }
  finally {
    isDeleting.value = false
  }
}

async function handleUnlink(receipt: ReceiptResponse) {
  try {
    await unlinkFromPayment(receipt.id)
    toast.add({ title: 'Verknüpfung aufgehoben', color: 'success', icon: 'i-lucide-unlink' })
    refresh()
  }
  catch {
    toast.add({ title: 'Fehler beim Aufheben', color: 'error', icon: 'i-lucide-circle-x' })
  }
}

// File download
async function handleDownloadFile(receipt: ReceiptResponse) {
  try {
    const blob = await downloadFile(receipt.id)
    downloadBlob(blob, receipt.file_original_name || 'beleg.pdf')
  }
  catch {
    toast.add({ title: 'Fehler beim Download', color: 'error', icon: 'i-lucide-circle-x' })
  }
}

// Dropdown menu items generator
function getDropdownItems(receipt: ReceiptResponse) {
  const items: Array<{ label: string, icon: string, onSelect: () => void } | { type: 'separator' }> = []

  // View details
  items.push({ label: 'Details anzeigen', icon: 'i-lucide-eye', onSelect: () => router.push(`/receipts/${receipt.id}`) })

  if (receipt.has_file) {
    items.push({ label: 'Datei herunterladen', icon: 'i-lucide-download', onSelect: () => handleDownloadFile(receipt) })
  }

  if (receipt.linked_transaction_id) {
    items.push({ label: 'Verknüpfung aufheben', icon: 'i-lucide-unlink', onSelect: () => handleUnlink(receipt) })
  }
  else {
    items.push({ label: 'Einzelne Zahlung verknüpfen', icon: 'i-lucide-link', onSelect: () => openLinkingModal(receipt, 'find-transaction') })
    items.push({ label: 'Sammelbeleg (M:N)', icon: 'i-lucide-link-2', onSelect: () => openLinkingModal(receipt, 'bulk') })
  }

  if (!receipt.linked_transaction_id && !receipt.is_locked) {
    items.push({ type: 'separator' })
    items.push({ label: 'Löschen', icon: 'i-lucide-trash-2', onSelect: () => openDeleteConfirm(receipt) })
  }

  return items
}

// Reset uses useUrlFilters.resetFilters — preserves tab
function handleResetFilters() {
  resetFilters(['tab', 'page_size'])
}

// Helper: Check if receipt is overdue
function isOverdue(receipt: ReceiptResponse): boolean {
  if (!receipt.due_date || receipt.linked_transaction_id)
    return false
  return new Date(receipt.due_date) < new Date()
}

// Helper: Get first SKR03 account name from line items
function getCategoryDisplay(receipt: ReceiptResponse): { name: string | null, extra: number } {
  const lineItems = receipt.line_items || []
  if (lineItems.length === 0)
    return { name: null, extra: 0 }
  const firstName = lineItems[0]?.skr03_account_name || null
  return { name: firstName, extra: Math.max(0, lineItems.length - 1) }
}

// Shared formatters
const { formatCurrency, formatDate, receiptTypeLabel, receiptTypeColor } = useFormatters()
</script>

<template>
  <div class="flex-1 min-w-0">
    <PageHeader title="Belege">
      <span class="shrink-0 text-[13px] text-stone-500">
        <span class="font-tabular">{{ receipts?.total || 0 }}</span> Belege
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
        icon="i-lucide-plus"
        color="primary"
        to="/receipts/new"
      >
        Beleg erstellen
      </UButton>
    </PageHeader>

    <div class="p-6 space-y-4">
      <!-- Tab navigation -->
      <TabNav v-model="filters.tab" :tabs="statusTabs" />

      <!-- Collapsible filter toolbar -->
      <FilterToolbar v-show="showFilters">
        <div class="flex flex-col gap-1 flex-1 min-w-80">
          <label class="text-xs font-medium text-stone-500 dark:text-stone-400">Suche</label>
          <UInput
            v-model="searchInput"
            placeholder="Belegnr., Name, Beschreibung..."
            icon="i-lucide-search"
            size="md"
          />
        </div>

        <div class="h-5 w-px bg-stone-200 dark:bg-stone-700" />

        <div class="flex flex-col gap-1">
          <label class="text-xs font-medium text-stone-500 dark:text-stone-400">Typ</label>
          <USelect
            :model-value="toSelect(filters.type)"
            :items="typeOptions"
            class="min-w-40"
            size="md"
            @update:model-value="(v: string) => filters.type = fromSelect(v)"
          />
        </div>

        <div class="flex flex-col gap-1">
          <label class="text-xs font-medium text-stone-500 dark:text-stone-400">Zahlung</label>
          <USelect
            :model-value="toSelect(filters.payment_status)"
            :items="paymentStatusOptions"
            class="min-w-40"
            size="md"
            @update:model-value="(v: string) => filters.payment_status = fromSelect(v)"
          />
        </div>

        <div class="h-5 w-px bg-stone-200 dark:bg-stone-700" />

        <FilterDateRange
          v-model:start-date="filters.start_date"
          v-model:end-date="filters.end_date"
        />

        <UButton
          class="mt-5"
          variant="link"
          color="neutral"
          size="md"
          @click="handleResetFilters"
        >
          Filter zurücksetzen
        </UButton>
      </FilterToolbar>

      <!-- Receipts Table -->
      <UCard :ui="{ body: 'p-0' }">
        <UTable
          :data="receipts?.receipts || []"
          :loading="status === 'pending'"
          :columns="[
            { accessorKey: 'date', header: 'Datum' },
            { accessorKey: 'receipt_number', header: 'Belegnummer' },
            { accessorKey: 'counterparty', header: 'Name' },
            { accessorKey: 'category', header: 'Kategorie' },
            { accessorKey: 'amount', header: 'Betrag' },
            { accessorKey: 'open_amount', header: 'Offen' },
            { accessorKey: 'due_date', header: 'Fälligkeit' },
            { accessorKey: 'type', header: 'Typ' },
            { accessorKey: 'status', header: 'Status' },
            { accessorKey: 'actions', header: '' },
          ]"
          :empty-state="{ icon: 'i-lucide-file-text', label: 'Keine Belege gefunden' }"
        >
          <template #date-cell="{ row }">
            {{ formatDate(row.original.date) }}
          </template>

          <template #receipt_number-cell="{ row }">
            <div class="flex items-center gap-2">
              <NuxtLink
                :to="`/receipts/${row.original.id}`"
                class="font-tabular text-sm text-primary hover:underline"
              >
                {{ row.original.receipt_number }}
              </NuxtLink>
              <UIcon
                v-if="row.original.has_file"
                name="i-lucide-paperclip"
                class="size-3.5 text-stone-400"
                title="Datei angehängt"
              />
            </div>
          </template>

          <template #counterparty-cell="{ row }">
            <div class="max-w-48">
              <div class="truncate font-medium">
                {{ row.original.counterparty }}
              </div>
              <div v-if="row.original.oms_shop_name" class="truncate text-xs text-stone-400">
                {{ row.original.oms_shop_name }}
                <span v-if="row.original.oms_platform">· {{ row.original.oms_platform }}</span>
              </div>
            </div>
          </template>

          <template #category-cell="{ row }">
            <template v-if="getCategoryDisplay(row.original).name">
              <div class="flex items-center gap-1">
                <span class="text-sm text-stone-600 dark:text-stone-400 truncate max-w-32">
                  {{ getCategoryDisplay(row.original).name }}
                </span>
                <UBadge
                  v-if="getCategoryDisplay(row.original).extra > 0"
                  color="neutral"
                  variant="subtle"
                  size="xs"
                >
                  +{{ getCategoryDisplay(row.original).extra }}
                </UBadge>
              </div>
            </template>
            <span v-else class="text-stone-400">–</span>
          </template>

          <template #amount-cell="{ row }">
            <span
              class="font-tabular"
              :class="row.original.type === 'revenue' ? 'text-emerald-600' : 'text-red-500'"
            >
              {{ row.original.type === 'expense' ? '-' : '' }}{{ formatCurrency(row.original.amount) }}
            </span>
          </template>

          <template #open_amount-cell="{ row }">
            <span
              v-if="row.original.open_amount && Number.parseFloat(row.original.open_amount) > 0"
              class="font-tabular text-orange-600"
            >
              {{ formatCurrency(row.original.open_amount) }}
            </span>
            <span v-else class="text-stone-400">–</span>
          </template>

          <template #due_date-cell="{ row }">
            <template v-if="row.original.due_date">
              <span
                class="font-tabular text-sm"
                :class="isOverdue(row.original) ? 'text-red-600 font-medium' : ''"
              >
                {{ formatDate(row.original.due_date) }}
              </span>
              <UIcon
                v-if="isOverdue(row.original)"
                name="i-lucide-alert-circle"
                class="ml-1 size-3.5 text-red-500"
                title="Überfällig"
              />
            </template>
            <span v-else class="text-stone-400">–</span>
          </template>

          <template #type-cell="{ row }">
            <UBadge
              :color="receiptTypeColor(row.original.type)"
              variant="soft"
            >
              {{ receiptTypeLabel(row.original.type) }}
            </UBadge>
          </template>

          <template #status-cell="{ row }">
            <div class="flex items-center gap-1.5">
              <UBadge
                :color="row.original.payment_status === 'paid' ? 'success' : 'warning'"
                variant="soft"
              >
                {{ row.original.payment_status === 'paid' ? 'Bezahlt' : 'Offen' }}
              </UBadge>
              <UIcon
                v-if="row.original.is_locked"
                name="i-lucide-lock"
                class="size-3.5 text-stone-400"
                title="Festgeschrieben"
              />
            </div>
          </template>

          <template #actions-cell="{ row }">
            <UDropdownMenu
              :items="getDropdownItems(row.original)"
              :content="{ align: 'end' }"
            >
              <UButton
                icon="i-lucide-more-horizontal"
                color="neutral"
                variant="ghost"
                size="md"
              />
            </UDropdownMenu>
          </template>
        </UTable>

        <!-- Pagination -->
        <PaginationFooter
          v-model:page="filters.page"
          v-model:page-size="filters.page_size"
          :total="receipts?.total || 0"
          label="Belege"
        />
      </UCard>
    </div>

    <!-- Delete Confirmation Modal -->
    <ConfirmModal
      v-model:open="isDeleteOpen"
      title="Beleg löschen"
      :message="`Beleg ${receiptToDelete?.receipt_number} wirklich löschen? Diese Aktion kann nicht rückgängig gemacht werden.`"
      confirm-label="Löschen"
      confirm-color="error"
      :loading="isDeleting"
      @confirm="confirmDelete"
    />

    <!-- Linking Modal -->
    <LinkingModal
      :mode="linkingMode"
      :receipt-id="linkingReceiptId"
      :open="isLinkingModalOpen"
      @update:open="isLinkingModalOpen = $event"
      @linked="handleLinked"
    />
  </div>
</template>
