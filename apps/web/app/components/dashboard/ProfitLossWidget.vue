<script setup lang="ts">
const props = defineProps<{
  transactions: Array<{ amount: string }>
}>()

const revenue = computed(() =>
  props.transactions
    .map(t => Number.parseFloat(t.amount))
    .filter(a => a > 0)
    .reduce((sum, a) => sum + a, 0),
)

const expenses = computed(() =>
  props.transactions
    .map(t => Number.parseFloat(t.amount))
    .filter(a => a < 0)
    .reduce((sum, a) => sum + a, 0),
)

const balance = computed(() => revenue.value + expenses.value)

function formatCurrency(value: number) {
  const formatted = Math.abs(value).toLocaleString('de-DE', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  const prefix = value >= 0 ? '+' : '-'
  return `${prefix}${formatted} €`
}
</script>

<template>
  <SectionCard title="Gewinn & Verlust">
    <div class="mt-3 flex flex-col gap-2">
      <div class="flex items-center justify-between">
        <span class="text-[13px] text-stone-500">Einnahmen</span>
        <span class="font-tabular text-[14px] font-medium text-emerald-500">
          {{ formatCurrency(revenue) }}
        </span>
      </div>

      <div class="flex items-center justify-between">
        <span class="text-[13px] text-stone-500">Ausgaben</span>
        <span class="font-tabular text-[14px] font-medium text-red-500">
          {{ formatCurrency(expenses) }}
        </span>
      </div>

      <div class="my-0.5 h-px w-full bg-stone-200" />

      <div class="flex items-center justify-between">
        <span class="text-[14px] font-medium text-stone-900">Saldo</span>
        <span
          class="font-tabular text-[16px] font-semibold"
          :class="balance >= 0 ? 'text-emerald-600' : 'text-red-600'"
        >
          {{ formatCurrency(balance) }}
        </span>
      </div>
    </div>
  </SectionCard>
</template>
