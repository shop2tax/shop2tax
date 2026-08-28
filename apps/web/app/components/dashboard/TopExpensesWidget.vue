<script setup lang="ts">
const props = defineProps<{
  dateFrom?: string
  dateTo?: string
}>()

const filters = computed(() => ({
  type: 'expense' as const,
  start_date: props.dateFrom,
  end_date: props.dateTo,
  page_size: 500,
}))

const { data: receiptData } = useReceipts(filters)

const ranked = computed(() => {
  const receipts = receiptData.value?.receipts || []
  const grouped = new Map<string, number>()

  for (const receipt of receipts) {
    for (const item of receipt.line_items) {
      if (!item.skr03_account_name)
        continue
      const amount = Number.parseFloat(String(item.amount))
      const current = grouped.get(item.skr03_account_name) || 0
      grouped.set(item.skr03_account_name, current + amount)
    }
  }

  const sorted = [...grouped.entries()]
    .map(([name, amount]) => ({ name, amount }))
    .sort((a, b) => a.amount - b.amount)
    .slice(0, 5)

  const firstEntry = sorted[0]
  const max = firstEntry ? Math.abs(firstEntry.amount) : 1
  return sorted.map((entry, index) => ({
    rank: index + 1,
    name: entry.name,
    amount: entry.amount,
    width: `${(Math.abs(entry.amount) / max) * 100}%`,
  }))
})

function formatCurrency(value: number) {
  return `${value.toLocaleString('de-DE', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} €`
}
</script>

<template>
  <SectionCard title="Top Ausgaben">
    <template #header>
      <NuxtLink
        to="/receipts"
        class="flex items-center gap-1.5 text-[13px] font-medium text-primary-600 transition-colors hover:text-primary-700"
      >
        Alle Belege
        <UIcon name="i-lucide-arrow-right" class="size-3.5" />
      </NuxtLink>
    </template>

    <div class="mt-3 flex flex-1 flex-col gap-2">
      <div
        v-for="entry in ranked"
        :key="entry.rank"
        class="relative flex h-[26px] items-center justify-between px-2"
      >
        <div
          class="pointer-events-none absolute inset-0 rounded bg-primary-50/50"
          :style="{ width: entry.width }"
        />
        <div class="relative z-10 flex items-center gap-3">
          <span class="w-3 font-tabular text-[12px] text-stone-300">{{ entry.rank }}</span>
          <span class="text-[13px] font-medium text-stone-900">{{ entry.name }}</span>
        </div>
        <span class="relative z-10 font-tabular text-[13px] text-stone-600">
          {{ formatCurrency(entry.amount) }}
        </span>
      </div>

      <div v-if="ranked.length === 0" class="flex flex-1 items-center justify-center">
        <span class="text-[13px] text-stone-400">Keine Ausgabenbelege</span>
      </div>
    </div>
  </SectionCard>
</template>
