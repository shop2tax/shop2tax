<script setup lang="ts">
definePageMeta({
  middleware: ['auth'],
})

// 📅 Period filter — compute date range from selection
const selectedPeriod = ref('month')
const periodOptions = [
  { label: 'Dieser Monat', value: 'month' },
  { label: 'Letzter Monat', value: 'last-month' },
  { label: 'Letzte 3 Monate', value: 'last-3-months' },
  { label: 'Dieses Quartal', value: 'quarter' },
  { label: 'Dieses Jahr', value: 'year' },
  { label: 'Alle', value: 'all' },
]

const dateRange = computed(() => {
  const now = new Date()
  const year = now.getFullYear()
  const month = now.getMonth()

  // Pad to YYYY-MM-DD without UTC conversion (toISOString shifts dates in CET)
  const format = (date: Date) =>
    `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`

  switch (selectedPeriod.value) {
    case 'month':
      return {
        date_from: format(new Date(year, month, 1)),
        date_to: format(new Date(year, month + 1, 0)),
      }
    case 'last-month':
      return {
        date_from: format(new Date(year, month - 1, 1)),
        date_to: format(new Date(year, month, 0)),
      }
    case 'last-3-months':
      return {
        date_from: format(new Date(year, month - 2, 1)),
        date_to: format(new Date(year, month + 1, 0)),
      }
    case 'quarter': {
      const quarterStart = Math.floor(month / 3) * 3
      return {
        date_from: format(new Date(year, quarterStart, 1)),
        date_to: format(new Date(year, quarterStart + 3, 0)),
      }
    }
    case 'year':
      return {
        date_from: format(new Date(year, 0, 1)),
        date_to: format(new Date(year, 11, 31)),
      }
    default:
      return {}
  }
})

// Readable label for current period
const periodLabel = computed(() => {
  const now = new Date()
  const formatter = new Intl.DateTimeFormat('de-DE', { month: 'long', year: 'numeric' })
  switch (selectedPeriod.value) {
    case 'month':
      return formatter.format(now)
    case 'last-month': {
      const lastMonth = new Date(now.getFullYear(), now.getMonth() - 1, 1)
      return formatter.format(lastMonth)
    }
    case 'last-3-months': {
      const threeMonthsAgo = new Date(now.getFullYear(), now.getMonth() - 2, 1)
      return `${formatter.format(threeMonthsAgo)} – ${formatter.format(now)}`
    }
    case 'quarter':
      return `Q${Math.floor(now.getMonth() / 3) + 1} ${now.getFullYear()}`
    case 'year':
      return String(now.getFullYear())
    default:
      return 'Gesamt'
  }
})

// All transactions for selected period (for stats)
const periodFilters = computed(() => ({
  ...dateRange.value,
  page_size: 500,
}))

// Open transactions only (the work queue)
const unmatchedFilters = computed(() => ({
  ...dateRange.value,
  status: 'open',
  page_size: 10,
}))

const { data: periodData } = useTransactions(periodFilters)
const { data: unmatchedData } = useTransactions(unmatchedFilters)
const { data: siteSettings } = useSiteSettings()

const periodTransactions = computed(() => periodData.value?.items || [])
</script>

<template>
  <div class="flex-1 min-w-0">
    <PageHeader title="Dashboard">
      <p class="shrink-0 text-[13px] text-stone-500">
        {{ periodLabel }} · <span class="font-tabular">{{ periodData?.total || 0 }}</span> Buchungen
      </p>
      <USelect
        v-model="selectedPeriod"
        :items="periodOptions"
        class="min-w-40"
        size="md"
      />
    </PageHeader>

    <div class="p-6 space-y-6">
      <div class="grid grid-cols-2 gap-4">
        <DashboardAccountingProgressWidget :transactions="periodTransactions" />
        <DashboardSmallBusinessWidget v-if="siteSettings?.is_small_business" />
        <DashboardProfitLossWidget :transactions="periodTransactions" />
        <DashboardTopExpensesWidget :date-from="dateRange.date_from" :date-to="dateRange.date_to" />
        <DashboardAICostsWidget />
      </div>

      <DashboardOpenTransactionsTable
        :transactions="unmatchedData?.items || []"
        :total="unmatchedData?.total || 0"
        :period-label="periodLabel"
      />
    </div>
  </div>
</template>
