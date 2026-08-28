<script setup lang="ts">
import type { AICostResponse } from '~/types/api'

const { data: aiCosts } = useFetch<AICostResponse>('/api/v1/dashboard/ai-costs', {
  key: 'dashboard-ai-costs',
})

const hasData = computed(() => (aiCosts.value?.total_extractions ?? 0) > 0)

const showBreakdown = ref(false)

function formatCost(cents: number): string {
  if (cents < 100) {
    return `${cents.toFixed(1)} ct`
  }
  return (cents / 100).toLocaleString('de-DE', { style: 'currency', currency: 'EUR' })
}

function providerLabel(provider: string): string {
  const labels: Record<string, string> = {
    gemini: 'Gemini',
    openai: 'OpenAI',
    anthropic: 'Anthropic',
    zugferd: 'ZUGFeRD',
  }
  return labels[provider] ?? provider
}
</script>

<template>
  <SectionCard v-if="hasData" title="KI-Erkennung">
    <div class="flex items-baseline gap-3">
      <span class="font-tabular text-[28px] font-semibold leading-none text-stone-900 dark:text-stone-100">
        {{ aiCosts!.total_extractions }}
      </span>
      <span class="text-[13px] text-stone-400">
        Belege erkannt
      </span>
    </div>

    <div class="mt-2 flex items-center gap-2 text-sm text-stone-500">
      <UIcon name="i-lucide-coins" class="size-4" />
      <span class="font-tabular">{{ formatCost(aiCosts!.total_cost_cents) }}</span>
      <span>diesen Monat</span>
    </div>

    <!-- Provider breakdown (collapsible) -->
    <div v-if="aiCosts!.by_provider.length > 1" class="mt-3">
      <button
        class="flex items-center gap-1 text-xs text-stone-400 hover:text-stone-600 dark:hover:text-stone-300"
        @click="showBreakdown = !showBreakdown"
      >
        <UIcon :name="showBreakdown ? 'i-lucide-chevron-up' : 'i-lucide-chevron-down'" class="size-3.5" />
        Details
      </button>

      <div v-show="showBreakdown" class="mt-2 space-y-1.5">
        <div
          v-for="provider in aiCosts!.by_provider"
          :key="provider.provider"
          class="flex items-center justify-between text-xs text-stone-500"
        >
          <span>{{ providerLabel(provider.provider) }}</span>
          <span class="font-tabular">{{ provider.extraction_count }}× · {{ formatCost(provider.total_cost_cents) }}</span>
        </div>
      </div>
    </div>
  </SectionCard>
</template>
