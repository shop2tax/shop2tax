<script setup lang="ts">
defineProps<{
  steps: { number: number, label: string }[]
  currentStep: number
}>()
</script>

<template>
  <div class="flex items-center justify-center rounded-lg border border-stone-200 bg-stone-50 p-4 dark:border-stone-800 dark:bg-stone-900">
    <div class="flex w-full max-w-[400px] items-center justify-between">
      <div v-for="step in steps" :key="step.number" class="flex items-center">
        <div
          class="flex size-8 items-center justify-center rounded-full text-sm font-medium transition-colors"
          :class="currentStep >= step.number
            ? 'bg-primary-500 text-white'
            : 'bg-stone-200 text-stone-500 dark:bg-stone-700 dark:text-stone-400'"
        >
          <UIcon v-if="currentStep > step.number" name="i-lucide-check" class="size-4" />
          <span v-else>{{ step.number }}</span>
        </div>
        <span
          class="ml-2 hidden text-sm font-medium sm:inline"
          :class="currentStep >= step.number ? 'text-stone-900 dark:text-stone-100' : 'text-stone-500 dark:text-stone-400'"
        >
          {{ step.label }}
        </span>
      </div>
    </div>
  </div>
</template>
