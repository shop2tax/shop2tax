<script setup lang="ts">
const props = defineProps<{
  limit?: number
}>()

// 📅 Always full current year — €22.000 threshold is annual
const year = new Date().getFullYear()
const yearFilters = computed(() => ({
  date_from: `${year}-01-01`,
  date_to: `${year}-12-31`,
  page_size: 500,
}))

const { data: yearData } = useTransactions(yearFilters)
const yearTransactions = computed(() => yearData.value?.items || [])

const threshold = computed(() => props.limit ?? 22_000)

const revenue = computed(() =>
  yearTransactions.value
    .map(t => Number.parseFloat(t.amount))
    .filter(a => a > 0)
    .reduce((sum, a) => sum + a, 0),
)

const percentage = computed(() => {
  if (!threshold.value)
    return 0
  return Math.min((revenue.value / threshold.value) * 100, 100)
})

const remaining = computed(() => threshold.value - revenue.value)

function formatCurrency(value: number) {
  return value.toLocaleString('de-DE', { style: 'currency', currency: 'EUR', minimumFractionDigits: 0, maximumFractionDigits: 0 })
}

function formatPercent(value: number) {
  return value.toLocaleString('de-DE', { minimumFractionDigits: 1, maximumFractionDigits: 1 })
}
</script>

<template>
  <SectionCard :title="`Kleinunternehmerregelung ${year}`">
    <div class="mt-1 flex items-baseline gap-2">
      <span class="font-tabular text-[28px] font-semibold leading-none text-stone-900">
        {{ formatCurrency(revenue) }}
      </span>
      <span class="text-[13px] text-stone-400">
        von {{ formatCurrency(threshold) }}
      </span>
    </div>

    <div class="relative mt-3 h-2 w-full overflow-hidden rounded-full bg-stone-100">
      <div
        class="absolute inset-y-0 left-0 rounded-full bg-primary-600 transition-all duration-700 ease-out"
        :style="{ width: `${percentage}%` }"
      />
    </div>

    <div class="mt-1 text-right">
      <span class="font-tabular text-[12px] font-medium text-primary-600">
        {{ formatPercent(percentage) }} %
      </span>
    </div>

    <div class="mt-auto pt-2">
      <span class="text-[12px] text-stone-400">
        Verbleibend: {{ formatCurrency(remaining) }}
      </span>
    </div>
  </SectionCard>
</template>
