<script setup lang="ts">
interface SyncLogEntry {
  start_date: string
  end_date: string
  fetched_count: number
  imported_count: number
  status: string
  created_at: string
  fee_count?: number
  skipped_count?: number
}

defineProps<{
  data: SyncLogEntry[]
  loading?: boolean
  total?: number
  pageSize?: number
  extraColumnKey?: 'fee_count' | 'skipped_count'
  extraColumnLabel?: string
}>()

const page = defineModel<number>('page', { default: 1 })

const { formatDate, formatDateTime } = useFormatters()

function statusColor(status: string): 'success' | 'warning' | 'error' {
  if (status === 'success')
    return 'success'
  if (status === 'partial')
    return 'warning'
  return 'error'
}

const columns = computed(() => {
  const baseColumns = [
    { accessorKey: 'period', header: 'Zeitraum' },
    { accessorKey: 'fetched_count', header: 'Abgerufen' },
    { accessorKey: 'imported_count', header: 'Importiert' },
  ]

  // Extra column is inserted dynamically
  // Will be rendered via slot

  return [
    ...baseColumns,
    { accessorKey: 'extra', header: '' }, // Placeholder for extra column
    { accessorKey: 'status', header: 'Status' },
    { accessorKey: 'created_at', header: 'Datum' },
  ]
})
</script>

<template>
  <SectionCard title="Sync-Verlauf">
    <UTable
      :data="data"
      :columns="columns"
      :loading="loading"
    >
      <template #period-cell="{ row }">
        <span class="text-sm">
          {{ formatDate(row.original.start_date) }} – {{ formatDate(row.original.end_date) }}
        </span>
      </template>

      <template #fetched_count-cell="{ row }">
        <span class="font-tabular">{{ row.original.fetched_count }}</span>
      </template>

      <template #imported_count-cell="{ row }">
        <span class="font-tabular">{{ row.original.imported_count }}</span>
      </template>

      <template #extra-header>
        {{ extraColumnLabel }}
      </template>

      <template #extra-cell="{ row }">
        <span v-if="extraColumnKey" class="font-tabular">
          {{ row.original[extraColumnKey] ?? '-' }}
        </span>
      </template>

      <template #status-cell="{ row }">
        <UBadge :color="statusColor(row.original.status)" variant="soft" size="sm">
          {{ row.original.status }}
        </UBadge>
      </template>

      <template #created_at-cell="{ row }">
        <span class="text-sm text-stone-500">{{ formatDateTime(row.original.created_at) }}</span>
      </template>
    </UTable>

    <template v-if="total && pageSize" #footer>
      <PaginationFooter
        v-model:page="page"
        :page-size="pageSize"
        :total="total"
        label="Einträge"
      />
    </template>
  </SectionCard>
</template>
