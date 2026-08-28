<script setup lang="ts">
import type { TransactionResponse } from '~/types/api'

type DropdownMenuItem = { label: string, icon?: string, onSelect: () => void } | { type: 'separator' }

const props = withDefaults(defineProps<{
  transactions: TransactionResponse[]
  total?: number
  loading?: boolean
  page?: number
  pageSize?: number
  showActions?: boolean
  showPagination?: boolean
  rowMenuItems?: (transaction: TransactionResponse) => DropdownMenuItem[]
  selectable?: boolean
  selectedIds?: Set<string>
}>(), {
  total: 0,
  loading: false,
  page: 1,
  pageSize: 25,
  showActions: true,
  showPagination: true,
  selectable: false,
})

const emit = defineEmits<{
  'update:page': [page: number]
  'update:pageSize': [pageSize: number]
  'update:selectedIds': [ids: Set<string>]
  'navigateReceipt': [receiptId: string]
  'openLinkedReceipts': [transaction: TransactionResponse]
  'createReceipt': [transactionId: string]
  'linkReceipt': [transaction: TransactionResponse]
}>()

const { formatCurrency, formatDate, amountColorClass } = useFormatters()

// Status helpers
function getStatusColor(status: string): 'error' | 'warning' | 'success' | 'neutral' {
  switch (status) {
    case 'open': return 'error'
    case 'assigned': return 'warning'
    case 'booked': return 'success'
    case 'automatic': return 'success'
    case 'private': return 'neutral'
    case 'internal': return 'neutral'
    default: return 'neutral'
  }
}

function getStatusLabel(status: string): string {
  switch (status) {
    case 'open': return 'Offen'
    case 'assigned': return 'Zugeordnet'
    case 'booked': return 'Gebucht'
    case 'automatic': return 'Automatisch'
    case 'private': return 'Privat'
    case 'internal': return 'Geldbewegung'
    default: return status
  }
}

const columns = computed(() => {
  const cols: { accessorKey: string, header: string }[] = []
  if (props.selectable) {
    cols.push({ accessorKey: 'select', header: '' })
  }
  cols.push(
    { accessorKey: 'status', header: 'Status' },
    { accessorKey: 'date', header: 'Datum' },
    { accessorKey: 'name_description', header: 'Name / Verwendungszweck' },
    { accessorKey: 'amount', header: 'Betrag' },
    { accessorKey: 'open_amount', header: 'Offen (Brutto)' },
    { accessorKey: 'source', header: 'Quelle' },
    { accessorKey: 'linked_receipts', header: 'Verknüpfungen' },
  )
  if (props.showActions) {
    cols.push({ accessorKey: 'actions', header: '' })
  }
  return cols
})

// --- Selection helpers (multi-select mode) ---
const selectedIdsSet = computed(() => props.selectedIds ?? new Set<string>())

const pageTransactionIds = computed(() => props.transactions.map(t => t.id))

const isAllPageSelected = computed(() => {
  if (props.transactions.length === 0)
    return false
  return pageTransactionIds.value.every(id => selectedIdsSet.value.has(id))
})

const isSomePageSelected = computed(() => {
  return pageTransactionIds.value.some(id => selectedIdsSet.value.has(id)) && !isAllPageSelected.value
})

function toggleRow(transactionId: string) {
  const newSet = new Set(selectedIdsSet.value)
  if (newSet.has(transactionId)) {
    newSet.delete(transactionId)
  }
  else {
    newSet.add(transactionId)
  }
  emit('update:selectedIds', newSet)
}

function toggleAllPage() {
  const newSet = new Set(selectedIdsSet.value)
  if (isAllPageSelected.value) {
    // Deselect all on this page
    for (const id of pageTransactionIds.value) {
      newSet.delete(id)
    }
  }
  else {
    // Select all on this page
    for (const id of pageTransactionIds.value) {
      newSet.add(id)
    }
  }
  emit('update:selectedIds', newSet)
}

function isRowSelected(transactionId: string): boolean {
  return selectedIdsSet.value.has(transactionId)
}
</script>

