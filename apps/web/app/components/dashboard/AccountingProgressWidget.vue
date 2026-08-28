<script setup lang="ts">
const props = defineProps<{
  transactions: Array<{ status: string }>
}>()

const total = computed(() => props.transactions.length)
const open = computed(() => props.transactions.filter(t => t.status === 'open').length)
const assigned = computed(() => props.transactions.filter(t => t.status === 'assigned').length)
const booked = computed(() => props.transactions.filter(t => t.status === 'booked' || t.status === 'automatic').length)

const percentage = computed(() => {
  if (!total.value)
    return 0
  return Math.round(((assigned.value + booked.value) / total.value) * 100)
})

const bookedPercent = computed(() => {
  if (!total.value)
    return 0
  return Math.round((booked.value / total.value) * 100)
})

const assignedPercent = computed(() => {
  if (!total.value)
    return 0
  return Math.round((assigned.value / total.value) * 100)
})
</script>

<template>
  <SectionCard title="Buchungsfortschritt">
    <template #header>
      <NuxtLink
        to="/transactions"
        class="flex items-center gap-1.5 text-[13px] font-medium text-primary-600 transition-colors hover:text-primary-700"
      >
        Alle Buchungen
        <UIcon name="i-lucide-arrow-right" class="size-3.5" />
      </NuxtLink>
    </template>

    <div class="mt-1 flex items-baseline gap-2">
      <span class="font-tabular text-[28px] font-semibold leading-none text-stone-900">
        {{ percentage }} %
      </span>
      <span class="text-[13px] text-stone-500">
        {{ assigned + booked }} von {{ total }}
      </span>
    </div>

    <div class="mt-3 flex h-2 w-full overflow-hidden rounded-full bg-stone-100">
      <div
        class="h-full bg-emerald-500 transition-all duration-700 ease-out"
        :style="{ width: `${bookedPercent}%` }"
      />
      <div
        class="h-full bg-amber-400 transition-all duration-700 ease-out"
        :style="{ width: `${assignedPercent}%` }"
      />
    </div>

    <div class="mt-3 flex items-center gap-4">
      <div class="flex items-center gap-1.5">
        <div class="size-1.5 rounded-full bg-red-400" />
        <span class="text-[12px] text-stone-500">
          <span class="font-tabular">{{ open }}</span> offen
        </span>
      </div>
      <div class="flex items-center gap-1.5">
        <div class="size-1.5 rounded-full bg-amber-400" />
        <span class="text-[12px] text-stone-500">
          <span class="font-tabular">{{ assigned }}</span> zugeordnet
        </span>
      </div>
      <div class="flex items-center gap-1.5">
        <div class="size-1.5 rounded-full bg-emerald-400" />
        <span class="text-[12px] text-stone-500">
          <span class="font-tabular">{{ booked }}</span> gebucht
        </span>
      </div>
    </div>
  </SectionCard>
</template>
