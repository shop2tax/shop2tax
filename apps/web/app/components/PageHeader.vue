<script setup lang="ts">
defineProps<{
  title: string
  backTo?: string
}>()
</script>

<template>
  <div class="flex h-20 items-center justify-between border-b border-stone-200 bg-stone-50 px-6 dark:border-stone-800 dark:bg-stone-950">
    <div class="flex items-center gap-2">
      <UButton
        v-if="backTo"
        :to="backTo"
        icon="i-lucide-arrow-left"
        color="neutral"
        variant="ghost"
        size="md"
      />
      <h1 class="font-display text-xl font-semibold text-stone-700 dark:text-stone-300">
        {{ title }}
      </h1>
    </div>
    <div v-if="$slots.default" class="flex items-center gap-4">
      <slot />
    </div>
  </div>
</template>
