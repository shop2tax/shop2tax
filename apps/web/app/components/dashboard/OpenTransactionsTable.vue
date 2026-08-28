<script setup lang="ts">
import type { TransactionResponse } from '~/types/api'

defineProps<{
  transactions: TransactionResponse[]
  total: number
  periodLabel: string
}>()

const router = useRouter()
</script>

<template>
  <SectionCard title="Die letzten 10 offenen Buchungen">
    <template v-if="total > transactions.length" #header>
      <NuxtLink
        to="/transactions?status=open"
        class="flex items-center gap-1.5 text-[13px] font-medium text-primary-600 transition-colors hover:text-primary-700"
      >
        Alle {{ total }} anzeigen
        <UIcon name="i-lucide-arrow-right" class="size-3.5" />
      </NuxtLink>
    </template>

    <template v-if="transactions.length > 0">
      <TransactionsTable
        :transactions="transactions"
        :total="total"
        :show-actions="false"
        :show-pagination="false"
        @navigate-receipt="(id: string) => router.push(`/receipts/${id}`)"
      />
    </template>

    <div v-else class="py-12 text-center">
      <div class="mx-auto mb-3 flex size-12 items-center justify-center rounded-full bg-emerald-50">
        <UIcon name="i-lucide-check-check" class="size-6 text-emerald-500" />
      </div>
      <p class="font-medium text-stone-700">
        Keine offenen Buchungen
      </p>
      <p class="mt-1 text-sm text-stone-500">
        Alle Buchungen für {{ periodLabel }} sind kontiert.
      </p>
      <NuxtLink
        to="/import"
        class="mt-4 inline-flex items-center gap-1.5 rounded-lg bg-primary-50 px-3 py-1.5 text-[13px] font-medium text-primary-700 transition-colors hover:bg-primary-100"
      >
        <UIcon name="i-lucide-upload" class="size-3.5" />
        CSV importieren
      </NuxtLink>
    </div>
  </SectionCard>
</template>
