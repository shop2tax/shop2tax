<script setup lang="ts">
import type { ParsedRowResponse } from '~/types/api'

defineProps<{
  rows: ParsedRowResponse[]
  selectedRows: Set<number>
  isMappingComplete: boolean
}>()

const emit = defineEmits<{
  toggleRow: [index: number]
  toggleAll: [count: number]
}>()

const { formatCurrency, formatDate, amountColorClass } = useFormatters()

const columns = [
  { accessorKey: 'select', header: '' },
  { accessorKey: 'rowNumber', header: '#' },
  { accessorKey: 'date', header: 'Datum' },
  { accessorKey: 'counterparty', header: 'Name' },
  { accessorKey: 'description', header: 'Verwendungszweck' },
  { accessorKey: 'amount', header: 'Betrag' },
]
</script>

<template>
  <!-- Not ready state -->
  <div v-if="!isMappingComplete && rows.length === 0" class="py-8 text-center text-stone-400">
    <UIcon name="i-lucide-table" class="mx-auto mb-2 size-10" />
    <p>Ordne alle Pflichtfelder zu, um die Vorschau zu sehen</p>
  </div>

  <!-- Preview Table -->
  <UTable
    v-if="rows.length > 0"
    :data="rows"
    :columns="columns"
  >
    <template #select-header>
      <UCheckbox
        :model-value="selectedRows.size === rows.length"
        :indeterminate="selectedRows.size > 0 && selectedRows.size < rows.length"
        @update:model-value="emit('toggleAll', rows.length)"
      />
    </template>

    <template #select-cell="{ row }">
      <UCheckbox
        :model-value="selectedRows.has(row.index)"
        @update:model-value="emit('toggleRow', row.index)"
      />
    </template>

    <template #rowNumber-cell="{ row }">
      <span class="font-tabular text-stone-400">{{ row.index + 1 }}</span>
    </template>

    <template #date-cell="{ row }">
      {{ row.original.date ? formatDate(row.original.date) : '—' }}
    </template>

    <template #counterparty-cell="{ row }">
      <div class="flex items-center gap-1.5">
        <span>{{ row.original.counterparty ?? '—' }}</span>
        <UTooltip v-if="row.original.oms_order_id" text="Wird nach Import automatisch mit Beleg verknüpft">
          <UIcon name="i-lucide-link-2" class="size-4 text-primary-500" />
        </UTooltip>
      </div>
    </template>

    <template #description-cell="{ row }">
      <div class="text-stone-500">
        {{ row.original.description ?? '—' }}
      </div>
    </template>

    <template #amount-cell="{ row }">
      <span
        v-if="row.original.amount"
        class="font-tabular"
        :class="amountColorClass(String(row.original.amount))"
      >
        {{ formatCurrency(row.original.amount) }}
      </span>
      <span v-else>—</span>
    </template>
  </UTable>
</template>