<template>
  <div>
    <UTable
      :data="transactions"
      :loading="loading"
      :columns="columns"
      :empty-state="{ icon: 'i-lucide-inbox', label: 'Keine Buchungen gefunden' }"
    >
      <!-- Selection checkbox header (select all on page) -->
      <template v-if="selectable" #select-header>
        <UCheckbox
          :model-value="isAllPageSelected"
          :indeterminate="isSomePageSelected"
          @update:model-value="toggleAllPage"
        />
      </template>

      <!-- Selection checkbox cell -->
      <template v-if="selectable" #select-cell="{ row }">
        <UCheckbox
          :model-value="isRowSelected(row.original.id)"
          @click.stop
          @update:model-value="toggleRow(row.original.id)"
        />
      </template>

      <template #status-cell="{ row }">
        <UBadge
          :color="getStatusColor(row.original.status)"
          variant="soft"
          size="md"
        >
          {{ getStatusLabel(row.original.status) }}
        </UBadge>
      </template>

      <template #date-cell="{ row }">
        {{ formatDate(row.original.date) }}
      </template>

      <template #name_description-cell="{ row }">
        <div class="max-w-64">
          <div class="font-medium truncate">
            {{ row.original.counterparty }}
          </div>
          <div class="text-xs text-gray-500 truncate">
            {{ row.original.description }}
          </div>
        </div>
      </template>

      <template #amount-cell="{ row }">
        <div class="flex items-center gap-1.5">
          <span
            class="font-tabular"
            :class="amountColorClass(row.original.amount)"
          >
            {{ formatCurrency(row.original.amount) }}
          </span>
          <UBadge
            v-if="row.original.original_currency && row.original.original_currency !== 'EUR'"
            color="neutral"
            variant="subtle"
            size="xs"
            :title="row.original.original_amount ? `Original: ${Number.parseFloat(row.original.original_amount).toLocaleString('de-DE', { minimumFractionDigits: 2 })} ${row.original.original_currency}` : undefined"
          >
            {{ row.original.original_currency }}
          </UBadge>
        </div>
      </template>

      <template #open_amount-cell="{ row }">
        <span
          v-if="Number.parseFloat(row.original.open_amount) > 0"
          class="font-tabular text-orange-600"
        >
          {{ formatCurrency(row.original.open_amount) }}
        </span>
        <span v-else class="text-gray-400">–</span>
      </template>

      <template #source-cell="{ row }">
        <UBadge color="neutral" variant="soft">
          {{ row.original.source_config_name ?? '–' }}
        </UBadge>
      </template>

      <template #linked_receipts-cell="{ row }">
        <template v-if="row.original.linked_receipts.length > 0">
          <UButton
            v-if="row.original.linked_receipts.length === 1"
            variant="link"
            color="primary"
            size="xs"
            class="px-0"
            @click="emit('navigateReceipt', row.original.linked_receipts[0]!.id)"
          >
            <UIcon name="i-lucide-file-text" class="size-3 mr-1" />
            {{ row.original.linked_receipts[0]!.receipt_number }}
          </UButton>
          <UButton
            v-else
            variant="link"
            color="primary"
            size="xs"
            class="px-0"
            @click="emit('openLinkedReceipts', row.original)"
          >
            <UIcon name="i-lucide-files" class="size-3 mr-1" />
            {{ row.original.linked_receipts.length }} Dokumente
          </UButton>
        </template>
        <span v-else class="text-gray-400">–</span>
      </template>

      <template v-if="showActions" #actions-cell="{ row }">
        <div class="flex items-center gap-1">
          <UButton
            icon="i-lucide-file-plus"
            color="neutral"
            variant="ghost"
            size="xs"
            title="Beleg erstellen"
            @click="emit('createReceipt', row.original.id)"
          />
          <UButton
            icon="i-lucide-link"
            color="neutral"
            variant="ghost"
            size="xs"
            title="Beleg verknüpfen"
            @click="emit('linkReceipt', row.original)"
          />
          <UDropdownMenu
            v-if="rowMenuItems"
            :items="rowMenuItems(row.original)"
            :content="{ align: 'end' }"
          >
            <UButton
              icon="i-lucide-more-horizontal"
              color="neutral"
              variant="ghost"
              size="xs"
            />
          </UDropdownMenu>
        </div>
      </template>
    </UTable>

    <!-- Pagination -->
    <PaginationFooter
      v-if="showPagination"
      :total="total"
      :page="page"
      :page-size="pageSize"
      label="Buchungen"
      @update:page="emit('update:page', $event)"
      @update:page-size="emit('update:pageSize', $event)"
    />
  </div>
</template>
